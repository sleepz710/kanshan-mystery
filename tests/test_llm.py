import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from openai import APIConnectionError, APIError, APITimeoutError

from backend import llm


ENV_NAMES = (
    "LLM_MOCK", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
    "LLM_ACTOR_MODEL", "LLM_WRITER_MODEL", "LLM_WRITER_BASE_URL", "LLM_WRITER_API_KEY",
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "_ENV_FILE", tmp_path / "missing.env")
    for key in ENV_NAMES:
        # 先登记恢复动作，dotenv 后续写入的变量也会在测试结束时清理。
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)


def real_mode(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_BASE_URL", "https://model.example.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-a-real-secret")
    monkeypatch.setenv("LLM_ACTOR_MODEL", "test-actor")
    monkeypatch.setenv("LLM_WRITER_MODEL", "test-writer")


def fake_client(monkeypatch, content='{"reply": "你好"}', *, error=None, choices=None):
    completion = SimpleNamespace(
        choices=choices if choices is not None else [
            SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")
        ]
    )
    create = AsyncMock(return_value=completion, side_effect=error)

    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    constructor = Mock(return_value=Client())
    monkeypatch.setattr(llm, "AsyncOpenAI", constructor)
    return constructor, create


@pytest.mark.parametrize("purpose", ["actor", "writer"])
def test_default_mock_never_constructs_client_and_returns_independent_data(monkeypatch, purpose):
    constructor = Mock(side_effect=AssertionError("模拟模式不应创建模型客户端"))
    monkeypatch.setattr(llm, "AsyncOpenAI", constructor)
    source = {"reply": "模拟", "reveal": ["c1"]}
    result = asyncio.run(llm.complete_json([], purpose=purpose, mock_response=source))
    result["reveal"].append("c2")
    assert llm.is_mock_mode() is True
    assert source["reveal"] == ["c1"]
    constructor.assert_not_called()


def test_old_mock_call_remains_compatible():
    assert asyncio.run(llm.complete_json([], mock_response={"ok": True})) == {"ok": True}


def test_mock_requires_an_explicit_json_object():
    with pytest.raises(llm.LLMError, match="mock_response") as error:
        asyncio.run(llm.complete_json([]))
    assert error.value.status_code == 503


def test_env_file_is_utf8_and_process_model_and_key_take_priority(monkeypatch, tmp_path):
    env_file = tmp_path / "config.env"
    env_file.write_text(
        "# 中文配置\nLLM_MOCK=0\nLLM_ACTOR_MODEL=来自文件\nLLM_WRITER_MODEL=文件编剧\n"
        "LLM_API_KEY=file-test-key\nLLM_WRITER_API_KEY=file-writer-key\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(llm, "_ENV_FILE", env_file)
    monkeypatch.setenv("LLM_MOCK", "1")
    monkeypatch.setenv("LLM_ACTOR_MODEL", "process-model")
    monkeypatch.setenv("LLM_API_KEY", "process-test-key")
    monkeypatch.setenv("LLM_WRITER_API_KEY", "process-writer-key")
    assert llm.is_mock_mode() is True
    assert os.environ["LLM_ACTOR_MODEL"] == "process-model"
    assert os.environ["LLM_WRITER_MODEL"] == "文件编剧"
    assert os.environ["LLM_API_KEY"] == "process-test-key"
    assert os.environ["LLM_WRITER_API_KEY"] == "process-writer-key"


def test_env_file_can_select_real_mode(monkeypatch, tmp_path):
    env_file = tmp_path / "config.env"
    env_file.write_text("LLM_MOCK=0\n", encoding="utf-8")
    monkeypatch.setattr(llm, "_ENV_FILE", env_file)
    assert llm.is_mock_mode() is False


@pytest.mark.parametrize("mode", ["yes", "", "2"])
def test_invalid_mode_is_a_configuration_error(monkeypatch, mode):
    monkeypatch.setenv("LLM_MOCK", mode)
    with pytest.raises(llm.LLMError, match="LLM_MOCK") as error:
        llm.is_mock_mode()
    assert error.value.status_code == 503


@pytest.mark.parametrize("purpose", ["", "reviewer", None, [], True])
def test_unknown_purpose_is_rejected_including_mock_mode(purpose):
    with pytest.raises(llm.LLMError, match="purpose") as error:
        asyncio.run(llm.complete_json([], purpose=purpose, mock_response={}))
    assert error.value.status_code == 503


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2048"])
def test_invalid_token_limit_is_rejected(value):
    with pytest.raises(llm.LLMError, match="max_tokens") as error:
        asyncio.run(llm.complete_json([], max_tokens=value, mock_response={}))
    assert error.value.status_code == 503


def test_real_mode_requires_key_without_falling_back_to_mock(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    constructor = Mock(side_effect=AssertionError("缺配置时不应创建客户端"))
    monkeypatch.setattr(llm, "AsyncOpenAI", constructor)
    with pytest.raises(llm.LLMError, match="LLM_API_KEY") as error:
        asyncio.run(llm.complete_json([], mock_response={"reply": "不应使用"}))
    assert error.value.status_code == 503
    constructor.assert_not_called()


@pytest.mark.parametrize(
    "purpose, model, tokens, thinking",
    [("actor", "deepseek-flash", 1024, "disabled"), ("writer", "deepseek-flash", 8192, "enabled")],
)
def test_default_deepseek_purposes_select_models_and_thinking(monkeypatch, purpose, model, tokens, thinking):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_API_KEY", "shared-test-key")
    constructor, create = fake_client(monkeypatch)
    messages = [{"role": "user", "content": "请用 JSON 回复"}]
    assert asyncio.run(llm.complete_json(messages, purpose=purpose)) == {"reply": "你好"}
    constructor.assert_called_once_with(
        api_key="shared-test-key", base_url="https://api.deepseek.com", timeout=30.0, max_retries=1
    )
    additional = {"temperature": 0} if purpose == "actor" else {}
    create.assert_awaited_once_with(
        model=model, messages=messages, response_format={"type": "json_object"}, max_tokens=tokens,
        extra_body={"thinking": {"type": thinking}},
        **additional,
    )
    if purpose == "writer":
        assert "temperature" not in create.await_args.kwargs


@pytest.mark.parametrize("base_url", ["https://api.deepseek.com/v1", "https://API.DEEPSEEK.COM:443/v1/"])
def test_official_deepseek_host_is_recognized_with_version_path(monkeypatch, base_url):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_BASE_URL", base_url)
    monkeypatch.setenv("LLM_API_KEY", "shared-test-key")
    _, create = fake_client(monkeypatch)
    asyncio.run(llm.complete_json([]))
    assert create.await_args.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_actor_model_override_takes_priority_over_legacy_model(monkeypatch):
    real_mode(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "legacy-model")
    _, create = fake_client(monkeypatch)
    asyncio.run(llm.complete_json([]))
    assert create.await_args.kwargs["model"] == "test-actor"


def test_legacy_model_is_actor_fallback_for_old_real_calls(monkeypatch):
    real_mode(monkeypatch)
    monkeypatch.delenv("LLM_ACTOR_MODEL")
    monkeypatch.setenv("LLM_MODEL", "legacy-model")
    _, create = fake_client(monkeypatch)
    asyncio.run(llm.complete_json([]))
    assert create.await_args.kwargs["model"] == "legacy-model"


def test_legacy_actor_model_does_not_replace_writer_model(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_API_KEY", "shared-test-key")
    monkeypatch.setenv("LLM_MODEL", "legacy-actor")
    _, create = fake_client(monkeypatch)
    asyncio.run(llm.complete_json([], purpose="writer"))
    assert create.await_args.kwargs["model"] == "deepseek-flash"


def test_writer_can_use_its_own_provider_key_and_model(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_API_KEY", "actor-test-key")
    monkeypatch.setenv("LLM_WRITER_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_WRITER_API_KEY", "writer-test-key")
    monkeypatch.setenv("LLM_WRITER_MODEL", "writer-model")
    constructor, create = fake_client(monkeypatch)
    asyncio.run(llm.complete_json([], purpose="writer"))
    assert constructor.call_args.kwargs["api_key"] == "writer-test-key"
    assert constructor.call_args.kwargs["base_url"] == "https://api.openai.com/v1"
    assert create.await_args.kwargs == {
        "model": "writer-model", "messages": [], "response_format": {"type": "json_object"}, "max_tokens": 8192
    }


@pytest.mark.parametrize("purpose", ["actor", "writer"])
def test_official_gpt54_explicit_completion_limit_survives_json_retry(monkeypatch, purpose):
    real_mode(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_ACTOR_MODEL", "gpt-5.4-2026-03-05")
    monkeypatch.setenv("LLM_WRITER_MODEL", "gpt-5.4-2026-03-05")
    _, create = fake_client(monkeypatch)
    create.side_effect = [
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{"), finish_reason="stop")]),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'), finish_reason="stop")]),
    ]

    assert asyncio.run(llm.complete_json([], purpose=purpose, max_tokens=2048)) == {"ok": True}
    assert create.await_count == 2
    for call in create.await_args_list:
        assert call.kwargs["max_completion_tokens"] == 2048
        assert call.kwargs["reasoning_effort"] == ("none" if purpose == "actor" else "high")
        assert "max_tokens" not in call.kwargs and "extra_body" not in call.kwargs


@pytest.mark.parametrize("base_url,model", [
    ("https://model.example.test/v1", "gpt-5.4-2026-03-05"),
    ("https://api.openai.com.example.test/v1", "gpt-5.4"),
    ("https://api.openai.com/v1", "gpt-5.4-pro"),
    ("https://api.openai.com/v1", "gpt-5.4-mini"),
    ("https://api.openai.com/v1", "gpt-4o"),
])
def test_gpt54_adaptation_is_scoped_to_verified_official_models(monkeypatch, base_url, model):
    real_mode(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", base_url)
    monkeypatch.setenv("LLM_ACTOR_MODEL", model)
    _, create = fake_client(monkeypatch)
    asyncio.run(llm.complete_json([]))
    assert create.await_args.kwargs["max_tokens"] == 1024
    assert "reasoning_effort" not in create.await_args.kwargs
    assert "max_completion_tokens" not in create.await_args.kwargs


def test_writer_specific_settings_can_work_without_actor_settings(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_BASE_URL", "invalid-unused-actor-url")
    monkeypatch.setenv("LLM_WRITER_BASE_URL", "https://writer.example.test/v1")
    monkeypatch.setenv("LLM_WRITER_API_KEY", "writer-test-key")
    monkeypatch.setenv("LLM_WRITER_MODEL", "writer-model")
    constructor, create = fake_client(monkeypatch)
    asyncio.run(llm.complete_json([], purpose="writer"))
    assert constructor.call_args.kwargs["api_key"] == "writer-test-key"
    assert create.await_args.kwargs["model"] == "writer-model"


def test_actor_ignores_writer_overrides(monkeypatch):
    real_mode(monkeypatch)
    monkeypatch.setenv("LLM_WRITER_BASE_URL", "invalid-unused-writer-url")
    monkeypatch.setenv("LLM_WRITER_API_KEY", "writer-test-key")
    constructor, create = fake_client(monkeypatch)
    asyncio.run(llm.complete_json([]))
    assert constructor.call_args.kwargs["api_key"] == "test-key-not-a-real-secret"
    assert create.await_args.kwargs["model"] == "test-actor"


@pytest.mark.parametrize("blank_overrides", [False, True])
def test_writer_falls_back_to_common_address_and_key_independently(monkeypatch, blank_overrides):
    real_mode(monkeypatch)
    if blank_overrides:
        monkeypatch.setenv("LLM_WRITER_BASE_URL", " ")
        monkeypatch.setenv("LLM_WRITER_API_KEY", " ")
    constructor, create = fake_client(monkeypatch)
    asyncio.run(llm.complete_json([], purpose="writer"))
    assert constructor.call_args.kwargs["base_url"] == "https://model.example.test/v1"
    assert constructor.call_args.kwargs["api_key"] == "test-key-not-a-real-secret"
    assert create.await_args.kwargs["model"] == "test-writer"


@pytest.mark.parametrize("override", ["address", "key"])
def test_writer_can_override_only_one_connection_setting(monkeypatch, override):
    real_mode(monkeypatch)
    if override == "address":
        monkeypatch.setenv("LLM_WRITER_BASE_URL", "https://writer.example.test/v1")
    else:
        monkeypatch.setenv("LLM_WRITER_API_KEY", "writer-test-key")
    constructor, _ = fake_client(monkeypatch)
    asyncio.run(llm.complete_json([], purpose="writer"))
    kwargs = constructor.call_args.kwargs
    assert kwargs["base_url"] == (
        "https://writer.example.test/v1" if override == "address" else "https://model.example.test/v1"
    )
    assert kwargs["api_key"] == (
        "writer-test-key" if override == "key" else "test-key-not-a-real-secret"
    )


@pytest.mark.parametrize("purpose", ["actor", "writer"])
def test_openai_requires_an_explicit_model_instead_of_deepseek_default(monkeypatch, purpose):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "shared-test-key")
    constructor, _ = fake_client(monkeypatch)
    name = "LLM_ACTOR_MODEL" if purpose == "actor" else "LLM_WRITER_MODEL"
    with pytest.raises(llm.LLMError, match=name) as error:
        asyncio.run(llm.complete_json([], purpose=purpose))
    assert error.value.status_code == 503
    constructor.assert_not_called()


def test_writer_provider_override_requires_writer_model_even_with_legacy_actor(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_API_KEY", "shared-test-key")
    monkeypatch.setenv("LLM_MODEL", "actor-model")
    monkeypatch.setenv("LLM_WRITER_BASE_URL", "https://api.openai.com/v1")
    with pytest.raises(llm.LLMError, match="LLM_WRITER_MODEL"):
        asyncio.run(llm.complete_json([], purpose="writer"))


def test_writer_reports_missing_shared_or_specific_key(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    with pytest.raises(llm.LLMError, match="LLM_WRITER_API_KEY 或 LLM_API_KEY"):
        asyncio.run(llm.complete_json([], purpose="writer"))


@pytest.mark.parametrize(
    "base_url",
    ["https://api.openai.com/v1", "https://api.deepseek.com.evil.test/v1", "https://fakeapi.deepseek.com/v1"],
)
@pytest.mark.parametrize("purpose", ["actor", "writer"])
def test_non_deepseek_providers_never_receive_thinking_parameters(monkeypatch, base_url, purpose):
    real_mode(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", base_url)
    _, create = fake_client(monkeypatch)
    asyncio.run(llm.complete_json([], purpose=purpose))
    assert "extra_body" not in create.await_args.kwargs
    assert "temperature" not in create.await_args.kwargs


@pytest.mark.parametrize(
    "base_url",
    ["file:///tmp/model", "model.example.test/v1", "http://[", "https://model.test:invalid", "https://bad host/v1", "https://api.deepseek.com@evil.test/v1"],
)
def test_invalid_endpoint_is_a_configuration_error(monkeypatch, base_url):
    real_mode(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", base_url)
    with pytest.raises(llm.LLMError, match="LLM_BASE_URL") as error:
        asyncio.run(llm.complete_json([]))
    assert error.value.status_code == 503


def test_writer_invalid_endpoint_reports_the_writer_setting(monkeypatch):
    real_mode(monkeypatch)
    monkeypatch.setenv("LLM_WRITER_BASE_URL", "invalid-writer-url")
    with pytest.raises(llm.LLMError, match="LLM_WRITER_BASE_URL"):
        asyncio.run(llm.complete_json([], purpose="writer"))


@pytest.mark.parametrize("purpose", ["actor", "writer"])
def test_explicit_token_limit_replaces_the_purpose_default(monkeypatch, purpose):
    real_mode(monkeypatch)
    _, create = fake_client(monkeypatch)
    asyncio.run(llm.complete_json([], purpose=purpose, max_tokens=2048))
    assert create.await_args.kwargs["max_tokens"] == 2048


def test_real_adapter_keeps_client_limits_and_legacy_call_signature(monkeypatch):
    real_mode(monkeypatch)
    constructor, create = fake_client(monkeypatch)
    messages = [{"role": "user", "content": "请用 JSON 回复"}]
    assert asyncio.run(llm.complete_json(messages)) == {"reply": "你好"}
    constructor.assert_called_once_with(
        api_key="test-key-not-a-real-secret",
        base_url="https://model.example.test/v1", timeout=30.0, max_retries=1,
    )
    create.assert_awaited_once_with(
        model="test-actor", messages=messages, response_format={"type": "json_object"}, max_tokens=1024,
    )


@pytest.mark.parametrize("content", ["not JSON", "[]", "null", "", "  \n  ", None, '{"value": NaN}', '{"value": Infinity}'])
def test_invalid_or_non_object_model_output_is_rejected(monkeypatch, content):
    real_mode(monkeypatch)
    _, create = fake_client(monkeypatch, content)
    with pytest.raises(llm.LLMError) as error:
        asyncio.run(llm.complete_json([]))
    assert error.value.status_code == 502
    assert type(error.value) is llm.LLMError
    assert create.await_count == 2


@pytest.mark.parametrize("first_content", ['{"bad": "private-invalid-secret-sentinel}', "", " \n ", None, "[]", "null"])
def test_one_format_repair_can_recover_without_reinjecting_invalid_content(monkeypatch, first_content):
    real_mode(monkeypatch)
    constructor, create = fake_client(monkeypatch)
    def completion(content):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")])
    create.side_effect = [completion(first_content), completion('{"reply": "已修复"}')]
    messages = [{"role": "system", "content": "请按规定用 JSON 回答。"}, {"role": "user", "content": "继续调查"}]
    original = json.loads(json.dumps(messages, ensure_ascii=False))
    result = asyncio.run(llm.complete_json(messages))
    assert result == {"reply": "已修复"}
    assert constructor.call_count == 1 and create.await_count == 2
    first, repaired = [call.kwargs for call in create.await_args_list]
    assert first["messages"] == original
    assert repaired["messages"][:-1] == original
    assert repaired["messages"][-1] == {"role": "user", "content": llm._JSON_REPAIR_INSTRUCTION}
    assert "private-invalid-secret-sentinel" not in json.dumps(repaired["messages"])
    assert all(message["role"] != "assistant" for message in repaired["messages"])
    assert {key: value for key, value in first.items() if key != "messages"} == {
        key: value for key, value in repaired.items() if key != "messages"}
    assert messages == original


def test_two_invalid_replies_stop_after_one_format_repair(monkeypatch):
    real_mode(monkeypatch)
    _, create = fake_client(monkeypatch)
    def completion(content):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")])
    create.side_effect = [completion("private-first-invalid-sentinel"), completion("private-second-invalid-sentinel")]
    with pytest.raises(llm.LLMError, match="有效的 JSON") as error:
        asyncio.run(llm.complete_json([{"role": "user", "content": "请返回 JSON"}]))
    assert create.await_count == 2 and type(error.value) is llm.LLMError
    assert "private-" not in str(error.value)


def test_empty_choices_is_rejected(monkeypatch):
    real_mode(monkeypatch)
    _, create = fake_client(monkeypatch, choices=[])
    with pytest.raises(llm.LLMError, match="没有返回"):
        asyncio.run(llm.complete_json([]))
    assert create.await_count == 1


def test_truncated_output_is_rejected_even_if_it_parses(monkeypatch):
    real_mode(monkeypatch)
    _, create = fake_client(monkeypatch, choices=[
        SimpleNamespace(message=SimpleNamespace(content='{"reply": "部分"}'), finish_reason="length")
    ])
    with pytest.raises(llm.LLMError, match="长度限制"):
        asyncio.run(llm.complete_json([]))
    assert create.await_count == 1


@pytest.mark.parametrize("kind, status", [("timeout", 504), ("connection", 502), ("api", 502)])
def test_sdk_failures_are_mapped_without_exposing_provider_content(monkeypatch, kind, status):
    real_mode(monkeypatch)
    request = httpx.Request("POST", "https://model.example.test/v1/chat/completions")
    if kind == "timeout":
        provider_error = APITimeoutError(request=request)
    elif kind == "connection":
        provider_error = APIConnectionError(message="provider-private-detail", request=request)
    else:
        provider_error = APIError("provider-private-detail", request=request, body={"internal": "hidden"})
    _, create = fake_client(monkeypatch, error=provider_error)
    with pytest.raises(llm.LLMError) as error:
        asyncio.run(llm.complete_json([]))
    assert error.value.status_code == status
    assert create.await_count == 1
    assert "provider-private-detail" not in str(error.value)
    assert "test-key-not-a-real-secret" not in str(error.value)
