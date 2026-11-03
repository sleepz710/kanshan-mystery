"""生成请求、只读审稿和耗时日志的离线边界回归。"""

import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml

from backend import llm
from backend.engine import GameEngine
from backend.studio import check as checker
from backend.studio.mock import mock_story
from backend.studio.service import Job, StudioService


@pytest.fixture
def runtime_root():
    with TemporaryDirectory(prefix="kanshan-writer-speed-") as directory:
        yield Path(directory)


@pytest.fixture(autouse=True)
def offline_models(monkeypatch, runtime_root):
    monkeypatch.setattr(llm, "_ENV_FILE", runtime_root / "missing.env")
    monkeypatch.setenv("LLM_MOCK", "1")
    for name in (
        "LLM_API_KEY", "LLM_WRITER_API_KEY", "OPENAI_API_KEY",
        "LLM_BASE_URL", "LLM_WRITER_BASE_URL", "LLM_MODEL",
        "LLM_ACTOR_MODEL", "LLM_WRITER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    def no_sdk(*args, **kwargs):
        pytest.fail("编剧速度回归必须使用模拟模型，不得构造真实模型客户端。")

    monkeypatch.setattr(llm, "AsyncOpenAI", no_sdk)
    if hasattr(checker, "AsyncOpenAI"):
        monkeypatch.setattr(checker, "AsyncOpenAI", no_sdk)


async def generate(runtime_root, monkeypatch, *, review=None):
    calls = []

    async def fake_complete(messages, **kwargs):
        calls.append({"messages": deepcopy(messages), **deepcopy(kwargs)})
        if "problems" in kwargs["mock_response"] and review is not None:
            return deepcopy(review)
        return deepcopy(kwargs["mock_response"])

    monkeypatch.setattr(checker, "complete_for", fake_complete)
    studio = StudioService(runtime_root / "stories")
    job = Job("writer-speed", "chat", "play")
    await studio._generate(job, ["一封消失的信，改编成现实推理案件。"], "new")
    return studio, job, calls


def saved_story(studio, job):
    return yaml.safe_load(
        (studio.stories_dir / f"{job.story_id}.yaml").read_text(encoding="utf-8")
    )


@pytest.mark.asyncio
async def test_one_round_uses_writer_actor_then_two_blind_answers(runtime_root, monkeypatch):
    studio, job, calls = await generate(runtime_root, monkeypatch)

    assert job.status == "done"
    assert saved_story(studio, job)["checked"] is True
    assert [call["role"] for call in calls] == ["writer", "actor", "writer", "actor"]
    assert calls[1]["mock_response"] == {"problems": []}
    assert "problems" in calls[1]["messages"][0]["content"]
    assert calls[2]["mock_response"] == {"answers": {}}
    assert set(calls[3]["mock_response"]) == {"answers"}
    assert calls[3]["mock_response"]["answers"]


@pytest.mark.asyncio
async def test_generation_contract_explains_reference_types_without_schema(runtime_root, monkeypatch):
    _, job, calls = await generate(runtime_root, monkeypatch)
    assert job.status == "done"
    generation = calls[0]["messages"]
    payload = json.loads(generation[-1]["content"])

    assert set(payload) == {"materials", "strategy", "previous_story", "problems", "reference_ids"}
    assert payload["previous_story"] is None and payload["problems"] == []
    for call in calls[:2]:
        assert "schema" not in json.loads(call["messages"][-1]["content"])
        assert "$defs" not in call["messages"][-1]["content"]

    prompt = generation[0]["content"]
    assert re.search(r"knows[^\n]*facts\.id", prompt)
    assert re.search(r"secrets[^\n]*fact[^\n]*本人\s*knows", prompt)
    assert re.search(r"admit[^\n]*本人\s*knows", prompt)
    assert re.search(r"confront[^\n]*(角色|characters\[\]\.id)", prompt)
    assert re.search(r"unlock[^\n]*(线索|clues\[\]\.id)", prompt)

    examples = [json.loads(line) for line in prompt.splitlines() if line.startswith("{")]
    example = next(item for item in examples if {"facts", "characters", "clues", "events"} <= item.keys())
    facts = {item["id"] for item in example["facts"]}
    characters = {item["id"] for item in example["characters"]}
    clues = {item["id"] for item in example["clues"]}
    assert any(character.get("secrets") for character in example["characters"])
    assert any(character.get("lies") for character in example["characters"])
    assert example["events"]
    for character in example["characters"]:
        knows = set(character["knows"])
        assert knows <= facts
        assert all(secret["fact"] in knows for secret in character.get("secrets", []))
        assert all(lie["admit"] in knows for lie in character.get("lies", []))
    for event in example["events"]:
        assert len(set(event["confront"])) == 2
        assert set(event["confront"]) <= characters
        assert set(event["unlock"]) <= clues


@pytest.mark.asyncio
async def test_review_story_cannot_replace_writer_draft_and_game_can_start(runtime_root, monkeypatch):
    replacement = mock_story()
    replacement["title"] = "审稿人试图替换的案件"
    replacement["facts"][0]["text"] = "审稿人擅自改写了核心事实。"
    replacement["ending"]["truth"] = "审稿人擅自改写了完整真相。"
    studio, job, _ = await generate(
        runtime_root, monkeypatch, review={"problems": [], "story": replacement}
    )

    assert job.status == "done"
    stored = saved_story(studio, job)
    expected = checker.Story.model_validate(mock_story()).model_dump()
    expected.update(id=job.story_id, source="generated", checked=stored["checked"])
    assert stored == expected
    engine = GameEngine(runtime_root / "official", studio.stories_dir)
    game = engine.new_game(job.story_id)
    assert game["game_id"] in engine.games
    assert game["title"] == expected["title"]


@pytest.mark.asyncio
async def test_model_timing_log_counts_characters_without_logging_body(runtime_root, monkeypatch, caplog):
    secret = "SECRET_WRITER_SPEED_BODY_请勿记录正文"
    messages = [{"role": "system", "content": "只返回 JSON"}, {"role": "user", "content": secret}]
    response = {"story": {"intro": secret}}

    async def fake_complete(*args, **kwargs):
        return deepcopy(response)

    monkeypatch.setattr(checker, "complete_for", fake_complete)
    studio = StudioService(runtime_root / "stories")
    job = Job("writer-speed-log", "chat", "play")
    with caplog.at_level(logging.INFO, logger="uvicorn.error.studio"):
        result = await studio._model_call(
            job, 1, "生成", messages, role="writer", mock_response={}
        )

    assert result == response
    records = [record for record in caplog.records if job.id in record.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert re.search(r"第\s*1\s*轮.*生成.*完成.*耗时\s+\d+(?:\.\d+)?\s*秒", message)
    counts = re.search(r"输入\s+(\d+)\s*字符.*输出\s+(\d+)\s*字符", message)
    assert counts is not None
    assert int(counts[1]) == sum(len(item["content"]) for item in messages)
    assert int(counts[2]) == len(json.dumps(response, ensure_ascii=False))
    assert secret not in caplog.text
