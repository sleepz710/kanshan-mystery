"""任务 14：重跑条件、候选保存、调用日志与编剧格式恢复。"""

import asyncio
from copy import deepcopy
import json
import logging
from unittest.mock import AsyncMock

import pytest
import yaml

from backend.llm import LLMError
from backend.studio import check as checker, service
from backend.studio.mock import mock_story
from backend.studio.service import Job, StudioService
from backend.studio.share import owned_story


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")


def saved(studio, job):
    return yaml.safe_load((studio.stories_dir / f"{job.story_id}.yaml").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_review_advice_does_not_repeat_hard_checks(tmp_path, monkeypatch, caplog):
    studio, job = StudioService(tmp_path), Job("review-advice", "chat", "play")
    calls = []

    async def model(messages, **kwargs):
        calls.append(kwargs["role"])
        result = deepcopy(kwargs["mock_response"])
        if "problems" in result:
            result["problems"] = ["SECRET_REVIEW_ADVICE"]
        return result

    monkeypatch.setattr(checker, "complete_for", model)
    with caplog.at_level(logging.INFO):
        await studio._generate(job, ["SECRET_MATERIAL"], "new")
    assert calls == ["writer", "writer", "writer", "actor"]
    assert job.status == "done" and not saved(studio, job)["checked"]
    assert job.problems == ["SECRET_REVIEW_ADVICE"]
    assert "SECRET_REVIEW_ADVICE" not in json.dumps(job.public())
    logs = [r.message for r in caplog.records if "耗时" in r.message]
    assert len(logs) == 4
    for step, message in zip(("生成", "审稿", "可解性·只给汤面", "可解性·全部线索"), logs):
        assert job.id in message and "第 1 轮" in message and step in message and "秒" in message
    assert "SECRET_MATERIAL" not in caplog.text and "SECRET_REVIEW_ADVICE" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["format", "structure", "count", "intro_answers", "clue_answers"])
async def test_hard_failures_start_another_round(tmp_path, monkeypatch, failure):
    studio, job = StudioService(tmp_path), Job("hard-check", "chat", "play")
    rounds = 0

    async def model(messages, **kwargs):
        nonlocal rounds
        result = deepcopy(kwargs["mock_response"])
        if "materials" in json.loads(messages[-1]["content"]):
            rounds += 1
            if rounds == 1:
                if failure == "format":
                    result["story"].pop("intro")
                elif failure == "structure":
                    result["story"]["clues"][0]["holder"] = "missing-character"
                elif failure == "count":
                    for index in range(2):
                        extra = deepcopy(result["story"]["characters"][0])
                        extra.update(id=f"extra-{index}", lies=[])
                        result["story"]["characters"].append(extra)
        if rounds == 1 and "answers" in result:
            if failure == "intro_answers" and kwargs["role"] == "writer":
                result["answers"] = {q["id"]: q["answer"] for q in mock_story()["ending"]["questions"]}
            if failure == "clue_answers" and kwargs["role"] == "actor":
                result["answers"] = {}
        return result

    monkeypatch.setattr(checker, "complete_for", model)
    await studio._generate(job, [], "new")
    assert rounds == 2 and job.status == "done"
    assert saved(studio, job)["checked"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["play", "share"])
@pytest.mark.parametrize("blocked_step", ["生成", "审稿", "可解性·只给汤面", "可解性·全部线索", "下一轮"])
async def test_deadline_saves_latest_valid_draft(tmp_path, monkeypatch, mode, blocked_step, caplog):
    studio, job = StudioService(tmp_path), Job("deadline", "chat", mode)
    original = studio._model_call
    generation_calls = 0

    async def model(job, attempt, step, messages, **kwargs):
        nonlocal generation_calls
        if step == "生成":
            generation_calls += 1
        if step == blocked_step or (blocked_step == "下一轮" and generation_calls == 2):
            await asyncio.Event().wait()
        result = await original(job, attempt, step, messages, **kwargs)
        if "story" in result:
            result["story"]["title"] = "审稿候选" if step == "审稿" else "初稿候选"
        return result

    monkeypatch.setattr(studio, "_model_call", model)
    monkeypatch.setattr(service, "GENERATION_TIMEOUT", service.SAVE_RESERVE + 0.05)
    if blocked_step == "下一轮":
        monkeypatch.setattr(checker, "check", AsyncMock(return_value={"ok": False, "problems": ["缺少证据"]}))
    with caplog.at_level(logging.INFO):
        await studio._generate(job, [], "new")
    if blocked_step == "生成":
        assert job.status == "failed" and job.error == "生成超时，请重试。"
        assert list(tmp_path.glob("*.yaml")) == []
        assert job.id in caplog.text and "失败" in caplog.text
    else:
        assert job.status == "done" and job.error and "检查未全部通过" in job.progress
        story = saved(studio, job)
        assert story["checked"] is False
        assert story["title"] == ("初稿候选" if blocked_step == "审稿" else "审稿候选")
        assert any("超时" in p for p in job.problems)
        assert "draft" not in job.public() and "problems" not in job.public()
        if mode == "share":
            assert owned_story(tmp_path, job.story_id, job.owner_token) == story
        else:
            assert job.owner_token is None


@pytest.mark.asyncio
async def test_bad_later_rounds_do_not_overwrite_valid_draft(tmp_path, monkeypatch):
    studio, job = StudioService(tmp_path), Job("keep-draft", "chat", "play")
    rounds = 0

    async def model(messages, **kwargs):
        nonlocal rounds
        if "materials" in json.loads(messages[-1]["content"]):
            rounds += 1
            if rounds > 1:
                return {"story": {"title": "损坏的后续版本"}}
        return deepcopy(kwargs["mock_response"])

    monkeypatch.setattr(checker, "complete_for", model)
    monkeypatch.setattr(checker, "check", AsyncMock(return_value={"ok": False, "problems": ["缺少证据"]}))
    await studio._generate(job, [], "new")
    assert rounds == 3 and job.status == "done"
    assert saved(studio, job)["title"] == mock_story()["title"]
    assert not saved(studio, job)["checked"] and job.problems == ["缺少证据"]


@pytest.mark.asyncio
async def test_no_valid_draft_after_three_rounds_fails_without_publishing(tmp_path, monkeypatch):
    studio, job = StudioService(tmp_path), Job("no-draft", "chat", "play")
    model = AsyncMock(return_value={"story": {"title": "格式损坏"}, "problems": []})
    monkeypatch.setattr(checker, "complete_for", model)
    await studio._generate(job, [], "new")
    assert model.await_count == 6 and job.status == "failed"
    assert "格式" in job.error and list(tmp_path.glob("*.yaml")) == []


@pytest.mark.asyncio
async def test_shutdown_after_valid_draft_cancels_without_publishing(tmp_path, monkeypatch):
    studio, job = StudioService(tmp_path), Job("shutdown", "chat", "share")
    original = checker.complete_for
    reviewing = asyncio.Event()

    async def model(messages, **kwargs):
        if "problems" in kwargs["mock_response"]:
            reviewing.set()
            await asyncio.Event().wait()
        return await original(messages, **kwargs)

    monkeypatch.setattr(checker, "complete_for", model)
    task = asyncio.create_task(studio._generate(job, [], "new"))
    await reviewing.wait()
    assert job.draft is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert job.status == "failed" and "关闭" in job.error
    assert job.owner_token is None and list(tmp_path.glob("*.yaml")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [{"action": "unknown", "strategy": "new"}, {"action": "discuss"}, {"action": "discuss", "strategy": "new", "arguments": []}])
async def test_decision_validation_retries_once_without_bad_response(tmp_path, monkeypatch, invalid):
    studio = StudioService(tmp_path)
    chat = studio.create_chat("share")["chat_id"]
    model = AsyncMock(side_effect=[invalid, {"action": "discuss", "strategy": "new", "reply": "可以继续讨论。"}])
    monkeypatch.setattr(checker, "complete_for", model)
    response = await studio.message(chat, "想聊一个新案件", {})
    assert model.await_count == 2 and response["job"] is None
    assert len(studio.chats[chat].history) == 2
    retry_messages = model.call_args_list[1].args[0]
    assert "操作格式不合法" in retry_messages[-1]["content"]
    assert all(m["role"] != "assistant" for m in retry_messages)


@pytest.mark.asyncio
async def test_twice_invalid_decision_leaves_chat_unchanged(tmp_path, monkeypatch):
    studio = StudioService(tmp_path)
    chat = studio.create_chat("share")["chat_id"]
    model = AsyncMock(return_value={"action": "unknown", "strategy": "new"})
    monkeypatch.setattr(checker, "complete_for", model)
    with pytest.raises(LLMError, match="有效的操作"):
        await studio.message(chat, "一个想法", {"idea.txt": b"idea"})
    assert model.await_count == 2
    assert studio.chats[chat].history == studio.chats[chat].materials == []
    assert studio.chats[chat].files == {} and studio.jobs == {}


@pytest.mark.asyncio
async def test_model_and_save_failures_are_logged(tmp_path, monkeypatch, caplog):
    studio, job = StudioService(tmp_path), Job("outage", "chat", "play")
    original = checker.complete_for
    monkeypatch.setattr(checker, "complete_for", AsyncMock(side_effect=LLMError("模型离线")))
    with caplog.at_level(logging.INFO):
        await studio._generate(job, [], "new")
    assert job.status == "failed"
    assert "outage" in caplog.text and "模型离线" in caplog.text and "生成 失败 耗时" in caplog.text
    monkeypatch.setattr(checker, "complete_for", original)

    def no_disk(story):
        raise OSError("磁盘不可写")

    monkeypatch.setattr(studio, "_save", no_disk)
    job = Job("save-failure", "chat", "play")
    await studio._generate(job, [], "new")
    assert job.status == "failed" and not list(tmp_path.glob("*.yaml"))
    assert "save-failure" in caplog.text and "磁盘不可写" in caplog.text
