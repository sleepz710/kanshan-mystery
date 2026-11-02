"""用技术样本检查前端依赖的 v2 响应结构。"""

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from test_engine_v2 import technical_story, write_story


@pytest.fixture
def client(tmp_path):
    official = tmp_path / "official"
    generated = tmp_path / "generated"
    write_story(official, technical_story())
    generated_story = technical_story("generated-protocol")
    generated_story["source"] = "generated"
    write_story(generated, generated_story)
    with TestClient(create_app(stories_dir=official, generated_stories_dir=generated)) as client:
        yield client


def start(client):
    response = client.post("/api/games", json={"story_id": "protocol"})
    assert response.status_code == 201, response.text
    return response.json()["game_id"]


def test_exposed_and_confront_events_have_distinct_public_shapes(client):
    game = start(client)
    for _ in range(2):
        assert client.post(f"/api/games/{game}/talk", json={"character_id": "b", "text": "材料"}).status_code == 200
    response = client.post(f"/api/games/{game}/show", json={"character_id": "a", "clue_id": "x"})
    assert response.status_code == 200, response.text
    events = response.json()["events"]
    assert [e["type"] for e in events] == ["exposed", "confront", "exposed"]
    for event in events:
        if event["type"] == "exposed":
            assert set(event) == {"type", "character", "lie", "text"}
        else:
            assert set(event) == {"type", "text", "lines"}
    assert "仅揭晓接口可返回的完整真相" not in response.text


def test_bad_ending_keeps_game_open_then_explicit_reveal_closes_it(client):
    game = start(client)
    ending = client.post(f"/api/games/{game}/accuse", json={"answers": {"q1": "b", "q2": "b"}})
    assert ending.status_code == 200, ending.text
    assert ending.json()["ending"]["retry"] is True
    assert ending.json()["rating"] == "C"
    assert set(ending.json()) == {"score", "total", "results", "ending", "rating"}
    assert client.post(f"/api/games/{game}/talk", json={"character_id": "a", "text": "继续"}).status_code == 200
    reveal = client.post(f"/api/games/{game}/reveal")
    assert reveal.status_code == 200
    assert set(reveal.json()) == {"truth", "lessons"}
    assert client.post(f"/api/games/{game}/talk", json={"character_id": "a", "text": "继续"}).status_code == 409


def test_generated_story_can_be_listed_and_started_without_exposing_truth(client):
    stories = client.get("/api/stories")
    assert stories.status_code == 200
    assert {s["source"] for s in stories.json()} == {"official", "generated"}
    assert "仅揭晓接口可返回的完整真相" not in stories.text
    response = client.post("/api/games", json={"story_id": "generated-protocol"})
    assert response.status_code == 201
    assert response.json()["kanshan"]["asks_left"] == 5
    assert "仅揭晓接口可返回的完整真相" not in response.text
