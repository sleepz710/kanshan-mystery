"""分享令牌、重启后预览、跨案件隔离与对局进度快照。"""

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.studio.service import StudioService
from backend.studio.test_studio import client, finish, mock_mode, new_chat


def share_job(client):
    chat = new_chat(client, "share")
    response = client.post(f"/api/studio/chats/{chat}/messages", data={"text": "生成一个办公室谜案"})
    job_id = response.json()["job"]["id"]
    finish(client)
    job = client.get(f"/api/studio/jobs/{job_id}").json()
    assert job["status"] == "done" and job["owner_token"]
    return job


def test_owner_only_preview_and_safe_share_url(client):
    job = share_job(client)
    url = f"/api/stories/{job['story_id']}/owner"
    assert job["share_url"] == f"/?story={job['story_id']}"
    assert job["owner_token"] not in job["share_url"]
    assert client.get(url).status_code == 403
    assert client.get(url, headers={"X-Owner-Token": "wrong"}).status_code == 403
    response = client.get(url, headers={"X-Owner-Token": job["owner_token"]})
    assert response.status_code == 200
    assert response.json()["story"]["ending"]["truth"]
    assert response.json()["games"] == []
    assert job["owner_token"] not in response.text
    raw = (client.app.state.studio.stories_dir / ".owners" / f"{job['story_id']}.json").read_text(encoding="utf-8")
    assert job["owner_token"] not in raw
    assert len(json.loads(raw)["token_hash"]) == 64


def test_cross_story_tokens_are_rejected(client):
    first, second = share_job(client), share_job(client)
    response = client.get(f"/api/stories/{second['story_id']}/owner", headers={"X-Owner-Token": first["owner_token"]})
    assert response.status_code == 403


def test_generated_story_can_be_played_and_owner_sees_real_progress(client):
    job = share_job(client)
    created = client.post("/api/games", json={"story_id": job["story_id"]})
    assert created.status_code == 201, created.text
    game_id = created.json()["game_id"]
    assert job["story_id"] in {s["id"] for s in client.get("/api/stories").json()}
    collected = set()
    for _ in range(4):
        response = client.post(f"/api/games/{game_id}/talk", json={"character_id": "wang", "text": "你有什么线索？"})
        assert response.status_code == 200, response.text
        collected.update(c["id"] for c in response.json()["new_clues"])
    assert "c1" in collected
    for character, clue in [("lin", "c1"), ("chen", "c2")]:
        response = client.post(f"/api/games/{game_id}/show", json={"character_id": character, "clue_id": clue})
        assert response.status_code == 200, response.text
    ended = client.post(f"/api/games/{game_id}/accuse", json={"answers": {"q1": "林青", "q2": "陈明", "q3": "王平"}})
    assert ended.status_code == 200 and ended.json()["ending"]["id"] == "truth"
    progress = client.get(f"/api/stories/{job['story_id']}/owner", headers={"X-Owner-Token": job["owner_token"]}).json()["games"]
    assert progress[0]["turns"] == 6
    assert progress[0]["exposed"] == ["l1", "l2"]
    assert progress[0]["ending"] == "truth"


def test_play_story_has_no_owner_access(client):
    chat = new_chat(client)
    result = client.post(f"/api/studio/chats/{chat}/messages", data={"text": "直接开始一个新案件"}).json()
    finish(client)
    job = client.get(f"/api/studio/jobs/{result['job']['id']}").json()
    assert job["owner_token"] is None and "share_url" not in job
    assert client.get(f"/api/stories/{job['story_id']}/owner", headers={"X-Owner-Token": "guess"}).status_code == 404


def test_owner_survives_service_restart(client):
    job = share_job(client)
    app = create_app()
    app.state.studio = StudioService(client.app.state.studio.stories_dir)
    with TestClient(app) as restarted:
        response = restarted.get(f"/api/stories/{job['story_id']}/owner", headers={"X-Owner-Token": job["owner_token"]})
        assert response.status_code == 200
        assert response.json()["story"]["id"] == job["story_id"]


def test_progress_is_per_story_and_excludes_conversations(client):
    job = share_job(client)
    engine = client.app.state.engine
    engine.games["friend-one"] = SimpleNamespace(
        story={"id": job["story_id"]}, turns=7, histories={"lin": [{"role": "user", "content": "私有对话"}]},
        acquired_clues={"c2", "c1"}, exposed={"l1"}, ending={"id": "truth", "text": "秘密结局"})
    engine.games["unrelated"] = SimpleNamespace(story={"id": "lost-tuition"})
    response = client.get(f"/api/stories/{job['story_id']}/owner", headers={"X-Owner-Token": job["owner_token"]})
    assert response.json()["games"] == [{"game_id": "friend-one", "turns": 7, "clues": ["c1", "c2"], "exposed": ["l1"], "ending": "truth"}]
    assert "私有对话" not in response.text
    engine.games["friend-one"].turns = 8
    assert client.get(f"/api/stories/{job['story_id']}/owner", headers={"X-Owner-Token": job["owner_token"]}).json()["games"][0]["turns"] == 8


def test_legacy_engine_progress_uses_user_turns(client):
    job = share_job(client)
    engine = client.app.state.engine
    engine.games["legacy-game"] = SimpleNamespace(
        story={"id": job["story_id"]}, acquired_clues={"c1"},
        histories={"xiaolin": [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好"}]})
    response = client.get(f"/api/stories/{job['story_id']}/owner", headers={"X-Owner-Token": job["owner_token"]}).json()
    assert response["games"][0]["turns"] == 1
    assert response["games"][0]["exposed"] == []
