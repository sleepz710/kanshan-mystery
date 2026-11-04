"""桌面配置、跨端口存储和重启续局均用临时数据与模拟客户端验证。"""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from backend import llm
from backend.app import create_app
from desktop import settings as desktop_settings


@pytest.fixture
def desktop(monkeypatch):
    with TemporaryDirectory(prefix="kanshan-desktop-test-") as directory:
        root = Path(directory)
        monkeypatch.setenv("KANSHAN_DATA_DIR", directory)
        monkeypatch.setenv("KANSHAN_DESKTOP", "1")
        for name in ("LLM_MOCK", "LLM_API_KEY", "LLM_BASE_URL", "LLM_ACTOR_MODEL", "LLM_WRITER_MODEL", "LLM_MODEL", "LLM_WRITER_API_KEY", "LLM_WRITER_BASE_URL"):
            monkeypatch.setenv(name, "")
        with TestClient(create_app()) as client:
            yield root, client


def config(**extra):
    return {"provider": "deepseek", "api_key": "TEST-LOCAL-KEY-1234", "actor_model": "deepseek-flash", "writer_model": "deepseek-flash", **extra}


def test_web_mode_has_no_settings(monkeypatch):
    monkeypatch.delenv("KANSHAN_DESKTOP", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/api/settings").status_code == 404
        assert client.put("/api/settings", json=config()).status_code == 404
        assert '/js/window.js' not in client.get('/').text


@pytest.mark.parametrize("path", ["/", "/game.html", "/ending.html", "/studio/", "/share/", "/settings/"])
def test_desktop_window_controls_are_injected_on_every_page(desktop, path):
    _, client = desktop
    page = client.get(path)
    assert page.status_code == 200
    assert page.text.count('src="/js/window.js"') == 1
    assert page.text.count('href="/css/window.css"') == 1
    assert "document.documentElement.classList.add('desktop-window')" in page.text
    assert page.text.index('/js/window.js') < page.text.index('</head>')


def test_first_start_requires_settings_and_keeps_secrets_private(desktop):
    root, client = desktop
    assert client.get("/api/settings").json()["configured"] is False
    assert client.post("/api/games", json={"story_id": "lost-tuition"}).status_code == 503
    page = client.get("/settings/")
    assert page.status_code == 200 and "模型设置" in page.text
    saved = client.put("/api/settings", json=config())
    assert saved.status_code == 200 and saved.json()["configured"]
    assert saved.json()["key_suffix"] == "1234"
    assert "TEST-LOCAL-KEY" not in saved.text + client.get("/api/settings").text
    assert os.environ["LLM_API_KEY"] == config()["api_key"]
    assert json.loads((root / "config.json").read_text(encoding="utf-8"))["api_key"] == config()["api_key"]
    assert client.post("/api/games", json={"story_id": "lost-tuition"}).status_code == 201


def test_keep_key_and_change_provider_validation(desktop):
    root, client = desktop
    client.put("/api/settings", json=config())
    assert client.put("/api/settings", json=config(api_key="")).status_code == 200
    assert os.environ["LLM_API_KEY"] == config()["api_key"]
    assert client.put("/api/settings", json=config(provider="openai", api_key="")).status_code == 422
    assert client.put("/api/settings", json=config(provider="openai", actor_model="", writer_model="")).status_code == 422
    saved = client.put("/api/settings", json=config(provider="openai", api_key="TEST-OPENAI-5678", actor_model="test-actor", writer_model="test-writer"))
    assert saved.status_code == 200 and saved.json()["key_suffix"] == "5678"
    assert os.environ["LLM_BASE_URL"] == "https://api.openai.com/v1"
    assert os.environ["LLM_ACTOR_MODEL"] == "test-actor"


@pytest.mark.parametrize("candidate,token_field,reasoning", [
    (config(), "max_tokens", None),
    (config(provider="openai", actor_model="test-actor", writer_model="test-writer"), "max_tokens", None),
    (config(provider="openai", actor_model="gpt-5.4", writer_model="gpt-5.4"), "max_completion_tokens", "none"),
    (config(provider="openai", actor_model="gpt-5.4-2026-03-05", writer_model="gpt-5.4-2026-03-05"), "max_completion_tokens", "none"),
])
def test_connection_is_one_minimal_call_and_does_not_save(desktop, monkeypatch, candidate, token_field, reasoning):
    root, client = desktop
    complete = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))]))
    class FakeClient:
        chat = SimpleNamespace(completions=SimpleNamespace(create=complete))
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    received = []
    def fake_client(**kwargs):
        received.append(kwargs)
        return FakeClient()
    monkeypatch.setattr(desktop_settings, "AsyncOpenAI", fake_client)
    response = client.post("/api/settings/test", json=candidate)
    assert response.json()["ok"] and complete.await_count == 1
    assert received[0]["max_retries"] == 0
    assert complete.call_args.kwargs[token_field] == 8
    assert complete.call_args.kwargs.get("reasoning_effort") == reasoning
    if reasoning:
        assert "max_tokens" not in complete.call_args.kwargs
    assert not (root / "config.json").exists()


@pytest.mark.parametrize("models", [{}, {"actor_model": "test-actor"}, {"writer_model": "test-writer"}])
def test_openai_requires_both_explicit_model_names(desktop, models):
    _, client = desktop
    response = client.put("/api/settings", json={"provider": "openai", "api_key": "TEST-ONLY-KEY", **models})
    assert response.status_code == 422
    assert client.get("/api/settings").json()["configured"] is False


def test_storage_is_restored_before_page_scripts_and_survives_new_app(desktop):
    root, client = desktop
    values = {"kanshan:last": "technical-game", "kanshan:studio:chats": "[]", "kanshan:quote": "</script>"}
    assert client.put("/api/desktop/storage", json=values).status_code == 200
    page = client.get("/")
    assert page.text.index("const initial=") < page.text.index("js/home.js")
    assert "\\u003c/script>" in page.text
    assert page.headers["cache-control"] == "no-store"
    with TestClient(create_app()) as restarted:
        assert '"kanshan:last": "technical-game"' in restarted.get("/").text
        assert restarted.put("/api/desktop/storage", json={"outside": "x"}).status_code == 422


def test_games_recover_after_desktop_restart(desktop):
    root, client = desktop
    client.put("/api/settings", json=config())
    original = client.post("/api/games", json={"story_id": "lost-tuition"}).json()
    assert (root / "games.json").exists()
    with TestClient(create_app()) as restarted:
        assert original["game_id"] in restarted.app.state.engine.games
        assert restarted.app.state.desktop_settings.public()["configured"]
        assert restarted.app.state.engine.generated_stories_dir == root / "stories"


def test_foreign_origin_cannot_update_desktop_settings(desktop):
    _, client = desktop
    assert client.put("/api/settings", json=config(), headers={"Origin": "https://example.com"}).status_code == 403


@pytest.mark.parametrize("browser_args", [None, "--disable-features=ElasticOverscroll"])
def test_first_launch_resolves_directory_and_enables_autoplay(monkeypatch, tmp_path, browser_args):
    from desktop import main as desktop_main

    physical = tmp_path / "physical-profile" / "KanshanMystery"

    class RedirectedDirectory:
        def mkdir(self, **kwargs):
            physical.mkdir(**kwargs)

        def resolve(self):
            assert physical.exists(), "创建目录后才能解析 Windows 重定向的实际路径"
            return physical

    class StartupReached(Exception):
        pass

    def verify_startup(**kwargs):
        assert os.environ["KANSHAN_DATA_DIR"] == str(physical)
        assert kwargs["filename"] == physical / "logs" / "desktop.log"
        expected = ((browser_args + " ") if browser_args else "") + "--autoplay-policy=no-user-gesture-required"
        assert os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] == expected
        raise StartupReached

    monkeypatch.setenv("KANSHAN_DATA_DIR", str(tmp_path / "virtual-profile"))
    monkeypatch.setenv("KANSHAN_DESKTOP", "")
    monkeypatch.setenv("LLM_MOCK", "1")
    if browser_args is None:
        monkeypatch.delenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", raising=False)
    else:
        monkeypatch.setenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", browser_args)
    monkeypatch.setattr(desktop_main, "Path", lambda value: RedirectedDirectory())
    monkeypatch.setattr(desktop_main.logging, "basicConfig", verify_startup)
    with pytest.raises(StartupReached):
        desktop_main.main()
