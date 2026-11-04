"""生成剧场的 HTTP、输入边界、修订流水线与模型配置测试。"""

import asyncio
import json
import socket
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from backend import llm
from backend.app import create_app
from backend.llm import LLMError
from backend.studio import check as checker
from backend.studio import ingest, service
from backend.studio.mock import mock_story
from backend.studio.service import StudioService


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(checker, "check_playability", lambda story: [])
    monkeypatch.setattr(checker, "check_opening", AsyncMock(return_value={"ok": True, "problems": []}))
    monkeypatch.setenv("LLM_MOCK", "1")
    monkeypatch.setattr(llm, "_ENV_FILE", tmp_path / "missing.env")

    def no_sdk(*args, **kwargs):
        pytest.fail("生成剧场回归必须提供模拟客户端。")

    monkeypatch.setattr(llm, "AsyncOpenAI", no_sdk)
    monkeypatch.setattr(checker, "AsyncOpenAI", no_sdk)


@pytest.fixture
def client(tmp_path):
    app = create_app(generated_stories_dir=tmp_path / "stories")
    app.state.studio = StudioService(tmp_path / "stories")
    with TestClient(app) as client:
        yield client


def new_chat(client, mode="play"):
    response = client.post("/api/studio/chats", json={"mode": mode})
    assert response.status_code == 201
    return response.json()["chat_id"]


async def wait_jobs(studio):
    await asyncio.gather(*studio.tasks)


def finish(client):
    client.portal.call(wait_jobs, client.app.state.studio)


async def request_fast_generation(studio, chat_id, text):
    response = await studio.message(chat_id, text, {})
    assert response["job"] is None
    assert "快速" in response["reply"] and "精修" in response["reply"]
    response = await studio.message(chat_id, "快速", {})
    assert response["job"]["quality"] == "fast"
    return response


def test_http_text_confirmation_generation_and_no_spoilers(client):
    chat = new_chat(client)
    first = client.post(f"/api/studio/chats/{chat}/messages", data={"text": "汤面：桌上有个空信封。汤底：秘书把信藏起来了。"})
    assert first.status_code == 200 and first.json()["job"] is None
    assert "看过答案" in first.json()["reply"]
    assert "藏起来" not in first.json()["reply"]
    second = client.post(f"/api/studio/chats/{chat}/messages", data={"text": "直接开始"})
    job_id = second.json()["job"]["id"]
    finish(client)
    response = client.get(f"/api/studio/jobs/{job_id}")
    result = response.json()
    assert result["status"] == "done" and result["owner_token"] is None
    assert result["story_id"].startswith("generated-")
    assert "林青" not in response.text and "陈明" not in response.text
    saved = yaml.safe_load((client.app.state.studio.stories_dir / f"{result['story_id']}.yaml").read_text(encoding="utf-8"))
    assert saved["checked"] is True and saved["source"] == "generated"
    assert checker.check_structure(saved)["ok"]


def test_files_and_all_input_forms(client, monkeypatch):
    monkeypatch.setattr(service, "fetch_url", AsyncMock(return_value="汤面：一封信。汤底：送错了收件人。"))
    chat = new_chat(client)
    response = client.post(f"/api/studio/chats/{chat}/messages", data={"text": "https://example.com/soup 直接开始"}, files=[
        ("files", ("idea.md", "一封消失的信".encode(), "text/markdown")),
        ("files", ("setting.txt", "校园的办公室".encode(), "text/plain")),
    ])
    assert response.status_code == 200
    finish(client)
    stored = client.app.state.studio.chats[chat]
    assert stored.strategy == "seen"
    assert any("办公室" in text for text in stored.materials)
    service.fetch_url.assert_awaited_once_with("https://example.com/soup")


@pytest.mark.parametrize("filename,data", [("bad.pdf", b"test"), ("bad.txt", b"\xff"), ("big.txt", b"x" * (ingest.MAX_FILE_BYTES + 1)), ("empty.md", b"")])
def test_bad_upload_is_rejected_without_consuming_chat(client, filename, data):
    chat = new_chat(client)
    response = client.post(f"/api/studio/chats/{chat}/messages", files={"files": (filename, data)})
    assert response.status_code == 422
    assert client.app.state.studio.chats[chat].history == []


def test_bad_requests_and_unknown_resources(client):
    assert client.post("/api/studio/chats", json={"mode": "admin"}).status_code == 422
    assert client.get("/api/studio/jobs/missing").status_code == 404
    assert client.post("/api/studio/chats/missing/messages", data={"text": "test"}).status_code == 404
    chat = new_chat(client)
    assert client.post(f"/api/studio/chats/{chat}/messages", data={"text": " "}).status_code == 422
    assert client.post(f"/api/studio/chats/{chat}/messages", data={"text": "x" * 20001}).status_code == 422
    assert client.post(f"/api/studio/chats/{chat}/messages", data={"other": "x"}).status_code == 422


@pytest.mark.asyncio
async def test_failed_url_leaves_chat_unchanged(tmp_path, monkeypatch):
    studio = StudioService(tmp_path)
    chat_id = studio.create_chat("play")["chat_id"]
    monkeypatch.setattr(service, "fetch_url", AsyncMock(side_effect=ingest.InputError("请粘贴文字")))
    with pytest.raises(ingest.InputError, match="粘贴"):
        await studio.message(chat_id, "https://example.com", {})
    assert studio.chats[chat_id].materials == []


@pytest.mark.asyncio
async def test_no_play_spoilers_even_if_model_returns_them(tmp_path, monkeypatch):
    studio = StudioService(tmp_path)
    chat_id = studio.create_chat("play")["chat_id"]
    monkeypatch.setattr(checker, "complete_for", AsyncMock(return_value={"action": "clarify", "strategy": "seen", "reply": "凶手是林青"}))
    assert "林青" not in (await studio.message(chat_id, "一个想法", {}))["reply"]


@pytest.mark.asyncio
async def test_share_can_discuss_plot(tmp_path, monkeypatch):
    studio = StudioService(tmp_path)
    chat_id = studio.create_chat("share")["chat_id"]
    monkeypatch.setattr(checker, "complete_for", AsyncMock(return_value={"action": "discuss", "strategy": "new", "reply": "可以让秘书换走信件。"}))
    result = await studio.message(chat_id, "我想讨论一个办公室案件", {})
    assert "秘书" in result["reply"] and result["job"] is None


@pytest.mark.asyncio
async def test_three_repairs_save_unchecked_without_exposing_problems(tmp_path, monkeypatch):
    studio = StudioService(tmp_path)
    checker_mock = AsyncMock(return_value={"ok": False, "problems": ["林青是真凶但缺少证据"]})
    monkeypatch.setattr(checker, "check", checker_mock)
    chat = studio.create_chat("play")["chat_id"]
    result = await request_fast_generation(studio, chat, "生成一个办公室案子")
    await wait_jobs(studio)
    job = studio.jobs[result["job"]["id"]]
    assert checker_mock.await_count == 3
    assert job.status == "done" and "林青" not in json.dumps(job.public(), ensure_ascii=False)
    story = yaml.safe_load((tmp_path / f"{job.story_id}.yaml").read_text(encoding="utf-8"))
    assert story["checked"] is False


@pytest.mark.asyncio
async def test_repair_problems_are_sent_to_next_writer_round(tmp_path, monkeypatch):
    studio = StudioService(tmp_path)
    original = checker.complete_for
    calls = []

    async def recording(messages, **kwargs):
        calls.append(deepcopy(messages))
        return await original(messages, **kwargs)

    monkeypatch.setattr(checker, "complete_for", recording)
    monkeypatch.setattr(checker, "check", AsyncMock(side_effect=[{"ok": False, "problems": ["c4 依赖错误"]}, {"ok": True, "problems": []}]))
    chat = studio.create_chat("play")["chat_id"]
    result = await request_fast_generation(studio, chat, "生成一个新案子")
    await wait_jobs(studio)
    job = studio.jobs[result["job"]["id"]]
    assert job.status == "done" and job.problems == []
    model_inputs = [json.loads(batch[-1]["content"]) for batch in calls]
    generation_inputs = [incoming for incoming in model_inputs if "previous_design" in incoming]
    assert len(generation_inputs) == 2
    assert generation_inputs[0]["previous_design"] is None
    assert generation_inputs[1]["problems"] == ["c4 依赖错误"]
    assert generation_inputs[1]["previous_design"] == StudioService._mock_design()


@pytest.mark.asyncio
async def test_model_outage_fails_job_and_allows_retry(tmp_path, monkeypatch):
    studio = StudioService(tmp_path)
    chat = studio.create_chat("play")["chat_id"]
    original = checker.complete_for

    async def outage(messages, **kwargs):
        incoming = json.loads(messages[-1]["content"])
        if "materials" in incoming and "previous_design" in incoming:
            raise LLMError("模型服务暂时不可用")
        return await original(messages, **kwargs)

    monkeypatch.setattr(checker, "complete_for", outage)
    response = await request_fast_generation(studio, chat, "生成一个案子")
    await wait_jobs(studio)
    assert studio.jobs[response["job"]["id"]].status == "failed"
    assert list(tmp_path.glob("*.yaml")) == []
    monkeypatch.setattr(checker, "complete_for", original)
    retried = await studio.message(chat, "直接开始", {})
    await wait_jobs(studio)
    assert studio.jobs[retried["job"]["id"]].status == "done"


@pytest.mark.asyncio
async def test_concurrent_messages_share_one_running_job(tmp_path, monkeypatch):
    studio = StudioService(tmp_path)
    gate = asyncio.Event()
    original = studio._pipeline

    async def blocked(*args):
        await gate.wait()
        await original(*args)

    monkeypatch.setattr(studio, "_pipeline", blocked)
    chat = studio.create_chat("play")["chat_id"]
    prompt = await studio.message(chat, "生成一个案子", {})
    assert prompt["job"] is None and "快速" in prompt["reply"] and "精修" in prompt["reply"]
    one, two = await asyncio.gather(studio.message(chat, "快速", {}), studio.message(chat, "开始生成", {}))
    assert one["job"]["id"] == two["job"]["id"] and len(studio.jobs) == 1
    gate.set()
    await wait_jobs(studio)


@pytest.mark.asyncio
async def test_shutdown_marks_pending_job_failed(tmp_path, monkeypatch):
    studio = StudioService(tmp_path)
    entered, blocked = asyncio.Event(), asyncio.Event()

    async def pending(*args):
        entered.set()
        await blocked.wait()

    monkeypatch.setattr(studio, "_pipeline", pending)
    chat = studio.create_chat("play")["chat_id"]
    result = await request_fast_generation(studio, chat, "生成一个案子")
    await asyncio.wait_for(entered.wait(), 2)
    await studio.close()
    assert studio.jobs[result["job"]["id"]].status == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://[::1]/", "http://10.0.0.1/", "file:///etc/passwd", "http://user:pass@example.com/", "http://example.com:8000/"])
async def test_fetch_rejects_non_public_urls(url):
    with pytest.raises(ingest.InputError):
        await ingest.fetch_url(url)


@pytest.mark.asyncio
async def test_dns_private_result_is_rejected(monkeypatch):
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.5", 80))]))
    with pytest.raises(ingest.InputError, match="公网"):
        await ingest.fetch_url("https://public.example/")


@pytest.mark.asyncio
async def test_public_fetch_pins_dns_address_and_extracts_text(monkeypatch):
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]))
    client_type = httpx.AsyncClient

    def handle(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.com"
        assert request.extensions["sni_hostname"] == "example.com"
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body><article><h1>一封消失的信</h1><p>桌上还放着完整的信封，但是里面的信不见了。秘书说没有动过它，保安却见到有人在走廊寄出一个包裹。</p></article></body></html>")

    monkeypatch.setattr(ingest.httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handle), **kw))
    text = await ingest.fetch_url("https://example.com/soup")
    assert "信封" in text and "<html>" not in text


@pytest.mark.asyncio
async def test_redirect_is_rechecked_and_cannot_enter_private_network(monkeypatch):
    loop = asyncio.get_running_loop()

    async def dns(host, port, **kw):
        address = "127.0.0.1" if host == "localhost" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(loop, "getaddrinfo", dns)
    client_type = httpx.AsyncClient
    requests = []

    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://localhost/private"})

    monkeypatch.setattr(ingest.httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(redirect), **kw))
    with pytest.raises(ingest.InputError, match="公网"):
        await ingest.fetch_url("https://example.com/")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_close_before_task_starts_does_not_leave_running_job(tmp_path):
    studio = StudioService(tmp_path)
    chat = studio.create_chat("play")["chat_id"]
    result = await request_fast_generation(studio, chat, "生成一个案子")
    await studio.close()
    assert studio.jobs[result["job"]["id"]].status == "failed"


@pytest.mark.asyncio
async def test_two_models_and_provider_thinking_flags(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_WRITER_MODEL", "writer-test")
    monkeypatch.setenv("LLM_ACTOR_MODEL", "actor-test")
    monkeypatch.delenv("LLM_WRITER_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_WRITER_API_KEY", raising=False)
    create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content='{"ok":true}'))]))

    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    constructor = Mock(return_value=Client())
    monkeypatch.setattr(checker, "AsyncOpenAI", constructor)
    await checker.complete_for([], role="actor", mock_response={})
    assert create.call_args.kwargs["model"] == "actor-test"
    assert create.call_args.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    await checker.complete_for([], role="writer", mock_response={})
    assert create.call_args.kwargs["model"] == "writer-test"
    assert create.call_args.kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    monkeypatch.setenv("LLM_WRITER_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_WRITER_API_KEY", "writer-key")
    await checker.complete_for([], role="writer", mock_response={})
    assert "extra_body" not in create.call_args.kwargs
    assert constructor.call_args.kwargs["api_key"] == "writer-key"
