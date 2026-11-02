import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from openai import APIConnectionError, APIError, APITimeoutError

from backend import llm


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "_ENV_FILE", tmp_path / "missing.env")
    for key in ("LLM_MOCK", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        # 先登记环境恢复动作，dotenv 后续写入的变量也会在测试结束时清理。
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)


def real_mode(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_BASE_URL", "https://model.example.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-a-real-secret")
    monkeypatch.setenv("LLM_MODEL", "test-model")


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


def test_default_mock_never_constructs_client_and_returns_independent_data(monkeypatch):
    constructor = Mock(side_effect=AssertionError("模拟模式不应创建模型客户端"))
    monkeypatch.setattr(llm, "AsyncOpenAI", constructor)
    source = {"reply": "模拟", "reveal": ["c1"]}
    result = asyncio.run(llm.complete_json([], mock_response=source))
    result["reveal"].append("c2")
    assert llm.is_mock_mode() is True
    assert source["reveal"] == ["c1"]
    constructor.assert_not_called()


def test_mock_requires_an_explicit_json_object():
    with pytest.raises(llm.LLMError, match="mock_response") as error:
        asyncio.run(llm.complete_json([]))
    assert error.value.status_code == 503


def test_env_file_is_utf8_and_does_not_override_process_environment(monkeypatch, tmp_path):
    env_file = tmp_path / "config.env"
    env_file.write_text("# 中文配置\nLLM_MOCK=0\nLLM_MODEL=来自文件\n", encoding="utf-8")
    monkeypatch.setattr(llm, "_ENV_FILE", env_file)
    monkeypatch.setenv("LLM_MOCK", "1")
    monkeypatch.setenv("LLM_MODEL", "process-model")
    assert llm.is_mock_mode() is True
    import os
    assert os.environ["LLM_MODEL"] == "process-model"


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


def test_real_mode_requires_configuration_and_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    constructor = Mock(side_effect=AssertionError("缺配置时不应创建客户端"))
    monkeypatch.setattr(llm, "AsyncOpenAI", constructor)
    with pytest.raises(llm.LLMError, match="LLM_BASE_URL.*LLM_API_KEY.*LLM_MODEL") as error:
        asyncio.run(llm.complete_json([], mock_response={"reply": "不应使用"}))
    assert error.value.status_code == 503
    constructor.assert_not_called()


@pytest.mark.parametrize("missing", ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"])
def test_each_real_setting_is_required(monkeypatch, missing):
    real_mode(monkeypatch)
    monkeypatch.delenv(missing)
    with pytest.raises(llm.LLMError, match=missing):
        asyncio.run(llm.complete_json([]))


@pytest.mark.parametrize("base_url", ["file:///tmp/model", "model.example.test/v1", "http://["])
def test_invalid_endpoint_is_a_configuration_error(monkeypatch, base_url):
    real_mode(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", base_url)
    with pytest.raises(llm.LLMError, match="LLM_BASE_URL") as error:
        asyncio.run(llm.complete_json([]))
    assert error.value.status_code == 503


def test_real_adapter_passes_json_mode_and_explicit_client_limits(monkeypatch):
    real_mode(monkeypatch)
    constructor, create = fake_client(monkeypatch)
    messages = [{"role": "user", "content": "请用 JSON 回复"}]
    assert asyncio.run(llm.complete_json(messages)) == {"reply": "你好"}
    constructor.assert_called_once_with(
        api_key="test-key-not-a-real-secret",
        base_url="https://model.example.test/v1",
        timeout=30.0,
        max_retries=1,
    )
    create.assert_awaited_once_with(
        model="test-model", messages=messages, response_format={"type": "json_object"}
    )


@pytest.mark.parametrize("content", ["not JSON", "[]", "null", "", None, '{"value": NaN}', '{"value": Infinity}'])
def test_invalid_or_non_object_model_output_is_rejected(monkeypatch, content):
    real_mode(monkeypatch)
    fake_client(monkeypatch, content)
    with pytest.raises(llm.LLMError) as error:
        asyncio.run(llm.complete_json([]))
    assert error.value.status_code == 502


def test_empty_choices_is_rejected(monkeypatch):
    real_mode(monkeypatch)
    fake_client(monkeypatch, choices=[])
    with pytest.raises(llm.LLMError, match="没有返回"):
        asyncio.run(llm.complete_json([]))


def test_truncated_output_is_rejected_even_if_it_parses(monkeypatch):
    real_mode(monkeypatch)
    fake_client(monkeypatch, choices=[
        SimpleNamespace(message=SimpleNamespace(content='{"reply": "部分"}'), finish_reason="length")
    ])
    with pytest.raises(llm.LLMError, match="长度限制"):
        asyncio.run(llm.complete_json([]))


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
    fake_client(monkeypatch, error=provider_error)
    with pytest.raises(llm.LLMError) as error:
        asyncio.run(llm.complete_json([]))
    assert error.value.status_code == status
    assert "provider-private-detail" not in str(error.value)
    assert "test-key-not-a-real-secret" not in str(error.value)
