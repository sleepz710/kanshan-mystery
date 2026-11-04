"""针对多轮修订、无素材确认和发布期间取消的离线复现。"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from unittest.mock import AsyncMock

import pytest

from backend import llm
from backend.engine import GameEngine
from backend.studio import check as checker
from backend.studio.ingest import InputError
from backend.studio.mock import mock_story
from backend.studio.service import Job, StudioService
from backend.studio.share import owned_story


@pytest.fixture
def runtime_root():
    with TemporaryDirectory(prefix="kanshan-regression-20261103-") as directory:
        yield Path(directory)


@pytest.fixture(autouse=True)
def offline_models(monkeypatch, runtime_root):
    monkeypatch.setattr(checker, "check_playability", lambda story: [])
    monkeypatch.setattr(checker, "check_opening", AsyncMock(return_value={"ok": True, "problems": []}))
    monkeypatch.setattr(llm, "_ENV_FILE", runtime_root / "missing.env")
    monkeypatch.setenv("LLM_MOCK", "1")
    for name in (
        "LLM_API_KEY", "LLM_WRITER_API_KEY", "OPENAI_API_KEY", "LLM_MODEL",
        "LLM_BASE_URL", "LLM_WRITER_BASE_URL", "LLM_ACTOR_MODEL", "LLM_WRITER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    def no_sdk(*args, **kwargs):
        pytest.fail("场景回归必须使用内存模拟回复，不得构造模型客户端。")

    monkeypatch.setattr(llm, "AsyncOpenAI", no_sdk)
    monkeypatch.setattr(checker, "AsyncOpenAI", no_sdk)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_round", ["format_error", "missing_design"])
async def test_unreadable_revision_keeps_the_existing_story_repair_feedback(
    runtime_root, monkeypatch, bad_round
):
    studio = StudioService(runtime_root / "stories")
    job = Job("repair-feedback", "chat", "play")
    generation_inputs = []
    round_no = 0

    async def model(messages, **kwargs):
        nonlocal round_no
        response = deepcopy(kwargs["mock_response"])
        if "design" in response:
            round_no += 1
            generation_inputs.append(deepcopy(json.loads(messages[-1]["content"])))
            if round_no == 2:
                if bad_round == "format_error":
                    raise checker.ReplyFormatError("模拟 JSON 无法读取。", "模拟空白回复")
                return {"unexpected": "没有生成新的 design"}
            response["design"]["intro"] = f"TECHNICAL_ROUND_{round_no}"
        elif "answers" in response and kwargs["role"] == "actor" and round_no == 1:
            # 第一次稿件已有具体的 q3 证据问题，后续输出失败并未替换这份稿。
            response["answers"]["q3"] = None
        return response

    monkeypatch.setattr(checker, "complete_for", model)
    await studio._generate(job, ["纯技术回归素材"], "new")

    assert len(generation_inputs) == 3
    before_failure, after_failure = generation_inputs[1:]
    assert before_failure["previous_design"]["intro"] == "TECHNICAL_ROUND_1"
    assert after_failure["previous_design"] == before_failure["previous_design"]
    assert any("q3" in problem for problem in before_failure["problems"])
    assert any("q3" in problem for problem in after_failure["problems"]), (
        "修订回复未产生新稿时，旧稿的具体证据问题仍应交给下一轮，不能只剩格式错误。"
    )
    assert any("JSON" in problem or "design" in problem for problem in after_failure["problems"])


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["直接开始", "开始生成。", "没看过答案", "看过答案！", "全新"])
async def test_empty_confirmations_do_not_become_story_material(runtime_root, monkeypatch, command):
    studio = StudioService(runtime_root / "stories")
    chat_id = studio.create_chat("play")["chat_id"]
    generated = []

    async def ask_for_material(*args, **kwargs):
        pytest.fail("没有素材的确认按钮只提示补充素材，不应调用模型。")

    async def record_generation(job, materials, strategy):
        generated.append((job.id, list(materials)))

    monkeypatch.setattr(checker, "complete_for", ask_for_material)
    monkeypatch.setattr(studio, "_generate", record_generation)
    try:
        for _ in range(2):
            try:
                response = await studio.message(chat_id, command, {})
            except InputError:
                # 明确要求补充素材或在对话中继续澄清，均不能直接启动生成。
                continue
            assert response["job"] is None
        await asyncio.gather(*list(studio.tasks))
        assert generated == [] and studio.jobs == {}
        assert studio.chats[chat_id].materials == []
    finally:
        await studio.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_file", [False, True])
async def test_substantive_text_or_attachments_still_use_the_normal_flow(
    runtime_root, monkeypatch, with_file
):
    studio = StudioService(runtime_root / "stories")
    chat_id = studio.create_chat("play")["chat_id"]
    requests, generated = [], []
    text = "直接开始" if with_file else "我想玩校园图书馆的推理案件，直接开始。"
    files = {"idea.md": "校园图书馆的书签被调换。".encode("utf-8")} if with_file else {}

    async def choose_generation(messages, **kwargs):
        requests.append(json.loads(messages[-1]["content"]))
        return {"action": "generate", "strategy": "new", "reply": ""}

    async def record_generation(job, materials, strategy):
        generated.append(list(materials))

    monkeypatch.setattr(checker, "complete_for", choose_generation)
    monkeypatch.setattr(studio, "_generate", record_generation)
    try:
        response = await studio.message(chat_id, text, files)
        if response["job"] is None:
            assert "快速" in response["reply"] and "精修" in response["reply"]
            response = await studio.message(chat_id, "快速", {})
        await asyncio.gather(*list(studio.tasks))
        assert response["job"] is not None and len(requests) == len(generated) == 1
        assert any("校园图书馆" in material for material in generated[0])
        assert studio.chats[chat_id].materials == generated[0]
    finally:
        await studio.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["play", "share"])
async def test_shutdown_during_publication_does_not_leave_a_failed_visible_story(
    runtime_root, monkeypatch, mode
):
    studio = StudioService(runtime_root / "stories")
    entered, release, finished = Event(), Event(), Event()
    original_save = studio._save

    async def model(messages, **kwargs):
        return deepcopy(kwargs["mock_response"])

    def delayed_save(story):
        entered.set()
        try:
            if not release.wait(3):
                raise TimeoutError("技术测试未释放保存步骤。")
            original_save(story)
        finally:
            finished.set()

    monkeypatch.setattr(checker, "complete_for", model)
    monkeypatch.setattr(studio, "_save", delayed_save)
    chat_id = studio.create_chat(mode)["chat_id"]
    try:
        response = await studio.message(chat_id, "生成一份纯技术测试案件。", {})
        if response["job"] is None:
            assert "快速" in response["reply"]
            response = await studio.message(chat_id, "快速", {})
        job = studio.jobs[response["job"]["id"]]
        assert await asyncio.to_thread(entered.wait, 2), "应先进入后台发布步骤。"
        closing = asyncio.create_task(studio.close())
        # 让取消请求进入正在等待保存线程的生成任务，再放行实际写盘。
        await asyncio.sleep(0)
        release.set()
        await closing
        assert await asyncio.to_thread(finished.wait, 2)
        engine = GameEngine(runtime_root / "no-official-stories", studio.stories_dir)

        if job.status == "done":
            # 已进入不可中断的原子发布时，可以完成发布并保留一致的结果。
            assert job.story_id
            assert [story["id"] for story in engine.list_stories()] == [job.story_id]
            assert engine.new_game(job.story_id)["title"] == mock_story()["title"]
            if mode == "share":
                assert job.owner_token
                assert owned_story(studio.stories_dir, job.story_id, job.owner_token)["id"] == job.story_id
        else:
            assert job.status == "failed" and job.story_id is None
            assert engine.list_stories() == [], "失败的生成任务不能在取消后继续发布可见案件。"
            assert list((studio.stories_dir / ".owners").glob("*.json")) == []
    finally:
        release.set()
        await studio.close()
        if entered.is_set():
            await asyncio.to_thread(finished.wait, 2)
