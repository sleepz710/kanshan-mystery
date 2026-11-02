"""检查器：依赖环、知识越界、结局覆盖及真正的盲答输入。"""

import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from backend.studio import check as checker


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
    model = AsyncMock(side_effect=[{"answers": {}}, {"answers": {"q1": "林青", "q2": "陈明"}}])
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
    story["events"][0]["when"] = {"has": "c3"}
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
    model = AsyncMock(side_effect=[{"answers": {}}, {"answers": {"q1": "林青", "q2": None}}])
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
