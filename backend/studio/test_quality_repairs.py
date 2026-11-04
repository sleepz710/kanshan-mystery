"""开局检查驱动修表、局部修复和实际稿审阅的回归。"""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock

import pytest

from backend import llm
from backend.studio import check as checker
from backend.studio.mock import mock_story
from backend.studio.service import Job, StudioService


@pytest.fixture
def runtime(monkeypatch):
    with TemporaryDirectory(prefix="kanshan-quality-repairs-") as folder:
        monkeypatch.setenv("LLM_MOCK", "1")
        monkeypatch.setattr(llm, "_ENV_FILE", Path(folder) / "missing.env")
        monkeypatch.setattr(checker, "check_playability", lambda story: [])
        monkeypatch.setattr(checker, "check_opening", AsyncMock(return_value={"ok": True, "problems": []}))
        def no_sdk(*args, **kwargs):
            pytest.fail("修表回归不得构造真实模型客户端")
        monkeypatch.setattr(llm, "AsyncOpenAI", no_sdk)
        monkeypatch.setattr(checker, "AsyncOpenAI", no_sdk)
        yield StudioService(Path(folder) / "stories")


async def run(studio, monkeypatch, transform):
    calls = []
    async def complete(messages, **kwargs):
        data = json.loads(messages[-1]["content"])
        response = deepcopy(kwargs["mock_response"])
        kind = next(iter(response))
        calls.append((kind, kwargs["role"], data))
        return transform(kind, data, response)
    monkeypatch.setattr(checker, "complete_for", complete)
    job = Job("quality-repair", "chat", "play")
    await studio._generate(job, ["纯技术回归素材"], "new")
    return job, calls


def opening_leaks_once(monkeypatch):
    opening = AsyncMock(side_effect=[
        {"ok": False, "problems": ["开局公开材料已答对 q1，请为相关事实补齐秘密锁。"]},
        {"ok": True, "problems": []},
    ])
    monkeypatch.setattr(checker, "check_opening", opening)
    return opening


@pytest.mark.asyncio
async def test_opening_leak_triggers_fields_repair_without_new_design(runtime, monkeypatch):
    opening = opening_leaks_once(monkeypatch)
    def transform(kind, data, response):
        if kind == "story" and data.get("previous_story"):
            characters = deepcopy(data["previous_story"]["characters"])
            characters[2]["secrets"] = [{"fact": "f3", "until": {"trust": 1}}]
            return {"fields": {"characters": characters}}
        return response
    job, calls = await run(runtime, monkeypatch, transform)
    assert job.status == "done" and job.draft["checked"] is True
    assert opening.await_count == 2 and sum(kind == "design" for kind, _, _ in calls) == 1
    assert not opening.await_args_list[0].args[0]["characters"][2]["secrets"]
    assert opening.await_args_list[1].args[0]["characters"][2]["secrets"]
    repair = next(payload for kind, _, payload in calls if kind == "story" and payload.get("previous_story"))
    assert "design" not in repair and any("q1" in p for p in repair["problems"])
    assert job.draft["characters"][2]["secrets"]
    review = next(payload for kind, _, payload in calls if kind == "problems")
    assert review["story"]["characters"][2]["secrets"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_fields", [{"id": "hijacked"}, {"source": "official"}, {"checked": True}, {"unknown": []}, {}])
async def test_invalid_fields_do_not_change_server_metadata(runtime, monkeypatch, bad_fields):
    opening = opening_leaks_once(monkeypatch)
    repairs = 0
    def transform(kind, data, response):
        nonlocal repairs
        if kind == "story" and data.get("previous_story"):
            repairs += 1
            if repairs == 1:
                return {"fields": bad_fields}
            return {"fields": {"intro": data["previous_story"]["intro"]}}
        return response
    job, calls = await run(runtime, monkeypatch, transform)
    assert job.status == "done" and job.draft["source"] == "generated"
    assert job.draft["checked"] is True and opening.await_count == 2
    assert job.story_id.startswith("generated-") and job.story_id != "hijacked"
    repairs = [payload for kind, _, payload in calls if kind == "story" and payload.get("previous_story")]
    assert any("fields" in p for p in repairs[1]["problems"])


@pytest.mark.asyncio
async def test_invalid_partial_array_preserves_complete_valid_table_for_retry(runtime, monkeypatch):
    opening = opening_leaks_once(monkeypatch)
    repairs = 0
    def transform(kind, data, response):
        nonlocal repairs
        if kind == "story" and data.get("previous_story"):
            repairs += 1
            if repairs == 1:
                return {"fields": {"characters": [deepcopy(data["previous_story"]["characters"][0])]}}
            assert len(data["previous_story"]["characters"]) == 3
            assert len(data["rejected_fields"]["characters"]) == 1
            return {"fields": {"characters": deepcopy(data["previous_story"]["characters"])}}
        return response
    job, _ = await run(runtime, monkeypatch, transform)
    assert job.status == "done" and len(job.draft["characters"]) == 3
    assert job.draft["checked"] is True and opening.await_count == 2


@pytest.mark.asyncio
async def test_repeated_table_errors_reuse_the_verified_design(runtime, monkeypatch):
    def transform(kind, data, response):
        if kind == "story":
            response["story"]["characters"][0]["knows"] = ["missing_fact"]
        return response
    job, calls = await run(runtime, monkeypatch, transform)
    assert job.status == "failed" and job.story_id is None
    assert sum(kind == "design" for kind, _, _ in calls) == 1
    assert sum(kind == "story" for kind, _, _ in calls) == 9
    assert not list(runtime.stories_dir.glob("*.yaml"))


@pytest.mark.asyncio
async def test_complete_design_with_wrong_timeline_type_is_formatted_by_actor(runtime, monkeypatch):
    seen_design = False
    def transform(kind, data, response):
        nonlocal seen_design
        if kind == "design":
            if not seen_design:
                seen_design = True
                response["design"]["timeline"][0] = {"time": "14:00", "event": "技术时间线"}
            else:
                assert data["problems"] and "timeline" in data["problems"][0]
                return {"design": StudioService._mock_design()}
        return response
    job, calls = await run(runtime, monkeypatch, transform)
    assert job.status == "done"
    assert [(kind, role) for kind, role, _ in calls if kind == "design"] == [("design", "writer"), ("design", "actor")]


@pytest.mark.asyncio
async def test_ending_fields_merge_keeps_truth_questions_and_other_ending_data(runtime, monkeypatch):
    original = checker.Story.model_validate(mock_story()).model_dump()

    def check_final_ending(story):
        return ["完整真相结局需正常结束，请修正 endings 的 retry。"] if story["ending"]["endings"][0]["retry"] else []

    monkeypatch.setattr(checker, "check_playability", check_final_ending)

    def transform(kind, data, response):
        if kind == "story":
            if data.get("previous_story"):
                endings = deepcopy(data["previous_story"]["ending"]["endings"])
                endings[0]["retry"] = False
                return {"fields": {"ending": {"endings": endings}}}
            response["story"]["ending"]["endings"][0]["retry"] = True
        return response

    job, calls = await run(runtime, monkeypatch, transform)
    assert job.status == "done" and job.draft["checked"] is True
    assert job.draft["ending"] == original["ending"]
    assert job.draft["ending"]["truth"] == original["ending"]["truth"]
    assert job.draft["ending"]["questions"] == original["ending"]["questions"]
    assert sum(kind == "design" for kind, _, _ in calls) == 1
    assert sum(kind == "story" for kind, _, _ in calls) == 2
    reviewed = next(data["story"] for kind, _, data in calls if kind == "problems")
    assert reviewed["ending"] == original["ending"]


@pytest.mark.asyncio
async def test_first_fill_with_fields_requires_a_complete_story_before_retry(runtime, monkeypatch):
    fills = 0

    def transform(kind, data, response):
        nonlocal fills
        if kind == "story":
            fills += 1
            if fills == 1:
                return {"fields": {"title": "只有局部字段"}}
            assert data["previous_story"] is None
            assert data["design"] == StudioService._mock_design()
            assert any("首次填表" in problem and "完整的 story 对象" in problem for problem in data["problems"])
        return response

    job, calls = await run(runtime, monkeypatch, transform)
    assert job.status == "done" and job.draft["checked"] is True
    assert job.draft["title"] == mock_story()["title"]
    assert fills == 2 and sum(kind == "design" for kind, _, _ in calls) == 1


@pytest.mark.asyncio
async def test_complete_bare_design_enters_filling_without_another_design_call(runtime, monkeypatch):
    def transform(kind, data, response):
        return response["design"] if kind == "design" else response

    job, calls = await run(runtime, monkeypatch, transform)
    assert job.status == "done" and job.draft["checked"] is True
    assert [(kind, role) for kind, role, _ in calls if kind == "design"] == [("design", "writer")]
    assert sum(kind == "story" for kind, _, _ in calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("has_previous", [False, True])
async def test_incomplete_bare_design_fails_validation_and_does_not_become_the_old_design(runtime, monkeypatch, has_previous):
    designs = 0

    def transform(kind, data, response):
        nonlocal designs
        if kind == "design":
            designs += 1
            bare = response["design"]
            if not (has_previous and designs == 1):
                bare.pop("intro")
            return bare
        if kind == "problems":
            return {"problems": ["旧稿的具体时间线问题仍需修订。"]}
        return response

    job, calls = await run(runtime, monkeypatch, transform)
    assert [(kind, role) for kind, role, _ in calls if kind == "design"] == [("design", "writer")] * 3
    assert sum(kind == "story" for kind, _, _ in calls) == (1 if has_previous else 0)
    if has_previous:
        assert job.status == "done" and job.draft["checked"] is False
        assert job.problems == ["旧稿的具体时间线问题仍需修订。"]
    else:
        assert job.status == "failed" and job.story_id is None
        assert not list(runtime.stories_dir.glob("*.yaml"))
