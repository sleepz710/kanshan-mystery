"""档位确认、双候选选择及并发取消回归。"""
import asyncio
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from backend import llm
from backend.studio import check as checker, service
from backend.studio.mock import mock_story
from backend.studio.service import Candidate, Job, QUALITY_PROMPT, StudioService


@pytest.fixture
def studio(monkeypatch):
    with TemporaryDirectory(prefix="kanshan-quality-") as directory:
        monkeypatch.setenv("LLM_MOCK", "1")
        monkeypatch.setattr(llm, "_ENV_FILE", Path(directory) / "missing.env")
        yield StudioService(Path(directory) / "stories")


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["没看过答案", "看过答案", "全新"])
async def test_strategy_selection_asks_quality_without_model_or_generation(studio, monkeypatch, strategy):
    chat_id = studio.create_chat("play")["chat_id"]
    studio.chats[chat_id].materials = ["已读取的案件题材"]
    async def no_model(*args, **kwargs):
        pytest.fail("档位确认必须是本地固定文案")
    monkeypatch.setattr(checker, "complete_for", no_model)
    result = await studio.message(chat_id, strategy, {})
    assert result == {"reply": QUALITY_PROMPT, "job": None}
    assert studio.chats[chat_id].asked and not studio.jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("command,quality", [("快速", "fast"), ("精修", "fine"), ("直接开始", "fast")])
async def test_quality_confirmation_starts_locally_and_is_public(studio, monkeypatch, command, quality):
    chat_id = studio.create_chat("play")["chat_id"]
    studio.chats[chat_id].materials = ["已读取的案件题材"]
    studio.chats[chat_id].asked = True
    seen = []
    async def generate(job, material, strategy):
        seen.append(job.quality)
    async def no_model(*args, **kwargs):
        pytest.fail("确认档位不应调用模型判意")
    monkeypatch.setattr(studio, "_generate", generate)
    monkeypatch.setattr(checker, "complete_for", no_model)
    result = await studio.message(chat_id, command, {})
    await asyncio.gather(*list(studio.tasks))
    job = studio.jobs[result["job"]["id"]]
    assert result["job"]["quality"] == job.public()["quality"] == quality
    assert seen == [quality]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["快速", "精修"])
async def test_empty_quality_selection_requires_material(studio, command):
    chat_id = studio.create_chat("play")["chat_id"]
    result = await studio.message(chat_id, command, {})
    assert result["job"] is None and not studio.jobs
    assert not studio.chats[chat_id].materials


@pytest.mark.asyncio
async def test_fine_compares_two_concurrent_candidates_before_one_solvability_check(studio, monkeypatch):
    ready = asyncio.Event()
    branches = []
    checked = []
    async def make(job, attempt, material, strategy, previous, problems, story_id):
        branches.append(job.id)
        if len(branches) == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=1)
        story = checker.Story.model_validate(mock_story()).model_dump()
        story.update(id=story_id, title=job.id)
        return Candidate(design=StudioService._mock_design(), story=story,
            playability=["线索太集中"] if job.id.endswith("-1") else [],
            review=[] if job.id.endswith("-1") else ["需要补充动机"])
    async def check(story, **kwargs):
        checked.append(story["title"])
        return {"ok": True, "problems": []}
    monkeypatch.setattr(studio, "_make_candidate", make)
    monkeypatch.setattr(checker, "check", check)
    job = Job("fine-choice", "chat", "play", quality="fine")
    # 第二轮不应继续消耗请求，模拟剩余预算估算只能容纳第一轮。
    monkeypatch.setattr(studio, "_budget", lambda job: 10.00001)
    await studio._pipeline(job, ["素材"], "new")
    assert len(branches) == 2
    assert checked == ["fine-choice-2"]
    assert job.draft["title"] == "fine-choice-2"


@pytest.mark.asyncio
async def test_fine_one_unavailable_branch_keeps_other_candidate(studio, monkeypatch):
    async def make(job, attempt, material, strategy, previous, problems, story_id):
        if job.id.endswith("-1"):
            raise llm.LLMError("临时服务错误")
        story = checker.Story.model_validate(mock_story()).model_dump()
        story.update(id=story_id, title="可用方案")
        return Candidate(design=StudioService._mock_design(), story=story)
    async def check(*args, **kwargs):
        return {"ok": True, "problems": []}
    monkeypatch.setattr(studio, "_make_candidate", make)
    monkeypatch.setattr(checker, "check", check)
    job = Job("fine-recovery", "chat", "play", quality="fine")
    await studio._generate(job, ["素材"], "new")
    assert job.status == "done" and job.draft["checked"] is True


@pytest.mark.asyncio
async def test_cancelling_fine_generation_cancels_both_unpublished_branches(studio, monkeypatch):
    ready = asyncio.Event()
    running, stopped = [], []
    async def make(job, *args):
        running.append(job.id)
        if len(running) == 2:
            ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.append(job.id)
    monkeypatch.setattr(studio, "_make_candidate", make)
    job = Job("fine-cancel", "chat", "play", quality="fine")
    task = asyncio.create_task(studio._generate(job, ["素材"], "new"))
    await asyncio.wait_for(ready.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(stopped) == 2 and job.status == "failed"
    assert not list(studio.stories_dir.glob("*.yaml"))


def test_quality_budgets(studio):
    assert studio._budget(Job("fast", "chat", "play")) == 600
    assert studio._budget(Job("fine", "chat", "play", quality="fine")) == 900


@pytest.mark.parametrize("mock,base,writer_base,model,multiplier", [
    ("0", "https://api.openai.com/v1", "", "gpt-5.4", 2),
    ("0", "https://api.deepseek.com", "https://api.openai.com/v1", "gpt-5.4-2026-03-05", 2),
    ("1", "https://api.openai.com/v1", "", "gpt-5.4", 1),
    ("0", "https://api.deepseek.com", "", "deepseek-flash", 1),
    ("0", "https://model.example.test/v1", "", "gpt-5.4", 1),
    ("0", "https://api.openai.com/v1", "https://writer.example.test/v1", "gpt-5.4", 1),
    ("0", "https://api.openai.com/v1", "", "gpt-5.4-mini", 1),
    ("0", "https://api.openai.com/v1", "", "gpt-4o", 1),
])
def test_budget_profiles_follow_only_the_verified_real_writer(studio, monkeypatch, mock, base, writer_base, model, multiplier):
    monkeypatch.setenv("LLM_MOCK", mock)
    monkeypatch.setenv("LLM_BASE_URL", base)
    monkeypatch.setenv("LLM_WRITER_BASE_URL", writer_base)
    monkeypatch.setenv("LLM_WRITER_MODEL", model)
    assert studio._budget(Job("fast", "chat", "play")) == 600 * multiplier
    assert studio._budget(Job("fine", "chat", "play", quality="fine")) == 900 * multiplier


def test_openai_budget_profile_keeps_small_monkeypatched_budgets(studio, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_WRITER_BASE_URL", "")
    monkeypatch.setenv("LLM_WRITER_MODEL", "gpt-5.4")
    monkeypatch.setattr(service, "GENERATION_TIMEOUT", 0.04)
    monkeypatch.setattr(service, "FINE_TIMEOUT", 0.06)
    assert studio._budget(Job("fast", "chat", "play")) == 0.08
    assert studio._budget(Job("fine", "chat", "play", quality="fine")) == 0.12


@pytest.mark.asyncio
async def test_openai_profile_enforces_a_monkeypatched_total_deadline(studio, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_WRITER_BASE_URL", "")
    monkeypatch.setenv("LLM_WRITER_MODEL", "gpt-5.4")
    monkeypatch.setattr(service, "GENERATION_TIMEOUT", 0.04)
    monkeypatch.setattr(service, "SAVE_RESERVE", 0.005)

    async def wait_forever(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(studio, "_pipeline", wait_forever)
    job = Job("profile-deadline", "chat", "play")
    await asyncio.wait_for(studio._generate(job, ["技术素材"], "new"), 0.5)
    assert job.status == "failed" and job.error == "生成超时，请重试。"


def test_quality_prompt_describes_process_without_unmeasured_minutes():
    assert QUALITY_PROMPT == "快速还是精修？精修会比较两份设计，并增加修订轮次。实际耗时取决于素材和模型。"
