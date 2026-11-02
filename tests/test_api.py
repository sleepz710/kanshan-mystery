"""使用真实剧本验证前端可以依赖的四个 HTTP 接口。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import agents
from backend.app import create_app
from backend.llm import LLMError


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")
    with TestClient(create_app()) as test_client:
        yield test_client


def start_game(client):
    response = client.post("/api/games", json={"story_id": "lost-tuition"})
    assert response.status_code == 201, response.text
    return response.json()


def test_creation_exposes_only_player_information(client):
    created = start_game(client)
    assert len(created["characters"]) == 3
    assert len(created["questions"]) == 4
    assert all(set(c) == {"id", "name", "avatar", "profile"} for c in created["characters"])
    assert all(set(q) == {"id", "text", "options"} for q in created["questions"])
    assert set(created) == {"game_id", "title", "intro", "characters", "questions"}


def test_real_story_roundtrip_with_mock_model(client):
    game_id = start_game(client)["game_id"]
    collected = {}

    def turn(action, **body):
        response = client.post(f"/api/games/{game_id}/{action}", json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert set(result) == {"reply", "new_clues", "events", "hint", "trust"}
        for clue in result["new_clues"]:
            assert set(clue) == {"id", "title", "content"}
            assert clue["id"] not in collected
            collected[clue["id"]] = clue
        return result

    for _ in range(3):
        turn("talk", character_id="xiaolin", text="请说说兼职的经过和付款情况。")
    assert {"c1", "c2", "c3"} <= collected.keys()

    turn("show", character_id="zhou", clue_id="c2")
    turn("talk", character_id="zhou", text="还有什么材料？")
    assert {"c4", "c7"} <= collected.keys()

    turn("talk", character_id="akai", text="你是怎么接触这个群的？")
    turn("talk", character_id="akai", text="可以把聊天记录给我看看吗？")
    assert "c5" in collected
    confrontation = turn("show", character_id="xiaolin", clue_id="c5")
    assert len(confrontation["events"]) == 1
    assert {line["speaker"] for line in confrontation["events"][0]["lines"]} == {"xiaolin", "akai"}
    assert {"c6"} <= collected.keys()
    repeated = turn("show", character_id="xiaolin", clue_id="c5")
    assert repeated["events"] == []
    assert len(collected) == 7

    ending = client.post(
        f"/api/games/{game_id}/accuse",
        json={"answers": {
            "q1": "刷单返利诈骗", "q2": "周明", "q3": "阿凯", "q4": "刷单群聊天记录"
        }},
    )
    assert ending.status_code == 200, ending.text
    assert ending.json()["score"] == ending.json()["total"]
    assert all(ending.json()["results"].values())
    assert len(ending.json()["lessons"]) == 3
    assert client.post(
        f"/api/games/{game_id}/talk", json={"character_id": "xiaolin", "text": "继续"}
    ).status_code == 409


@pytest.mark.parametrize("body", [
    {"story_id": "../SPEC"}, {"story_id": ""}, {"story_id": "lost-tuition", "truth": True}
])
def test_bad_creation_input_is_rejected(client, body):
    assert client.post("/api/games", json=body).status_code == 422


@pytest.mark.parametrize("text", ["", "   ", "x" * 4001])
def test_empty_or_oversize_message_is_rejected(client, text):
    game_id = start_game(client)["game_id"]
    assert client.post(
        f"/api/games/{game_id}/talk", json={"character_id": "xiaolin", "text": text}
    ).status_code == 422


def test_unavailable_resources_and_unowned_clue(client):
    game_id = start_game(client)["game_id"]
    assert client.post("/api/games", json={"story_id": "not-a-story"}).status_code == 404
    assert client.post(
        "/api/games/missing/talk", json={"character_id": "xiaolin", "text": "你好"}
    ).status_code == 404
    assert client.post(
        f"/api/games/{game_id}/talk", json={"character_id": "missing", "text": "你好"}
    ).status_code == 404
    response = client.post(
        f"/api/games/{game_id}/show", json={"character_id": "zhou", "clue_id": "c2"}
    )
    assert response.status_code == 409


def test_invalid_answers_do_not_finish_game(client):
    game_id = start_game(client)["game_id"]
    assert client.post(
        f"/api/games/{game_id}/accuse", json={"answers": {"q1": "伪造选项"}}
    ).status_code == 422
    assert client.post(
        f"/api/games/{game_id}/talk", json={"character_id": "xiaolin", "text": "你好"}
    ).status_code == 200


def test_model_error_is_reported_without_partial_progress(client, monkeypatch):
    game_id = start_game(client)["game_id"]

    async def unavailable(context, *, retry_leaked=None):
        raise LLMError("模型服务暂时不可用，请稍后重试。")

    with monkeypatch.context() as patch:
        patch.setattr(agents, "reply", unavailable)
        response = client.post(
            f"/api/games/{game_id}/talk", json={"character_id": "xiaolin", "text": "你好"}
        )
        assert response.status_code == 502
        assert response.json() == {"detail": "模型服务暂时不可用，请稍后重试。"}

    response = client.post(
        f"/api/games/{game_id}/talk", json={"character_id": "xiaolin", "text": "你好"}
    )
    assert response.status_code == 200
    assert response.json()["trust"]["xiaolin"] == 1
    assert response.json()["new_clues"][0]["id"] == "c1"


def test_backend_root_and_api_docs(client):
    assert client.get("/").status_code == 200
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) >= {
        "/api/games", "/api/games/{game_id}/talk", "/api/games/{game_id}/show",
        "/api/games/{game_id}/accuse",
    }
    for path in ["/.env", "/SPEC.md", "/stories/lost-tuition.yaml"]:
        assert client.get(path).status_code == 404


def test_frontend_is_served_without_hiding_api(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")
    (tmp_path / "index.html").write_text("<h1>看山谜案馆</h1>", encoding="utf-8")
    with TestClient(create_app(frontend_dir=tmp_path)) as test_client:
        assert "看山谜案馆" in test_client.get("/").text
        assert test_client.get("/docs").status_code == 200
        assert test_client.post("/api/games", json={"story_id": "lost-tuition"}).status_code == 201
        assert test_client.get("/../SPEC.md").status_code == 404
