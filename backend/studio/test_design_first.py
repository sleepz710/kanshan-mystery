"""设计与填表分离，以及按具体质量问题修订的回归。"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from unittest.mock import AsyncMock

import pytest

from backend import llm
from backend.studio import check as checker, service
from backend.studio.service import Job, StudioService


@pytest.fixture
def runtime(monkeypatch):
    with TemporaryDirectory(prefix="kanshan-design-first-") as folder:
        monkeypatch.setenv("LLM_MOCK", "1")
        monkeypatch.setattr(llm, "_ENV_FILE", Path(folder) / "missing.env")
        monkeypatch.setattr(checker, "check_playability", lambda story: [])
        monkeypatch.setattr(checker, "check_opening", AsyncMock(return_value={"ok": True, "problems": []}))
        yield StudioService(Path(folder) / "stories")


async def generate(studio, monkeypatch, transform=None):
    calls = []
    async def complete(messages, **kwargs):
        response = deepcopy(kwargs["mock_response"])
        kind = next(iter(response))
        data = json.loads(messages[-1]["content"])
        calls.append((kind, kwargs["role"], data))
        if transform is not None:
            response = await transform(kind, data, response)
        return response
    monkeypatch.setattr(checker, "complete_for", complete)
    job = Job("design-regression", "chat", "play")
    await studio._generate(job, ["一封信的技术回归素材"], "new")
    return job, calls


@pytest.mark.asyncio
async def test_design_then_actor_fill_then_actual_story_review_and_blind_checks(runtime, monkeypatch):
    job, calls = await generate(runtime, monkeypatch)
    assert job.status == "done" and job.draft["checked"] is True
    assert [(kind, role) for kind, role, _ in calls] == [
        ("design", "writer"), ("story", "actor"), ("problems", "actor"),
        ("answers", "writer"), ("answers", "actor")]
    assert calls[1][2]["design"] == calls[2][2]["design"]
    reviewed_story = calls[2][2]["story"]
    assert reviewed_story["id"] == job.story_id
    assert reviewed_story["facts"] == job.draft["facts"]
    assert reviewed_story["ending"] == job.draft["ending"]


@pytest.mark.asyncio
async def test_format_repairs_keep_one_design_and_allow_two_retries(runtime, monkeypatch):
    filled = 0
    async def transform(kind, data, response):
        nonlocal filled
        if kind == "story":
            filled += 1
            if filled < 3:
                response["story"]["characters"][0]["knows"] = ["unknown_fact"]
        return response
    job, calls = await generate(runtime, monkeypatch, transform)
    assert job.status == "done" and job.draft["checked"] is True
    designs = [payload for kind, _, payload in calls if kind == "design"]
    fills = [payload for kind, _, payload in calls if kind == "story"]
    assert len(designs) == 1 and len(fills) == 3
    assert fills[0]["design"] == StudioService._mock_design()
    for repair in fills[1:]:
        assert "design" not in repair
        assert repair["previous_story"]["characters"][0]["knows"] == ["unknown_fact"]
        assert repair["reference_ids"]["facts"]
    assert any("unknown_fact" in problem for problem in fills[1]["problems"])


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["review", "playability", "solvability"])
async def test_every_quality_problem_revises_design(runtime, monkeypatch, source):
    if source == "playability":
        monkeypatch.setattr(checker, "check_playability", lambda story: ["层次不足，请增加第3层证据"])
    async def transform(kind, data, response):
        if kind == "problems" and source == "review":
            return {"problems": ["时间线矛盾，请修改设计稿"]}
        if kind == "answers" and source == "solvability" and "clues" in data:
            return {"answers": dict.fromkeys(response["answers"], None)}
        return response
    job, calls = await generate(runtime, monkeypatch, transform)
    designs = [payload for kind, _, payload in calls if kind == "design"]
    assert len(designs) == 3 and designs[1]["problems"]
    assert designs[1]["previous_design"] is not None
    assert job.status == "done" and job.draft["checked"] is False


@pytest.mark.asyncio
async def test_budget_estimates_last_round_before_another_revision(runtime, monkeypatch):
    monkeypatch.setattr(service, "GENERATION_TIMEOUT", 0.40)
    monkeypatch.setattr(service, "SAVE_RESERVE", 0.02)
    async def transform(kind, data, response):
        await asyncio.sleep(0.045)
        return {"problems": ["需要补充动机"]} if kind == "problems" else response
    job, calls = await generate(runtime, monkeypatch, transform)
    assert len([call for call in calls if call[0] == "design"]) == 1
    assert job.status == "done" and job.draft["checked"] is False


@pytest.mark.asyncio
async def test_later_worse_draft_does_not_replace_better_checked_candidate(runtime, monkeypatch):
    round_no = 0
    async def transform(kind, data, response):
        nonlocal round_no
        if kind == "design":
            round_no += 1
        if kind == "story":
            response["story"]["title"] = f"版本{round_no}"
        if kind == "problems":
            return {"problems": [f"问题{i}" for i in range(round_no)]}
        return response
    job, _ = await generate(runtime, monkeypatch, transform)
    assert job.status == "done" and job.draft["title"] == "版本1"
    assert job.problems == ["问题0"]


@pytest.mark.asyncio
async def test_unreadable_design_never_publishes_a_story(runtime, monkeypatch):
    async def transform(kind, data, response):
        if kind == "design":
            return {"design": {"truth": "缺少设计字段"}}
        pytest.fail("无效设计稿不能进入填表")
    job, calls = await generate(runtime, monkeypatch, transform)
    assert job.status == "failed" and job.story_id is None
    assert len(calls) == 3
    assert calls[1][2]["previous_design"] == {"truth": "缺少设计字段"}
    assert any("timeline" in problem for problem in calls[1][2]["problems"])
