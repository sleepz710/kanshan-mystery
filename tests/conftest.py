"""自动测试隔离本地密钥，真实模型验证通过独立命令执行。"""

import pytest

from backend import llm


@pytest.fixture(autouse=True)
def offline_models(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "_ENV_FILE", tmp_path / "missing.env")
    for name in (
        "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_ACTOR_MODEL",
        "LLM_WRITER_MODEL", "LLM_WRITER_BASE_URL", "LLM_WRITER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_MOCK", "1")

    def unexpected_model_client(*args, **kwargs):
        pytest.fail("自动测试不应连接真实模型，请提供模拟客户端。")

    monkeypatch.setattr(llm, "AsyncOpenAI", unexpected_model_client)
