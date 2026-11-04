"""编剧完整调用期限、保活等待、重试与会话状态的离线回归。"""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from openai import APIStatusError, AsyncOpenAI
import pytest
import yaml

from backend import llm
from backend.app import create_app
from backend.engine import GameEngine
from backend.studio import check as checker, service
from backend.studio.mock import mock_story
from backend.studio.service import Job, StudioService


@pytest.fixture(autouse=True)
def isolated_models(monkeypatch, tmp_path):
    monkeypatch.setattr(checker, "check_playability", lambda story: [])
    monkeypatch.setattr(llm, "_ENV_FILE", tmp_path / "missing.env")
    for name in (
        "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_ACTOR_MODEL",
        "LLM_WRITER_MODEL", "LLM_WRITER_BASE_URL", "LLM_WRITER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_MOCK", "1")

    def unexpected_client(*args, **kwargs):
        pytest.fail("调用期限回归只使用离线 HTTP 客户端。")

    monkeypatch.setattr(llm, "AsyncOpenAI", unexpected_client)
    monkeypatch.setattr(checker, "AsyncOpenAI", unexpected_client)


@pytest.fixture
def install_http_model(monkeypatch):
    def install(handler):
        monkeypatch.setenv("LLM_MOCK", "0")
        monkeypatch.setenv("LLM_BASE_URL", "https://model.example.test/v1")
        monkeypatch.setenv("LLM_API_KEY", "test-key-not-a-secret")

        sdk_client = AsyncOpenAI(
            base_url="https://model.example.test/v1", api_key="test-key-not-a-secret",
            timeout=120, max_retries=1,
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler), verify=False, trust_env=False,
            ),
        )
        # 先完成 SDK 懒加载，让缩短后的期限只测请求等待与重试。
        sdk_client.chat.completions
        sdk_client.default_headers

        def client(**kwargs):
            return sdk_client

        monkeypatch.setattr(checker, "AsyncOpenAI", client)

    return install


class KeepAlive(httpx.AsyncByteStream):
    def __init__(self):
        self.started = asyncio.Event()
        self.chunks = 0
        self.closed = False

    async def __aiter__(self):
        self.started.set()
        while True:
            await asyncio.sleep(0.005)
            self.chunks += 1
            yield b"\n"

    async def aclose(self):
        self.closed = True


def completion(content):
    return httpx.Response(200, json={
        "id": "test-completion", "object": "chat.completion", "created": 0,
        "model": "test-model", "choices": [{
            "index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": content},
        }],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["writer", "actor"])
@pytest.mark.parametrize("base", ["https://api.deepseek.com", "https://model.example.test/v1"])
async def test_generation_thinking_effort_preserves_roles(monkeypatch, install_http_model, role, base):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return completion('{"problems": []}')

    install_http_model(handle)
    monkeypatch.setenv("LLM_BASE_URL", base)
    result = await checker.complete_for([], role=role, mock_response={})

    assert result == {"problems": []}
    payload = requests[0]
    if base == "https://api.deepseek.com":
        assert payload["thinking"] == {"type": "enabled" if role == "writer" else "disabled"}
        if role == "writer":
            assert payload["reasoning_effort"] == "high"
        else:
            assert "reasoning_effort" not in payload
    else:
        assert "thinking" not in payload and "reasoning_effort" not in payload


@pytest.mark.asyncio
async def test_inner_timeout_is_not_a_request_deadline(monkeypatch):
    create = AsyncMock(side_effect=TimeoutError("inner timeout"))

    @asynccontextmanager
    async def client(**kwargs):
        yield SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-a-secret")
    monkeypatch.setattr(checker, "AsyncOpenAI", client)
    with pytest.raises(TimeoutError, match="inner timeout") as error:
        await checker.complete_for([], role="writer", mock_response={})

    assert type(error.value) is TimeoutError and create.await_count == 1


@pytest.mark.asyncio
async def test_api_failure_logs_only_role_type_and_status(monkeypatch, caplog):
    secret = "PRIVATE_PROVIDER_RESPONSE_AND_KEY"
    response = httpx.Response(
        403, request=httpx.Request("POST", "https://model.example.test/v1"),
        headers={"authorization": secret}, json={"error": secret},
    )
    create = AsyncMock(side_effect=APIStatusError(secret, response=response, body={"error": secret}))

    @asynccontextmanager
    async def client(**kwargs):
        yield SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_API_KEY", secret)
    monkeypatch.setattr(checker, "AsyncOpenAI", client)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(llm.LLMError) as error:
            await checker.complete_for([], role="writer", mock_response={})

    assert "编剧模型调用失败：APIStatusError status=403" in caplog.text
    assert secret not in caplog.text and secret not in error.value.message


@pytest.mark.asyncio
async def test_keepalive_bytes_cannot_extend_complete_call(monkeypatch, install_http_model):
    stream = KeepAlive()
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)

    install_http_model(handle)
    monkeypatch.setattr(checker, "MODEL_CALL_TIMEOUT", 2)
    with pytest.raises(checker.ModelTimeoutError) as error:
        await asyncio.wait_for(checker.complete_for([], role="writer", mock_response={}), 5)

    assert error.value.status_code == 504
    assert len(requests) == 1
    assert stream.chunks >= 2 and stream.closed


@pytest.mark.asyncio
async def test_json_retry_shares_original_deadline(monkeypatch, install_http_model):
    requests = []

    async def handle(request):
        requests.append(json.loads(request.content))
        await asyncio.sleep(0.12)
        return completion("{" if len(requests) == 1 else '{"ok":true}')

    install_http_model(handle)
    monkeypatch.setattr(checker, "MODEL_CALL_TIMEOUT", 0.2)
    with pytest.raises(checker.ModelTimeoutError):
        await asyncio.wait_for(checker.complete_for([], role="writer", mock_response={}), 2)

    assert len(requests) == 2
    assert requests[1]["messages"][-1]["content"] == checker._JSON_REPAIR_INSTRUCTION


@pytest.mark.asyncio
async def test_sdk_retry_shares_original_deadline(monkeypatch, install_http_model):
    requests = []

    async def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"retry-after-ms": "120"}, json={
                "error": {"message": "test throttling", "type": "rate_limit_error"},
            })
        await asyncio.sleep(0.12)
        return completion('{"ok":true}')

    install_http_model(handle)
    monkeypatch.setattr(checker, "MODEL_CALL_TIMEOUT", 0.2)
    with pytest.raises(checker.ModelTimeoutError):
        await asyncio.wait_for(checker.complete_for([], role="writer", mock_response={}), 2)

    assert len(requests) == 2


@pytest.mark.asyncio
async def test_generation_timeout_can_succeed_next_round(tmp_path, monkeypatch, caplog):
    studio = StudioService(tmp_path / "stories")
    job = Job("retry-timeout", "chat", "play")
    generations = []

    async def model(messages, **kwargs):
        incoming = json.loads(messages[-1]["content"])
        if "materials" in incoming:
            generations.append(incoming)
            if len(generations) == 1:
                raise checker.ModelTimeoutError()
        return deepcopy(kwargs["mock_response"])

    monkeypatch.setattr(checker, "complete_for", model)
    with caplog.at_level(logging.INFO):
        await studio._generate(job, ["PRIVATE_MATERIAL"], "new")

    assert len(generations) == 2
    assert any("超时" in problem for problem in generations[1]["problems"])
    assert job.status == "done" and job.error is None
    assert GameEngine(tmp_path / "official", studio.stories_dir).new_game(job.story_id)
    assert any("第 1 轮 设计稿 超时" in record.message for record in caplog.records)
    assert "PRIVATE_MATERIAL" not in caplog.text


@pytest.mark.asyncio
async def test_three_generation_timeouts_fail_without_publishing(tmp_path, monkeypatch):
    studio = StudioService(tmp_path / "stories")
    job = Job("all-timeouts", "chat", "share")
    calls = 0

    async def model(messages, **kwargs):
        nonlocal calls
        calls += 1
        raise checker.ModelTimeoutError()

    monkeypatch.setattr(checker, "complete_for", model)
    await studio._generate(job, ["technical fixture"], "new")

    assert calls == 3 and job.status == "failed"
    assert "超时" in job.error and "三轮" in job.error
    assert "设计" in job.error or "填表" in job.error
    assert job.story_id is None and job.owner_token is None
    assert list(tmp_path.rglob("*.yaml")) == []
    assert list(tmp_path.rglob("*.json")) == []


@pytest.mark.asyncio
async def test_total_deadline_cancels_without_retry(tmp_path, monkeypatch, install_http_model):
    stream = KeepAlive()
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)

    install_http_model(handle)
    monkeypatch.setattr(checker, "MODEL_CALL_TIMEOUT", 0.5)
    monkeypatch.setattr(service, "GENERATION_TIMEOUT", service.SAVE_RESERVE + 0.1)
    studio = StudioService(tmp_path / "stories")
    job = Job("total-deadline", "chat", "play")
    await asyncio.wait_for(studio._generate(job, ["technical fixture"], "new"), 2)

    assert len(requests) == 1 and stream.closed
    assert job.status == "failed" and job.error == "生成超时，请重试。"
    assert list(tmp_path.rglob("*.yaml")) == []


@pytest.mark.asyncio
async def test_first_message_deadline_preserves_chat(tmp_path, monkeypatch, install_http_model):
    stream = KeepAlive()
    install_http_model(lambda request: httpx.Response(
        200, headers={"content-type": "application/json"}, stream=stream,
    ))
    monkeypatch.setattr(checker, "MODEL_CALL_TIMEOUT", 0.1)
    app = create_app(stories_dir=tmp_path / "official", generated_stories_dir=tmp_path / "stories")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", trust_env=False) as client:
        created = await client.post("/api/studio/chats", json={"mode": "play"})
        chat_id = created.json()["chat_id"]
        response = await client.post(
            f"/api/studio/chats/{chat_id}/messages",
            data={"text": "我想玩恐怖一点的，医院题材"},
            files=[("files", ("idea.txt", b"PRIVATE_MATERIAL", "text/plain"))],
        )

    assert response.status_code == 504 and "超时" in response.json()["detail"]
    chat = app.state.studio.chats[chat_id]
    assert chat.history == [] and chat.files == {} and chat.materials == []
    assert chat.urls == set() and chat.job_id is None and not chat.asked
    assert not chat.lock.locked()
    assert app.state.studio.jobs == {} and app.state.studio.tasks == set()
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_step", ["review", "intro_answers", "clue_answers", "later_generation"])
async def test_step_deadline_preserves_playable_draft(tmp_path, monkeypatch, failure_step):
    studio = StudioService(tmp_path / "stories")
    job = Job("keep-draft", "chat", "play")
    generations = 0

    async def model(messages, **kwargs):
        nonlocal generations
        incoming = json.loads(messages[-1]["content"])
        if "design" in kwargs["mock_response"]:
            generations += 1
            if generations > 1 and failure_step == "later_generation":
                raise checker.ModelTimeoutError()
            return deepcopy(kwargs["mock_response"])
        if "story" in kwargs["mock_response"]:
            return {"story": mock_story()}
        if "problems" in kwargs["mock_response"]:
            step = "review"
        else:
            step = "intro_answers" if kwargs["role"] == "writer" else "clue_answers"
        if step == failure_step:
            raise checker.ModelTimeoutError()
        if failure_step == "later_generation" and step == "clue_answers":
            return {"answers": {question["id"]: None for question in mock_story()["ending"]["questions"]}}
        return deepcopy(kwargs["mock_response"])

    monkeypatch.setattr(checker, "complete_for", model)
    await studio._generate(job, ["technical fixture"], "new")

    assert job.status == "done" and job.error
    saved = yaml.safe_load((studio.stories_dir / f"{job.story_id}.yaml").read_text(encoding="utf-8"))
    assert saved["title"] == mock_story()["title"] and saved["checked"] is False
    assert GameEngine(tmp_path / "official", studio.stories_dir).new_game(job.story_id)
    if failure_step == "later_generation":
        assert generations == 3


@pytest.mark.asyncio
async def test_external_cancellation_propagates_without_retry(tmp_path, install_http_model):
    stream = KeepAlive()
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)

    install_http_model(handle)
    studio = StudioService(tmp_path / "stories")
    job = Job("shutdown", "chat", "play")
    task = asyncio.create_task(studio._generate(job, ["technical fixture"], "new"))
    try:
        await asyncio.wait_for(stream.started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert len(requests) == 1 and stream.closed
    assert job.status == "failed" and "关闭" in job.error
    assert list(tmp_path.rglob("*.yaml")) == []
