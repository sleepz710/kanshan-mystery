import json
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI
import pytest

from backend import llm
from backend.studio import check as checker
from backend.studio.service import StudioService
from backend.studio.test_openai_background import response


@pytest.fixture
def writer_transport(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_BASE_URL", "https://actor.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "actor-test-key")
    monkeypatch.setenv("LLM_ACTOR_MODEL", "actor-model")
    monkeypatch.setenv("LLM_WRITER_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_WRITER_API_KEY", "writer-test-key")
    monkeypatch.setenv("LLM_WRITER_MODEL", "gpt-5.4-2026-03-05")

    def install(handler):
        options = []

        def client(**kwargs):
            options.append(kwargs)
            return AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False))

        monkeypatch.setattr(checker, "AsyncOpenAI", client)
        return options

    return install


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", [None, False, True])
async def test_openai_intent_keeps_writer_configuration_and_background_protocol(writer_transport, intent):
    requests = []

    def handle(request):
        requests.append(request)
        return response("completed", content='{"ok":true}')

    options = writer_transport(handle)
    arguments = {} if intent is None else {"intent": intent}
    assert await checker.complete_for([], role="writer", mock_response={}, **arguments) == {"ok": True}
    assert options[0]["base_url"] == "https://api.openai.com/v1"
    assert options[0]["api_key"] == "writer-test-key"
    assert requests[0].url.path == "/v1/responses"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "gpt-5.4-2026-03-05"
    assert payload["reasoning"] == {"effort": "none" if intent else "high"}
    assert payload["background"] is True
    assert "intent" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", [False, True])
async def test_deepseek_intent_disables_thinking_on_the_writer_channel(writer_transport, monkeypatch, intent):
    monkeypatch.setenv("LLM_WRITER_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_WRITER_MODEL", "deepseek-flash")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]})

    options = writer_transport(handle)
    assert await checker.complete_for([], role="writer", mock_response={}, intent=intent) == {"ok": True}
    assert options[0]["base_url"] == "https://api.deepseek.com"
    assert options[0]["api_key"] == "writer-test-key"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "deepseek-flash"
    assert payload["thinking"] == {"type": "disabled" if intent else "enabled"}
    assert payload.get("reasoning_effort") == (None if intent else "high")
    assert "intent" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["clarify", "discuss", "generate"])
async def test_play_raw_reply_cannot_change_public_history_or_design_material(monkeypatch, tmp_path, action):
    studio = StudioService(tmp_path / "stories")
    chat_id = studio.create_chat("play")["chat_id"]
    material = "校园书店闭店后换书，3个人、8条线索、2句谎话、3题、2结局。"
    raw_reply = "我擅自改成4人10线索，并揭晓藏在柜子里的完整谜底。"
    calls, handoff = [], []

    async def complete(messages, **kwargs):
        calls.append(kwargs)
        assert "play素材判意的reply使用空字符串" in messages[0]["content"]
        return {"action": action, "strategy": "new", "reply": raw_reply}

    def start_job(selected_chat, history):
        handoff.extend(studio.chats[selected_chat].materials)
        return SimpleNamespace(id="captured-job", quality="fast")

    monkeypatch.setattr(checker, "complete_for", complete)
    monkeypatch.setattr(studio, "_start_job", start_job)
    first = await studio.message(chat_id, material, {})
    assert calls[0]["role"] == "writer" and calls[0]["intent"] is True
    assert raw_reply not in first["reply"]
    await studio.message(chat_id, "全新", {})
    final = await studio.message(chat_id, "快速", {})
    assert final["job"]["id"] == "captured-job"
    assert handoff[0] == material
    assert raw_reply not in "\n".join(handoff)
    assert raw_reply not in json.dumps(studio.chats[chat_id].history, ensure_ascii=False)
    assert not studio.tasks


@pytest.mark.asyncio
async def test_share_discussion_uses_normal_writer_purpose_and_retains_its_reply(monkeypatch, tmp_path):
    studio = StudioService(tmp_path / "stories")
    chat_id = studio.create_chat("share")["chat_id"]
    calls = []

    async def complete(messages, **kwargs):
        calls.append(kwargs)
        return {"action": "discuss", "strategy": "new", "reply": "可以讨论完整谜底和证据安排。"}

    monkeypatch.setattr(checker, "complete_for", complete)
    result = await studio.message(chat_id, "一起讨论出题方案", {})
    assert calls[0]["role"] == "writer" and calls[0]["intent"] is False
    assert result["reply"] == "可以讨论完整谜底和证据安排。"
    assert studio.chats[chat_id].history[-1]["content"] == result["reply"]
