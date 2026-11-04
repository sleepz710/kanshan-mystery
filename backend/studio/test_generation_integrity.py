"""生成候选必须可开局，后续坏输出或模型失败不能覆盖可运行版本。"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml

from backend import llm
from backend.engine import GameEngine
from backend.studio import check as checker, service
from backend.studio.mock import mock_story
from backend.studio.service import Job, StudioService


@pytest.fixture
def runtime_root():
    # Windows 工作区的原子重命名可能受限制，业务写盘放在系统临时目录。
    with TemporaryDirectory(prefix="kanshan-generation-integrity-") as directory:
        yield Path(directory)


@pytest.fixture(autouse=True)
def offline_models(monkeypatch, runtime_root):
    monkeypatch.setattr(checker, "check_playability", lambda story: [])
    monkeypatch.setenv("LLM_MOCK", "1")
    monkeypatch.setattr(llm, "_ENV_FILE", runtime_root / "missing.env")
    for name in (
        "LLM_API_KEY", "LLM_WRITER_API_KEY", "OPENAI_API_KEY",
        "LLM_BASE_URL", "LLM_WRITER_BASE_URL", "LLM_MODEL",
        "LLM_ACTOR_MODEL", "LLM_WRITER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    def no_sdk(*args, **kwargs):
        pytest.fail("生成完整性回归必须使用模拟模型客户端。")

    monkeypatch.setattr(llm, "AsyncOpenAI", no_sdk)
    if hasattr(checker, "AsyncOpenAI"):
        monkeypatch.setattr(checker, "AsyncOpenAI", no_sdk)


def payload(messages):
    return json.loads(messages[-1]["content"])


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["先不要开始生成，我还要补充人物关系。", "素材写着「直接开始」，请先讨论人物。"])
async def test_discussion_does_not_start_when_material_contains_start_words(runtime_root, monkeypatch, text):
    studio = StudioService(runtime_root / "stories")
    chat_id = studio.create_chat("share")["chat_id"]

    async def discuss(*args, **kwargs):
        return {"action": "discuss", "strategy": "new", "reply": "可以继续讨论人物关系。"}

    monkeypatch.setattr(checker, "complete_for", discuss)
    try:
        result = await studio.message(chat_id, text, {})
        assert result["job"] is None
        assert not studio.jobs
    finally:
        await studio.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("command, strategy", [("直接开始", "seen"), ("开始生成。", "unseen")])
async def test_confirmed_start_reuses_strategy_without_a_model_call(
    runtime_root, monkeypatch, command, strategy
):
    studio = StudioService(runtime_root / "stories")
    chat_id = studio.create_chat("play")["chat_id"]
    chat = studio.chats[chat_id]
    chat.materials = ["已读取并讨论过的技术测试素材。"]
    chat.strategy, chat.asked = strategy, True
    generated = []

    async def no_model(*args, **kwargs):
        pytest.fail("确认开始时应直接复用策略，不应等待模型再次判意。")

    async def record_generation(job, materials, chosen_strategy):
        generated.append((job.id, list(materials), chosen_strategy))

    monkeypatch.setattr(checker, "complete_for", no_model)
    monkeypatch.setattr(studio, "_generate", record_generation)
    try:
        result = await studio.message(chat_id, command, {})
        await asyncio.gather(*list(studio.tasks))
        assert result["job"] is not None
        assert generated == [(result["job"]["id"], ["已读取并讨论过的技术测试素材。", command], strategy)]
        assert chat.strategy == strategy
        assert chat.history[-1]["role"] == "assistant"
    finally:
        await studio.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("command, strategy", [("没看过答案", "unseen"), ("看过答案", "seen"), ("全新！", "new")])
async def test_strategy_confirmation_starts_without_a_model_call(
    runtime_root, monkeypatch, command, strategy
):
    studio = StudioService(runtime_root / "stories")
    chat_id = studio.create_chat("play")["chat_id"]
    chat = studio.chats[chat_id]
    chat.materials = ["已读取并讨论过的技术测试素材。"]
    chat.strategy, chat.asked = ("new" if strategy != "new" else "seen"), True
    generated = []

    async def no_model(*args, **kwargs):
        pytest.fail("明确选择改编策略时不应再调用编剧模型。")

    async def record_generation(job, materials, chosen_strategy):
        generated.append((job.id, chosen_strategy))

    monkeypatch.setattr(checker, "complete_for", no_model)
    monkeypatch.setattr(studio, "_generate", record_generation)
    try:
        result = await studio.message(chat_id, command, {})
        assert result["job"] is None and "快速" in result["reply"] and "精修" in result["reply"]
        assert generated == [] and chat.strategy == strategy
        result = await studio.message(chat_id, "快速", {})
        await asyncio.gather(*list(studio.tasks))
        assert result["job"] is not None
        assert generated == [(result["job"]["id"], strategy)]
        assert chat.strategy == strategy and chat.quality == "fast"
    finally:
        await studio.close()


def valid_story(title="PLAYABLE_INITIAL"):
    result = mock_story()
    result["title"] = title
    return result


def damaged_story(title, damage="condition"):
    result = valid_story(title)
    if damage == "condition":
        result["clues"][0]["requires"] = {"clue": "c3"}
    else:
        result.pop("intro")
    return result


def assert_published_game_opens(studio, job, runtime_root):
    assert job.status == "done"
    assert job.story_id
    path = studio.stories_dir / f"{job.story_id}.yaml"
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["checked"] is False
    assert checker.check_structure(saved)["ok"]
    engine = GameEngine(runtime_root / "no-official-stories", studio.stories_dir)
    assert [story["id"] for story in engine.list_stories()] == [job.story_id]
    opened = engine.new_game(job.story_id)
    assert opened["title"] == saved["title"]
    return saved


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["play", "share"])
async def test_unknown_condition_is_only_a_private_draft(runtime_root, monkeypatch, mode):
    studio = StudioService(runtime_root / "stories")
    job = Job("unknown-condition", "chat", mode)
    marker = "PRIVATE_DRAFT_UNSUPPORTED_CONDITION"

    async def model(messages, **kwargs):
        if "story" in kwargs["mock_response"]:
            return {"story": damaged_story(marker)}
        return deepcopy(kwargs["mock_response"])

    monkeypatch.setattr(checker, "complete_for", model)
    await studio._generate(job, ["technical fixture"], "new")

    assert job.status == "failed"
    assert job.story_id is None and job.owner_token is None
    assert list(studio.stories_dir.glob("*.yaml")) == []
    assert marker not in json.dumps(job.public(), ensure_ascii=False)
    assert not job.public().get("share_url")
    drafts = [path for path in (runtime_root / "drafts").rglob("*") if path.is_file()]
    assert drafts, "不能开局的候选应保留为私有草稿，方便后续修订。"
    assert any(marker in path.read_text(encoding="utf-8") for path in drafts)
    engine = GameEngine(runtime_root / "no-official-stories", studio.stories_dir)
    assert engine.list_stories() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["deadline", "exhausted"])
@pytest.mark.parametrize("damage", ["condition", "format"])
async def test_bad_later_generation_cannot_replace_playable_initial_draft(
    runtime_root, monkeypatch, stop, damage
):
    studio = StudioService(runtime_root / "stories")
    job = Job("keep-initial", "chat", "play")
    generations = 0
    blocked = asyncio.Event()

    async def model(messages, **kwargs):
        nonlocal generations
        if "design" in kwargs["mock_response"]:
            generations += 1
            if generations > 1 and stop == "deadline":
                blocked.set()
                await asyncio.Event().wait()
            return deepcopy(kwargs["mock_response"])
        if "story" in kwargs["mock_response"]:
            return {"story": valid_story() if generations == 1 else damaged_story("INVALID_LATER_DRAFT", damage)}
        if "problems" in kwargs["mock_response"]:
            return {"problems": []}
        if "answers" in kwargs["mock_response"] and kwargs["role"] == "actor":
            # 首轮盲答缺少证据，触发后续修订；后续坏稿不能覆盖首轮可运行稿。
            return {"answers": {q["id"]: None for q in mock_story()["ending"]["questions"]}}
        return deepcopy(kwargs["mock_response"])

    monkeypatch.setattr(checker, "complete_for", model)
    if stop == "deadline":
        monkeypatch.setattr(service, "GENERATION_TIMEOUT", service.SAVE_RESERVE + 0.1)
    await studio._generate(job, ["technical fixture"], "new")

    if stop == "deadline":
        assert blocked.is_set()
    else:
        assert generations == 3
    saved = assert_published_game_opens(studio, job, runtime_root)
    assert saved["title"] == "PLAYABLE_INITIAL"


@pytest.mark.asyncio
async def test_local_condition_error_is_passed_to_the_repair_model(runtime_root, monkeypatch):
    studio = StudioService(runtime_root / "stories")
    job = Job("specific-repair", "chat", "play")
    calls = []
    generations = 0

    async def model(messages, **kwargs):
        nonlocal generations
        incoming = payload(messages)
        calls.append(deepcopy(incoming))
        if "story" in kwargs["mock_response"]:
            generations += 1
            story = damaged_story("INVALID_FIRST_DRAFT") if generations == 1 else valid_story("REPAIRED_GENERATION")
            return {"story": story}
        return deepcopy(kwargs["mock_response"])

    monkeypatch.setattr(checker, "complete_for", model)
    await studio._generate(job, ["technical fixture"], "new")

    assert job.status == "done" and generations == 2
    problems = [problem for item in calls for problem in item.get("problems", [])]
    assert any(
        "clue" in problem and any(location in problem for location in ("c1", "clues.0", "clues[0]"))
        for problem in problems
    ), "修订输入应指出实际坏掉的线索或字段，不能只重复通用条件规则。"
    engine = GameEngine(runtime_root / "no-official-stories", studio.stories_dir)
    assert engine.new_game(job.story_id)["title"] == "REPAIRED_GENERATION"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_step", ["review", "intro_answers", "clue_answers", "later_generation"])
async def test_later_model_error_preserves_a_playable_candidate(
    runtime_root, monkeypatch, failure_step
):
    studio = StudioService(runtime_root / "stories")
    job = Job("later-model-error", "chat", "play")
    generations = 0
    failed = False

    async def model(messages, **kwargs):
        nonlocal generations, failed
        incoming = payload(messages)
        if "design" in kwargs["mock_response"]:
            generations += 1
            if generations > 1 and failure_step == "later_generation":
                failed = True
                raise llm.LLMError("模拟后续模型调用失败，请重试。")
            return deepcopy(kwargs["mock_response"])
        if "story" in kwargs["mock_response"]:
            step = "generation"
        elif "problems" in kwargs["mock_response"]:
            step = "review"
        else:
            step = "intro_answers" if kwargs["role"] == "writer" else "clue_answers"
        if step == failure_step:
            failed = True
            raise llm.LLMError("模拟后续模型调用失败，请重试。")
        if step == "generation":
            return {"story": valid_story()}
        if step == "review":
            return {"problems": []}
        if failure_step == "later_generation" and step == "clue_answers":
            return {"answers": {q["id"]: None for q in mock_story()["ending"]["questions"]}}
        return deepcopy(kwargs["mock_response"])

    monkeypatch.setattr(checker, "complete_for", model)
    await studio._generate(job, ["technical fixture"], "new")

    assert failed
    saved = assert_published_game_opens(studio, job, runtime_root)
    assert saved["title"] == "PLAYABLE_INITIAL"
