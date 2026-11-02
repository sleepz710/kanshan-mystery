"""体验口令属于网络边界，验证页面和 API 都经过认证。"""

import pytest
from fastapi.testclient import TestClient

from deploy.gateway import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DEPLOY_USERNAME", "judge")
    monkeypatch.setenv("DEPLOY_PASSWORD", "local-test-password")
    monkeypatch.setenv("LLM_MOCK", "1")
    with TestClient(create_app()) as client:
        yield client


@pytest.mark.parametrize("path", ["/", "/docs", "/openapi.json", "/studio/", "/api/stories"])
def test_pages_require_password(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic ")


@pytest.mark.parametrize("authorization", ["Basic bad", "Bearer anything", "Basic ☃", ""])
def test_invalid_auth_cannot_start_game(client, authorization):
    response = client.post(
        "/api/games", headers={"Authorization": authorization.encode("utf-8")},
        json={"story_id": "lost-tuition"},
    )
    assert response.status_code == 401


def test_wrong_password(client):
    response = client.get("/", auth=("judge", "wrong-password"))
    assert response.status_code == 401


def test_password_opens_docs_and_game(client):
    auth = ("judge", "local-test-password")
    assert client.get("/docs", auth=auth).status_code == 200
    stories = client.get("/api/stories", auth=auth)
    assert stories.status_code == 200
    assert any(story["id"] == "lost-tuition" for story in stories.json())
    response = client.post("/api/games", auth=auth, json={"story_id": "lost-tuition"})
    assert response.status_code == 201
    assert response.json()["characters"]
    assert response.json()["questions"]
    assert response.json()["kanshan"]["greeting"]
    assert response.json()["kanshan"]["asks_left"] == 5


@pytest.mark.parametrize("username,password", [("", "long-test-password"), ("bad:user", "long-test-password"), ("judge", "short")])
def test_invalid_config_fails_at_start(monkeypatch, username, password):
    monkeypatch.setenv("DEPLOY_USERNAME", username)
    monkeypatch.setenv("DEPLOY_PASSWORD", password)
    with pytest.raises(RuntimeError, match="DEPLOY_USERNAME"):
        create_app()
