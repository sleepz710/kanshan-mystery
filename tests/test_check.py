"""检查器：依赖环、知识越界、结局覆盖及真正的盲答输入。"""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from backend.engine import GameEngine
from backend.studio import check as checker
from backend.studio.mock import mock_story


def sample_story():
    return {
        "id": "missing-letter", "title": "消失的信", "source": "generated",
        "intro": "信封仍在桌上，里面的信却不见了。", "facts": [
            {"id": "f1", "text": "林青换走了信。"}, {"id": "f2", "text": "陈明收到了信。"}],
        "characters": [
            {"id": "lin", "name": "林青", "avatar": "lin.png", "profile": "秘书", "persona": "谨慎", "knows": ["f1"],
             "secrets": [], "lies": [{"id": "l1", "claim": "我没碰过信", "until": {"shown": "c1"}, "admit": "f1"}], "trust_start": 0},
            {"id": "chen", "name": "陈明", "avatar": "chen.png", "profile": "收件人", "persona": "紧张", "knows": ["f2"],
             "secrets": [{"fact": "f2", "until": {"trust": 2}}], "lies": [], "trust_start": 0}],
        "clues": [
            {"id": "c1", "title": "监控", "content": "林青换走了信。", "holder": "chen", "requires": {"trust": 1}},
            {"id": "c2", "title": "收件回执", "content": "陈明签收信件。", "holder": "lin", "requires": {"exposed": "l1"}},
            {"id": "c3", "title": "对质记录", "content": "两人承认信被调换后送到陈明手里。", "holder": "chen", "requires": {"event": "e1"}}],
        "events": [{"id": "e1", "when": {"shown": "c2", "to": "chen"}, "confront": ["lin", "chen"], "unlock": ["c3"]}],
        "kanshan": {"greeting": "一起调查吧", "hints": [{"done": {"exposed": "l1"}, "vague": "看看监控", "direct": "把监控给林青看"}]},
        "ending": {"questions": [
            {"id": "q1", "text": "谁换了信？", "options": ["林青", "陈明"], "answer": "林青"},
            {"id": "q2", "text": "谁收到了信？", "options": ["林青", "陈明"], "answer": "陈明"}],
            "endings": [{"id": "truth", "title": "查清", "when": {"correct": ["q1", "q2"]}, "text": "信的去向查清了"},
                        {"id": "half", "title": "未查清", "text": "继续调查", "retry": True}],
            "truth": "林青换走信后寄给陈明。", "lessons": []},
    }


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")


@pytest.mark.asyncio
async def test_valid_story_and_two_blind_calls(monkeypatch):
    story = sample_story()
    before = deepcopy(story)
    model = AsyncMock(side_effect=[{"answers": {"q1": None, "q2": None}}, {"answers": {"q1": "林青", "q2": "陈明"}}])
    monkeypatch.setattr(checker, "complete_for", model)
    assert await checker.check(story) == {"ok": True, "problems": []}
    assert story == before
    assert [call.kwargs["role"] for call in model.call_args_list] == ["writer", "actor"]
    intro = json.loads(model.call_args_list[0].args[0][1]["content"])
    clues = json.loads(model.call_args_list[1].args[0][1]["content"])
    assert set(intro) == {"intro", "questions"}
    assert set(clues) == {"intro", "questions", "clues"}
    assert all("answer" not in q for q in intro["questions"])
    assert "truth" not in clues and "facts" not in clues


def test_circular_clue_and_lie_are_unreachable():
    story = sample_story()
    story["clues"][0]["requires"] = {"exposed": "l1"}
    result = checker.check_structure(story)
    assert not result["ok"]
    assert any("c1 拿不到" in p for p in result["problems"])
    assert any("l1 拆不穿" in p for p in result["problems"])


def test_event_can_unlock_clue_without_holder_condition():
    story = sample_story()
    story["clues"][2]["requires"] = {"has": "c3"}
    assert checker.check_structure(story)["ok"]


def test_event_reward_cannot_be_obtained_before_its_event():
    story = sample_story()
    story["clues"][2]["requires"] = {}
    story["events"][0]["when"] = {"has": "c3", "to": "chen"}
    result = checker.check_structure(story)
    assert not result["ok"]
    assert any("c3 拿不到" in p for p in result["problems"])


@pytest.mark.parametrize("mutation, fragment", [
    (lambda s: s["characters"][0]["lies"][0].update(admit="f2"), "knows"),
    (lambda s: s["characters"][1]["secrets"][0].update(fact="f1"), "knows"),
    (lambda s: s["clues"][0].update(holder="missing"), "missing"),
    (lambda s: s["clues"][0].update(requires={"has": "missing"}), "missing"),
    (lambda s: s["clues"][0].update(requires={"trust": 4}), "trust"),
    (lambda s: s["events"][0].update(when={"shown": "c2"}), "to"),
    (lambda s: s["events"][0].update(confront=["lin", "lin"]), "不同"),
    (lambda s: s["ending"]["questions"][0].update(answer="不存在"), "选项"),
    (lambda s: s["clues"][0].update(id="f1"), "重复"),
    (lambda s: s["ending"]["endings"][0].update(when={"correct": ["q9"]}), "题号"),
])
def test_invalid_references_and_fields(mutation, fragment):
    story = sample_story()
    mutation(story)
    result = checker.check_structure(story)
    assert not result["ok"] and any(fragment in p for p in result["problems"])


def test_ordered_ending_shadowing_detected():
    story = sample_story()
    story["ending"]["endings"].insert(0, {"id": "early", "title": "提前结束", "text": "结束"})
    result = checker.check_structure(story)
    assert any("truth" in p and "覆盖" in p for p in result["problems"])


def test_chose_and_correct_can_both_be_reached():
    story = sample_story()
    story["ending"]["endings"].insert(1, {"id": "wrong", "title": "误判", "when": {"chose": {"q1": "陈明"}}, "text": "误判"})
    assert checker.check_structure(story)["ok"]


@pytest.mark.asyncio
async def test_missing_evidence_is_reported_by_blind_solver(monkeypatch):
    story = sample_story()
    story["clues"][1]["content"] = "一张空白纸"
    story["clues"][2]["content"] = "一段无关对话"
    model = AsyncMock(side_effect=[{"answers": {"q1": None, "q2": None}}, {"answers": {"q1": "林青", "q2": None}}])
    monkeypatch.setattr(checker, "complete_for", model)
    result = await checker.check(story)
    assert not result["ok"] and any("q2" in p and "线索支撑" in p for p in result["problems"])


@pytest.mark.asyncio
async def test_intro_gives_away_majority(monkeypatch):
    model = AsyncMock(return_value={"answers": {"q1": "林青", "q2": "陈明"}})
    monkeypatch.setattr(checker, "complete_for", model)
    assert any("汤面" in p for p in (await checker.check(sample_story()))["problems"])


@pytest.mark.parametrize("story", [None, [], {}, {"facts": None}])
def test_malformed_external_story_returns_problems(story):
    assert not checker.check_structure(story)["ok"]


def test_writer_schema_describes_only_supported_condition_shapes():
    definitions = checker.Story.model_json_schema()["$defs"]
    condition = definitions["Condition"]
    assert set(condition["properties"]) == {"trust", "shown", "has", "exposed", "event"}
    assert condition["properties"]["trust"]["minimum"] == 0
    assert condition["properties"]["trust"]["maximum"] == 3
    assert condition["properties"]["has"]["pattern"] == r"^[a-z0-9][a-z0-9_-]*$"
    assert definitions["EventWhen"]["required"] == ["to"]
    assert set(definitions["HintCondition"]["properties"]) == {"has", "exposed", "event"}
    for name in ("Condition", "EventWhen", "HintCondition", "CorrectEndingWhen", "ChoseEndingWhen", "FallbackEndingWhen"):
        assert definitions[name]["additionalProperties"] is False
    assert definitions["CorrectEndingWhen"]["required"] == ["correct"]
    assert definitions["CorrectEndingWhen"]["properties"]["correct"]["minItems"] == 1
    assert definitions["ChoseEndingWhen"]["required"] == ["chose"]
    assert definitions["ChoseEndingWhen"]["properties"]["chose"]["minProperties"] == 1
    assert definitions["ChoseEndingWhen"]["properties"]["chose"]["additionalProperties"] is False
    assert definitions["FallbackEndingWhen"]["properties"] == {}
    assert len(definitions["Ending"]["properties"]["when"]["anyOf"]) == 3


@pytest.mark.parametrize("mutation, location", [
    (lambda s: s["clues"][0].update(condition={"has": "c1"}), "clues.0.condition"),
    (lambda s: s["clues"][0].update(requires={"clue": "c1"}), "clues.0.requires.clue"),
    (lambda s: s["clues"][0].update(requires={"has": 1}), "clues.0.requires.has"),
    (lambda s: s["clues"][0].update(requires={"has": "invalid id"}), "clues.0.requires.has"),
    (lambda s: s["clues"][0].update(requires={"trust": True}), "clues.0.requires.trust"),
    (lambda s: s["events"][0].update(when={"has": "c1"}), "events.0.when.to"),
    (lambda s: s["kanshan"]["hints"][0].update(done={"shown": "c1", "to": "lin"}), "kanshan.hints.0.done.shown"),
    (lambda s: s["kanshan"]["hints"][0].update(done={"trust": 1}), "kanshan.hints.0.done.trust"),
    (lambda s: s["ending"]["endings"][0].update(condition={"correct": ["q1"]}), "ending.endings.0.condition"),
    (lambda s: s["ending"]["endings"][0].update(when={"all_correct": True}), "ending.endings.0.when"),
    (lambda s: s["ending"]["endings"][0].update(when={"correct": ["q1"], "chose": {"q2": "陈明"}}), "ending.endings.0.when"),
    (lambda s: s["ending"]["endings"][0].update(when={"correct": []}), "ending.endings.0.when"),
    (lambda s: s["ending"]["endings"][0].update(when={"chose": {}}), "ending.endings.0.when"),
])
def test_unsupported_conditions_return_repairable_field_locations(mutation, location):
    story = sample_story()
    mutation(story)
    result = checker.check_structure(story)
    assert not result["ok"]
    assert any(location in problem for problem in result["problems"])


@pytest.mark.parametrize("when", [
    {"has": "c1", "to": "chen"},
    {"exposed": "l1", "to": "chen"},
    {"trust": 1, "to": "chen"},
])
def test_event_conditions_with_target_match_engine_contract(when, tmp_path):
    story = mock_story()
    story["events"][0]["when"] = when
    assert checker.check_structure(story) == {"ok": True, "problems": []}
    normalized = checker.Story.model_validate(story).model_dump()
    assert normalized["events"][0]["when"] == when
    assert type(normalized["events"][0]["when"]) is dict
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / f"{story['id']}.yaml").write_text(yaml.safe_dump(normalized, allow_unicode=True), encoding="utf-8")
    game = GameEngine(tmp_path / "official", generated).new_game(story["id"])
    assert game["title"] == story["title"]


def test_valid_mock_and_official_v2_keep_plain_condition_dicts():
    official_path = Path(__file__).resolve().parents[1] / "stories" / "lost-tuition.yaml"
    for story in (mock_story(), yaml.safe_load(official_path.read_text(encoding="utf-8"))):
        assert checker.check_structure(story) == {"ok": True, "problems": []}
        normalized = checker.Story.model_validate(story).model_dump()
        assert type(normalized["clues"][0]["requires"]) is dict
        assert type(normalized["events"][0]["when"]) is dict
        assert normalized["ending"]["endings"][-1]["when"] == {}
        GameEngine._validate_story(normalized, normalized["id"])


def test_writer_schema_names_reference_namespaces():
    definitions = checker.Story.model_json_schema()["$defs"]
    for record, field, namespace in (
        ("Event", "confront", "characters.id"),
        ("Event", "unlock", "clues.id"),
        ("Character", "knows", "facts.id"),
        ("Secret", "fact", "facts.id"),
        ("Lie", "admit", "facts.id"),
        ("Clue", "holder", "characters.id"),
        ("EventWhen", "to", "characters.id"),
    ):
        assert namespace in definitions[record]["properties"][field]["description"]
    assert "不得填写 clues.id" in definitions["Event"]["properties"]["confront"]["description"]


def test_wrong_reference_kind_reports_owner_field_and_actual_namespace():
    story = sample_story()
    story["events"][0].update(confront=["c1", "c2"], unlock=["lin"])
    story["characters"][0]["knows"].append("c1")
    story["characters"][1]["secrets"][0]["fact"] = "lin"
    story["characters"][0]["lies"][0]["admit"] = "c2"
    story["clues"][0]["holder"] = "c3"
    before = deepcopy(story)
    result = checker.check_structure(story)
    assert not result["ok"] and story == before
    for diagnostic in (
        "事件 e1.confront[0] 须引用 characters.id，c1 属于 clues.id。",
        "事件 e1.confront[1] 须引用 characters.id，c2 属于 clues.id。",
        "事件 e1.unlock[0] 须引用 clues.id，lin 属于 characters.id。",
        "角色 lin.knows 须引用 facts.id，c1 属于 clues.id。",
        "角色 chen.secrets[0].fact 须引用 facts.id，lin 属于 characters.id。",
        "谎话 l1.admit 须引用 facts.id，c2 属于 clues.id。",
        "线索 c1.holder 须引用 characters.id，c3 属于 clues.id。",
    ):
        assert diagnostic in result["problems"]
