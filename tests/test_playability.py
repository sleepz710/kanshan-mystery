"""好玩度五条规则、解锁层数和循环依赖的纯程序测试。"""

from copy import deepcopy
from math import inf
from pathlib import Path

import pytest
import yaml

from backend.studio import check as checker


@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("好玩度检查不得调用模型")

    monkeypatch.setattr(checker, "complete_for", forbidden)
    monkeypatch.setattr(checker, "AsyncOpenAI", forbidden)


@pytest.fixture
def story():
    return {
        "id": "playability", "title": "技术样本", "source": "generated", "intro": "公开说明",
        "facts": [{"id": f"f{cid}", "text": f"角色{cid}的事实"} for cid in ("a", "b", "c")],
        "characters": [
            {"id": "a", "name": "角色甲", "avatar": "a.png", "profile": "公开甲", "persona": "谨慎",
             "knows": ["fa"], "secrets": [], "lies": [{"id": "la", "claim": "甲的谎话", "until": {"shown": "c3"}, "admit": "fa"}]},
            {"id": "b", "name": "角色乙", "avatar": "b.png", "profile": "公开乙", "persona": "谨慎",
             "knows": ["fb"], "secrets": [], "lies": [{"id": "lb", "claim": "乙的谎话", "until": {"shown": "c4"}, "admit": "fb"}]},
            {"id": "c", "name": "角色丙", "avatar": "c.png", "profile": "公开丙", "persona": "谨慎",
             "knows": ["fc"], "secrets": [{"fact": "fc", "until": {"trust": 1}}], "lies": []},
        ],
        "clues": [
            {"id": "c0", "holder": "a", "requires": {}},
            {"id": "c1", "holder": "b", "requires": {}},
            {"id": "c2", "holder": "c", "requires": {}},
            {"id": "c3", "holder": "b", "requires": {"shown": "c0"}},
            {"id": "c4", "holder": "a", "requires": {"exposed": "la"}},
            {"id": "c5", "holder": "c", "requires": {"exposed": "lb"}},
            {"id": "c6", "holder": "c", "requires": {"trust": 2}},
            {"id": "c7", "holder": "b", "requires": {"has": "c2"}},
        ],
        "events": [],
        "kanshan": {"greeting": "开始调查", "hints": [{"done": {"has": "c5"}, "vague": "找证据", "direct": "核对证据"}]},
        "ending": {
            "questions": [{"id": "q1", "text": "技术题", "options": ["甲", "乙"], "answer": "甲"}],
            "endings": [{"id": "truth", "title": "完成", "text": "结果", "when": {"correct": ["q1"]}},
                        {"id": "retry", "title": "再试", "text": "重试", "retry": True}],
            "truth": "技术真相",
        },
    }


def complete_fields(story):
    for clue in story["clues"]:
        clue.setdefault("title", f"线索{clue['id']}")
        clue.setdefault("content", f"内容{clue['id']}")
    return story


def test_official_story_passes_all_five_rules():
    path = Path(__file__).resolve().parents[1] / "stories" / "lost-tuition.yaml"
    official = yaml.safe_load(path.read_text(encoding="utf-8"))
    before = deepcopy(official)
    assert checker.check_structure(official)["ok"]
    assert checker.check_playability(official) == []
    assert official == before
    layers = checker._unlock_layers(official)
    assert max(layers[c["id"]] for c in official["clues"]) == 3


def test_balanced_technical_story_passes_without_mutation(story):
    complete_fields(story)
    before = deepcopy(story)
    assert checker.check_structure(story)["ok"]
    assert checker.check_playability(story) == []
    assert story == before


def test_holder_concentration_reports_actual_counts_and_transfer(story):
    for clue in story["clues"]:
        if clue["id"] in {"c1", "c6", "c7"}:
            clue["holder"] = "a"
    problems = checker.check_playability(story)
    assert len(problems) == 1
    assert all(text in problems[0] for text in ("角色甲", "a", "5/8", "超过一半", "至少将 1 条", "c7"))


def test_exactly_half_is_allowed(story):
    for clue in story["clues"]:
        if clue["id"] in {"c6", "c7"}:
            clue["holder"] = "a"
    assert checker.check_playability(story) == []


def test_four_initial_clues_are_reported(story):
    story["clues"][7]["requires"] = {}
    problems = checker.check_playability(story)
    assert len(problems) == 1
    assert all(text in problems[0] for text in ("开局", "4 条", "超过 3 条", "c7", "至少 1 条"))


def test_event_reward_is_excluded_from_initial_count_even_without_requires(story):
    story["clues"][7].pop("requires")
    story["events"] = [{"id": "e1", "when": {"shown": "c0", "to": "a"}, "confront": ["a", "b"], "unlock": ["c7"]}]
    assert checker.check_playability(story) == []


def test_depth_below_three_reports_deepest_clue(story):
    story["characters"][1]["lies"][0]["until"] = {"shown": "c0"}
    problems = checker.check_playability(story)
    assert len(problems) == 1
    assert all(text in problems[0] for text in ("第 2 层", "不足第 3 层", "c4", "增加"))


def test_each_character_needs_a_clue(story):
    for clue in story["clues"]:
        if clue["id"] in {"c2", "c6"}:
            clue["holder"] = "a"
        elif clue["id"] == "c5":
            clue["holder"] = "b"
    problems = checker.check_playability(story)
    assert len(problems) == 1
    assert all(text in problems[0] for text in ("角色丙", "c", "0 条", "至少 1 条"))


def test_each_character_needs_a_secret_or_lie(story):
    story["characters"][2]["secrets"] = []
    problems = checker.check_playability(story)
    assert len(problems) == 1
    assert all(text in problems[0] for text in ("角色丙", "0 个秘密", "0 句谎话", "增加至少 1"))


def test_self_held_evidence_is_reported(story):
    story["clues"][3]["holder"] = "a"
    problems = checker.check_playability(story)
    assert len(problems) == 1
    assert all(text in problems[0] for text in ("角色甲", "la", "c3", "1 条", "全部由本人持有", "交给其他角色"))


def test_one_external_clue_is_enough_even_with_another_self_held_clue(story):
    story["characters"][0]["lies"][0]["until"] = {"shown": "c3", "has": "c0"}
    assert checker.check_playability(story) == []


@pytest.mark.parametrize("until", [{}, {"trust": 0}, {"trust": 3}])
def test_lie_without_direct_or_indirect_evidence_is_reported(story, until):
    story["characters"][0]["lies"][0]["until"] = until
    assert any("la" in p and "0 条拆谎证据" in p for p in checker.check_playability(story))


@pytest.mark.parametrize("until", [{"event": "e1"}, {"trust": 2, "event": "e1"}, {"exposed": "lb"}])
def test_indirect_evidence_is_exempt_from_holder_rule(story, until):
    story["characters"][0]["lies"][0]["until"] = until
    story["characters"][1]["lies"][0]["until"] = {"shown": "c0"}
    story["events"] = [{"id": "e1", "when": {"has": "c1", "to": "b"}, "confront": ["a", "b"], "unlock": []}]
    assert not any("la" in p and "拆谎证据" in p for p in checker.check_playability(story))


@pytest.mark.parametrize("trust", [0, 1, 2, 3])
def test_every_trust_threshold_counts_as_one_layer(story, trust):
    story["clues"][6]["requires"] = {"trust": trust}
    assert checker._unlock_layers(story)["c6"] == 1


@pytest.mark.parametrize("key", ["shown", "has"])
def test_show_and_has_add_one_layer(story, key):
    story["clues"][7]["requires"] = {key: "c5"}
    layers = checker._unlock_layers(story)
    assert layers["c3"] == 1
    assert layers["la"] == layers["c4"] == 2
    assert layers["lb"] == layers["c5"] == 3
    assert layers["c7"] == 4


def test_and_conditions_take_maximum_and_events_do_not_add_a_layer(story):
    story["events"] = [{"id": "e1", "when": {"shown": "c4", "to": "a"}, "confront": ["a", "b"], "unlock": []}]
    story["clues"][7]["requires"] = {"trust": 3, "shown": "c0", "has": "c5", "exposed": "la", "event": "e1"}
    layers = checker._unlock_layers(story)
    assert layers["e1"] == 3
    assert layers["c7"] == 4


def test_event_reward_uses_shortest_of_own_and_all_event_paths(story):
    story["clues"][6]["requires"] = {"has": "c5"}
    story["events"] = [
        {"id": "deep", "when": {"shown": "c4", "to": "a"}, "confront": ["a", "b"], "unlock": ["c6"]},
        {"id": "short", "when": {"has": "c0", "to": "a"}, "confront": ["a", "b"], "unlock": ["c6"]},
    ]
    layers = checker._unlock_layers(story)
    assert layers["deep"] == 3 and layers["short"] == 1
    assert layers["c6"] == 1
    story["clues"][6]["requires"] = {}
    assert checker._unlock_layers(story)["c6"] == 0


@pytest.mark.parametrize("cycle", ["self", "clues", "lies", "event"])
def test_cycles_terminate_and_identify_unresolved_clues(story, cycle):
    if cycle == "self":
        story["clues"][0]["requires"] = {"shown": "c0"}
    elif cycle == "clues":
        story["clues"][0]["requires"] = {"has": "c7"}
        story["clues"][7]["requires"] = {"shown": "c0"}
    elif cycle == "lies":
        story["characters"][0]["lies"][0]["until"] = {"exposed": "lb"}
        story["characters"][1]["lies"][0]["until"] = {"exposed": "la"}
    else:
        story["clues"][0]["requires"] = {"event": "e1"}
        story["events"] = [{"id": "e1", "when": {"shown": "c0", "to": "a"}, "confront": ["a", "b"], "unlock": []}]
    layers = checker._unlock_layers(story)
    assert any(layers[c["id"]] == inf for c in story["clues"])
    assert any("解锁层数无法计算" in p and "循环依赖" in p for p in checker.check_playability(story))


def test_cycle_with_independent_event_path_converges(story):
    story["clues"][6]["requires"] = {"event": "loop"}
    story["events"] = [
        {"id": "loop", "when": {"shown": "c6", "to": "a"}, "confront": ["a", "b"], "unlock": ["c6"]},
        {"id": "exit", "when": {"has": "c0", "to": "a"}, "confront": ["a", "b"], "unlock": ["c6"]},
    ]
    complete_fields(story)
    assert checker.check_structure(story)["ok"]
    layers = checker._unlock_layers(story)
    assert layers["c6"] == 1 and layers["loop"] == 2
    assert checker.check_playability(story) == []
