"""固定生成坏稿及设计前置、指定规模保留回归，全部使用离线数据。"""

from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from backend.studio import check as checker
from backend.studio.mock import mock_story
from backend.studio.service import StudioService


BOOKSTORE_INPUT = (
    "我想玩一个现代校园书店里的案子：闭店后，一本预订书被换成了空白本。"
    "请改编成3个人、8条线索、2句谎话、3个结局题、2个结局的短篇现实推理，"
    "线索能相互印证，人物动机清楚。"
)


def bookstore():
    folder = Path(__file__).resolve().parents[2] / "docs/testing/task18-final/bookstore"
    design = json.loads((folder / "selected-design.json").read_text(encoding="utf-8"))
    story = yaml.safe_load((folder / "story.yaml").read_text(encoding="utf-8"))
    return design, story


def repaired_bookstore():
    design, story = bookstore()
    story["clues"] = [clue for clue in story["clues"] if clue["id"] != "c_late"]
    story["events"] = [event for event in story["events"] if "c_late" not in event["unlock"]]
    for event in story["events"]:
        if event["id"] == "e_lin_confront":
            event["when"]["exposed"] = "l_lin_leave"
        if event["id"] == "e_chen_confront":
            event["when"]["exposed"] = "l_chen_sample"
    return design, story


def test_fixed_bookstore_rejects_extra_clue_and_missing_acquire_prerequisites():
    design, story = bookstore()
    problems = StudioService._evidence_problems(design, story)

    assert any("clues 数量 9" in problem and "设计 8" in problem for problem in problems)
    assert any("c_chen_pickup" in problem and "预订登记单" in problem for problem in problems)
    assert any("c_chen_pickup" in problem and "l_chen_sample" in problem for problem in problems)
    assert any("c_admit" in problem and "预订登记单" in problem for problem in problems)
    assert any("c_admit" in problem and "l_chen_sample" in problem for problem in problems)
    assert StudioService._requested_size_problems([BOOKSTORE_INPUT], design=design) == []
    assert any("8 条线索" in problem and "当前为 9" in problem
               for problem in StudioService._requested_size_problems([BOOKSTORE_INPUT], story=story))


def test_equivalent_event_chain_preserves_all_bookstore_prerequisites():
    design, story = repaired_bookstore()
    assert checker.check_structure(story) == {"ok": True, "problems": []}
    assert StudioService._evidence_problems(design, story) == []
    assert StudioService._requested_size_problems([BOOKSTORE_INPUT], story=story) == []


def test_correct_requires_cannot_hide_a_weaker_event_unlock():
    design, story = repaired_bookstore()
    pickup = next(clue for clue in story["clues"] if clue["id"] == "c_chen_pickup")
    pickup["requires"] = {"shown": "c_monitor", "has": "c_register", "exposed": "l_chen_sample"}
    event = next(event for event in story["events"] if event["id"] == "e_chen_confront")
    del event["when"]["exposed"]

    problems = StudioService._evidence_problems(design, story)
    assert any("c_chen_pickup" in problem and "预订登记单" in problem for problem in problems)
    assert any("c_chen_pickup" in problem and "l_chen_sample" in problem for problem in problems)


def test_every_alternative_unlock_path_must_preserve_required_evidence():
    design, story = repaired_bookstore()
    story["events"].append({"id": "early_pickup", "when": {"shown": "c_blank", "to": "chen"},
                            "confront": ["chen", "su"], "unlock": ["c_chen_pickup"]})
    problems = StudioService._evidence_problems(design, story)
    assert any("c_chen_pickup" in problem and "预订登记单" in problem for problem in problems)


def test_named_evidence_omission_is_checked_without_any_direct_condition():
    design = StudioService._mock_design()
    story = checker.Story.model_validate(mock_story()).model_dump()
    design["clues"][3]["acquire"] = "向林青出示监控记录且已取得空信封后交出寄件单"
    story["clues"][3]["requires"] = {"shown": "c1"}

    problems = StudioService._evidence_problems(design, story)
    assert len(problems) == 1 and "c4" in problems[0] and "空信封" in problems[0]
    story["clues"][3]["requires"]["has"] = "c3"
    assert StudioService._evidence_problems(design, story) == []


def test_lie_evidence_can_include_corrobation_obtained_after_admission():
    design = StudioService._mock_design()
    # 医院诊断中，录音已经反驳未上楼，人物 evidence 还列出拆谎后取得的照片和视频。
    # 同样，监控已直接反驳没碰信件，拆谎后取得的回执只提供后续互证。
    design["characters"][0]["evidence"] = "王平持有的监控记录拍下林青寄信，快递回执进一步互证信已送达。"
    story = checker.Story.model_validate(mock_story()).model_dump()
    assert StudioService._evidence_problems(design, story) == []


def test_explicit_trust_and_exposure_requirements_are_preserved():
    design = StudioService._mock_design()
    story = checker.Story.model_validate(mock_story()).model_dump()
    design["clues"][3]["acquire"] = "拆穿林青谎话并且信任达到2后交出寄件单"
    problems = StudioService._evidence_problems(design, story)
    assert any("c4" in problem and "信任 2" in problem for problem in problems)
    assert any("c4" in problem and "l1" in problem for problem in problems)
    story["clues"][3]["requires"] = {"trust": 2, "exposed": "l1"}
    assert StudioService._evidence_problems(design, story) == []


def test_unknown_design_holder_reports_mapping_problem_without_raising():
    design = StudioService._mock_design()
    design["clues"][3].update(holder="缺失人物", acquire="拆穿其谎话后交出寄件单")
    story = checker.Story.model_validate(mock_story()).model_dump()
    problems = StudioService._evidence_problems(design, story)
    assert len(problems) == 1 and "c4" in problems[0] and "持有人" in problems[0]


def test_ambiguous_optional_acquisition_keeps_existing_condition_checks():
    design = StudioService._mock_design()
    design["clues"][3]["acquire"] = "出示监控记录，或信任达到1后交出寄件单"
    story = checker.Story.model_validate(mock_story()).model_dump()
    assert StudioService._evidence_problems(design, story) == []


@pytest.mark.parametrize("change,expected", [
    ("content", "正文"), ("holder", "持有人"), ("question", "结局题"), ("omit", "未唯一对应"),
])
def test_fill_keeps_design_evidence_and_question_correspondence(change, expected):
    design = StudioService._mock_design()
    story = checker.Story.model_validate(mock_story()).model_dump()
    if change == "question":
        story["ending"]["questions"][0]["answer"] = "王平"
    elif change == "omit":
        story["clues"][0].update(title="新造材料", content="新增的内容")
    else:
        story["clues"][0][change] = "更改后的证据" if change == "content" else "lin"
    assert any(expected in problem for problem in StudioService._evidence_problems(design, story))


def test_unique_content_alias_keeps_acquire_prerequisites():
    design = StudioService._mock_design()
    design["clues"][3]["acquire"] = "向林青出示监控记录后交出寄件单"
    story = checker.Story.model_validate(mock_story()).model_dump()
    story["clues"][0]["title"] = "监控记录副本"
    story["clues"][3].update(title="寄件单副本", requires={"shown": "c1"})
    assert StudioService._evidence_problems(design, story) == []
    story["clues"][3]["requires"] = {}
    assert any("c4" in problem and "shown" in problem
               for problem in StudioService._evidence_problems(design, story))


@pytest.mark.parametrize("text", ["三个人、八条线索、两句谎话、三道结局题、两个结局", BOOKSTORE_INPUT])
def test_explicit_scale_counts_include_chinese_numerals(text):
    design, story = repaired_bookstore()
    assert StudioService._requested_size_problems([text], design=design) == []
    assert StudioService._requested_size_problems([text], story=story) == []
    story["ending"]["endings"].insert(1, deepcopy(story["ending"]["endings"][0]))
    assert any("2 个结局" in problem for problem in StudioService._requested_size_problems([text], story=story))


@pytest.mark.parametrize("text", ["医院题材", "至少3个人，最多8条线索", "3到4人、8–12条线索", "13人、18条线索"])
def test_unspecified_range_and_unsupported_scale_do_not_force_exact_counts(text):
    assert StudioService._requested_size_problems([text], story=mock_story()) == []
