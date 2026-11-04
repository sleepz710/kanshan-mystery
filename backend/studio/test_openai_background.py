"""官方 GPT-5.4 编剧后台响应的离线 SDK/HTTP 回归。"""

import asyncio
import json
import logging
from time import monotonic

import httpx
from openai import AsyncOpenAI
import pytest

from backend import llm
from backend.studio import check as checker


MODEL = "gpt-5.4-2026-03-05"


def response(status, *, response_id="resp-test", content=None):
    output = []
    if content is not None:
        output = [{
            "id": "msg-test", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": content, "annotations": []}],
        }]
    return httpx.Response(200, json={
        "id": response_id, "object": "response", "created_at": 0, "status": status,
        "model": MODEL, "output": output,
    })


@pytest.fixture
def background_model(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-a-secret")
    monkeypatch.setenv("LLM_WRITER_BASE_URL", "")
    monkeypatch.setenv("LLM_WRITER_API_KEY", "")
    monkeypatch.setenv("LLM_WRITER_MODEL", MODEL)
    monkeypatch.setattr(checker, "_BACKGROUND_POLL_INTERVAL", 0.001)
    monkeypatch.setattr(checker, "_BACKGROUND_RETRY_DELAYS", (0.001, 0.002))
    monkeypatch.setattr(checker, "MODEL_CALL_TIMEOUT", 1)
    monkeypatch.setattr(checker, "OPENAI_WRITER_CALL_TIMEOUT", 1)

    def install(handler):
        client = AsyncOpenAI(
            base_url="https://api.openai.com/v1", api_key="test-key-not-a-secret",
            timeout=120, max_retries=1,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False),
        )
        client.responses
        client.default_headers
        monkeypatch.setattr(checker, "AsyncOpenAI", lambda **kwargs: client)

    return install


@pytest.mark.asyncio
async def test_background_creation_polling_and_combined_output_text(background_model):
    requests = []
    replies = [response("queued"), response("in_progress"), response("completed", content='{"ok": true}')]

    def handle(request):
        requests.append(request)
        return replies.pop(0)

    background_model(handle)
    messages = [{"role": "system", "content": "只返回JSON"}, {"role": "user", "content": "设计素材"}]
    assert await checker.complete_for(messages, role="writer", mock_response={}) == {"ok": True}
    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/v1/responses"), ("GET", "/v1/responses/resp-test"), ("GET", "/v1/responses/resp-test"),
    ]
    payload = json.loads(requests[0].content)
    assert payload == {"model": MODEL, "input": messages, "background": True, "store": False,
                       "reasoning": {"effort": "high"}, "text": {"format": {"type": "json_object"}}}


@pytest.mark.asyncio
async def test_background_completed_on_creation_uses_all_output_text_parts(background_model):
    requests = []

    def handle(request):
        requests.append(request)
        result = json.loads(response("completed", content='{"ok":').content)
        result["output"][0]["content"].append({"type": "output_text", "text": "true}", "annotations": []})
        return httpx.Response(200, json=result)

    background_model(handle)
    assert await checker.complete_for([], role="writer", mock_response={}) == {"ok": True}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_background_writer_can_outlast_the_original_model_deadline(background_model, monkeypatch):
    requests = []

    async def handle(request):
        requests.append(request)
        if request.method == "GET":
            await asyncio.sleep(0.04)
            return response("completed", content='{"ok":true}')
        return response("in_progress")

    background_model(handle)
    monkeypatch.setattr(checker, "MODEL_CALL_TIMEOUT", 0.02)
    monkeypatch.setattr(checker, "OPENAI_WRITER_CALL_TIMEOUT", 0.2)
    assert await checker.complete_for([], role="writer", mock_response={}) == {"ok": True}
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_background_invalid_json_retries_once_without_replaying_bad_output(background_model):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return response("completed", content="{" if len(requests) == 1 else '{"ok":true}')

    background_model(handle)
    messages = [{"role": "user", "content": "只返回JSON"}]
    assert await checker.complete_for(messages, role="writer", mock_response={}) == {"ok": True}
    assert requests[1]["input"] == [*messages, {"role": "user", "content": checker._JSON_REPAIR_INSTRUCTION}]
    assert messages == [{"role": "user", "content": "只返回JSON"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "cancelled", "incomplete"])
async def test_background_terminal_failures_never_accept_partial_json(background_model, caplog, status):
    requests = []

    def handle(request):
        requests.append(request)
        result = json.loads(response(status, content='{"ok":true}').content)
        result["error"] = {"code": "server_error", "message": "PRIVATE_PROVIDER_ERROR"}
        return httpx.Response(200, json=result)

    background_model(handle)
    with caplog.at_level(logging.WARNING), pytest.raises(llm.LLMError) as error:
        await checker.complete_for([], role="writer", mock_response={})
    assert len(requests) == 1
    assert "PRIVATE_PROVIDER_ERROR" not in str(error.value) + caplog.text
    if status == "incomplete":
        assert isinstance(error.value, checker.ReplyFormatError) and error.value.retry is False


@pytest.mark.asyncio
async def test_background_poll_failure_cancels_known_response_and_hides_provider_error(background_model, caplog):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(400, json={"error": {"message": "PRIVATE_PROVIDER_ERROR"}})
        return response("cancelled" if request.url.path.endswith("/cancel") else "in_progress")

    background_model(handle)
    with caplog.at_level(logging.WARNING), pytest.raises(llm.LLMError) as error:
        await checker.complete_for([], role="writer", mock_response={})
    assert requests[-1].url.path == "/v1/responses/resp-test/cancel"
    assert "PRIVATE_PROVIDER_ERROR" not in str(error.value) + caplog.text


@pytest.mark.asyncio
async def test_background_poll_connection_and_server_failures_resume_same_response(background_model, caplog):
    requests = []
    polls = 0

    def handle(request):
        nonlocal polls
        requests.append(request)
        if request.method == "GET":
            polls += 1
            if polls in {1, 4}:
                raise httpx.ConnectError("PRIVATE_CONNECTION_DETAIL", request=request)
            if polls in {2, 5}:
                return httpx.Response(503, json={"error": {"message": "PRIVATE_SERVER_DETAIL"}})
            return response("completed" if polls == 6 else "in_progress", content='{"ok":true}')
        return response("in_progress")

    background_model(handle)
    with caplog.at_level(logging.WARNING):
        assert await checker.complete_for([], role="writer", mock_response={}) == {"ok": True}
    assert sum(request.method == "POST" for request in requests) == 1
    assert polls == 6
    assert {request.url.path for request in requests if request.method == "GET"} == {"/v1/responses/resp-test"}
    assert not any(request.url.path.endswith("/cancel") for request in requests)
    assert "连续失败=2" in caplog.text and "连续失败=3" not in caplog.text
    assert "PRIVATE_CONNECTION_DETAIL" not in caplog.text and "PRIVATE_SERVER_DETAIL" not in caplog.text


@pytest.mark.asyncio
async def test_background_three_consecutive_poll_failures_cancel_without_recreation(background_model):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            raise httpx.ReadTimeout("PRIVATE_TIMEOUT_DETAIL", request=request)
        return response("cancelled" if request.url.path.endswith("/cancel") else "in_progress")

    background_model(handle)
    with pytest.raises(llm.LLMError):
        await checker.complete_for([], role="writer", mock_response={})
    assert sum(request.method == "GET" for request in requests) == 3
    assert sum(request.url.path == "/v1/responses" for request in requests) == 1
    assert requests[-1].url.path == "/v1/responses/resp-test/cancel"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 403, 429])
async def test_background_nonretryable_poll_status_cancels_immediately(background_model, status):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(status, json={"error": {"message": "PRIVATE_PROVIDER_DETAIL"}})
        return response("cancelled" if request.url.path.endswith("/cancel") else "in_progress")

    background_model(handle)
    with pytest.raises(llm.LLMError):
        await checker.complete_for([], role="writer", mock_response={})
    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/v1/responses"), ("GET", "/v1/responses/resp-test"),
        ("POST", "/v1/responses/resp-test/cancel"),
    ]


@pytest.mark.asyncio
async def test_background_create_connection_error_is_not_retried(background_model):
    requests = []

    def handle(request):
        requests.append(request)
        raise httpx.ConnectError("PRIVATE_CONNECTION_DETAIL", request=request)

    background_model(handle)
    with pytest.raises(llm.LLMError):
        await checker.complete_for([], role="writer", mock_response={})
    assert len(requests) == 1 and requests[0].url.path == "/v1/responses"


@pytest.mark.asyncio
async def test_background_retry_backoff_remains_inside_the_total_deadline(background_model, monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(503, json={"error": {"message": "PRIVATE_SERVER_DETAIL"}})
        return response("cancelled" if request.url.path.endswith("/cancel") else "in_progress")

    background_model(handle)
    monkeypatch.setattr(checker, "OPENAI_WRITER_CALL_TIMEOUT", 0.03)
    monkeypatch.setattr(checker, "_BACKGROUND_RETRY_DELAYS", (0.1, 0.2))
    with pytest.raises(checker.ModelTimeoutError):
        await checker.complete_for([], role="writer", mock_response={})
    assert sum(request.method == "GET" for request in requests) == 1
    assert sum(request.url.path == "/v1/responses" for request in requests) == 1
    assert requests[-1].url.path == "/v1/responses/resp-test/cancel"


@pytest.mark.asyncio
async def test_background_deadline_cancels_remote_response(background_model, monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        return response("cancelled" if request.url.path.endswith("/cancel") else "in_progress")

    background_model(handle)
    monkeypatch.setattr(checker, "OPENAI_WRITER_CALL_TIMEOUT", 0.03)
    with pytest.raises(checker.ModelTimeoutError):
        await checker.complete_for([], role="writer", mock_response={})
    assert requests[0].url.path == "/v1/responses"
    assert requests[-1].url.path == "/v1/responses/resp-test/cancel"
    assert sum(request.url.path.endswith("/cancel") for request in requests) == 1


@pytest.mark.asyncio
async def test_background_external_repeated_cancellation_waits_for_bounded_remote_cleanup(background_model):
    polling, cancelling, finish_cancel = asyncio.Event(), asyncio.Event(), asyncio.Event()
    requests = []

    async def handle(request):
        requests.append(request)
        if request.url.path.endswith("/cancel"):
            cancelling.set()
            await finish_cancel.wait()
            return response("cancelled")
        if request.method == "GET":
            polling.set()
            await asyncio.Event().wait()
        return response("in_progress")

    background_model(handle)
    task = asyncio.create_task(checker.complete_for([], role="writer", mock_response={}))
    await asyncio.wait_for(polling.wait(), 1)
    task.cancel()
    await asyncio.wait_for(cancelling.wait(), 1)
    task.cancel()
    finish_cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sum(request.url.path.endswith("/cancel") for request in requests) == 1


@pytest.mark.asyncio
async def test_background_cancel_timeout_preserves_original_deadline_error(background_model, monkeypatch, caplog):
    requests = []

    async def handle(request):
        requests.append(request)
        if request.url.path.endswith("/cancel"):
            await asyncio.Event().wait()
        return response("in_progress")

    background_model(handle)
    monkeypatch.setattr(checker, "OPENAI_WRITER_CALL_TIMEOUT", 0.03)
    monkeypatch.setattr(checker, "_BACKGROUND_CANCEL_TIMEOUT", 0.02)
    started = monotonic()
    with caplog.at_level(logging.WARNING), pytest.raises(checker.ModelTimeoutError):
        await asyncio.wait_for(checker.complete_for([], role="writer", mock_response={}), 0.5)
    assert monotonic() - started < 0.5
    assert requests[-1].url.path.endswith("/cancel")
    assert "取消失败：TimeoutError" in caplog.text


@pytest.mark.asyncio
async def test_background_format_retry_uses_the_original_wall_clock(background_model, monkeypatch):
    requests = []
    creations = 0

    async def handle(request):
        nonlocal creations
        requests.append(request)
        if request.url.path == "/v1/responses":
            creations += 1
            if creations == 1:
                await asyncio.sleep(0.02)
                return response("completed", content="{")
        return response("cancelled" if request.url.path.endswith("/cancel") else "in_progress", response_id="resp-retry")

    background_model(handle)
    monkeypatch.setattr(checker, "OPENAI_WRITER_CALL_TIMEOUT", 0.05)
    with pytest.raises(checker.ModelTimeoutError):
        await checker.complete_for([], role="writer", mock_response={})
    assert creations == 2
    assert requests[-1].url.path == "/v1/responses/resp-retry/cancel"
