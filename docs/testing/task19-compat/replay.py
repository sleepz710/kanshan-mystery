"""用已验收角色输出回放三案 HTTP 路线，检查指定源码的兼容性。"""

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch


SAMPLES = Path(__file__).resolve().parents[1] / "task19-demo"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def permissions(engine, state):
    return {
        character["id"]: [fact["id"] for fact in engine._context(state, character["id"], "")["facts"]]
        for character in state.story["characters"]
    }


async def replay_case(entry, application):
    import httpx
    import yaml
    from backend import agents
    from backend.engine import GameEngine
    from backend.studio.check import check_playability, check_structure

    original_path = SAMPLES / entry["original_file"]
    revised_path = SAMPLES / entry["revised_file"]
    assert sha256(original_path) == entry["original_sha256"]
    assert sha256(revised_path) == entry["revised_sha256"]
    assert yaml.safe_load(original_path.read_text(encoding="utf-8"))["checked"] is False
    story = yaml.safe_load(revised_path.read_text(encoding="utf-8"))
    assert story["checked"] is True
    structure = check_structure(story)
    playability = check_playability(story)
    assert structure == {"ok": True, "problems": []}
    assert playability == []
    previous_path = SAMPLES / f"{entry['name']}-playthrough.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    assert previous["story_sha256"] == entry["revised_sha256"]
    tested_bytes = revised_path.read_bytes().replace(b"checked: true", b"checked: false")
    assert hashlib.sha256(tested_bytes).hexdigest() == previous["tested_story_sha256"]
    assert previous["accepted"] is True
    assert previous["solvability"] == {"ok": True, "problems": []}

    engine = application.state.engine
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://replay") as client:
        response = await client.get("/api/stories")
        assert response.status_code == 200
        listed = next(item for item in response.json() if item["id"] == entry["revised_id"])
        assert listed["checked"] is True
        response = await client.post("/api/games", json={"story_id": entry["revised_id"]})
        assert response.status_code == 201
        game = response.json()
        assert game["checked"] is True
        game_id = game["game_id"]
        initial_permissions = permissions(engine, engine.games[game_id])
        assert initial_permissions == previous["initial_permissions"]
        turns = []
        for index, turn in enumerate(previous["turns"]):
            expected = turn["result"]
            cid = turn["character_id"]
            state = engine.games[game_id]
            exposed_count = sum(
                event["type"] == "exposed" and event["character"] == cid
                for event in expected["events"]
            )
            talk_count = state.talk_counts[cid] + (turn["action"] == "talk")
            compatible_candidates = []
            for delta, fallback in ((0, False), (1, False), (-1, False), (0, True)):
                trust = min(3, max(0, min(3, state.trust[cid] + delta)) + exposed_count)
                if fallback:
                    trust = state.trust[cid]
                elif talk_count >= 4:
                    trust = max(1, trust)
                if trust == expected["trust"][cid]:
                    compatible_candidates.append((delta, fallback))
            assert compatible_candidates, (entry["name"], index, "trust transition")
            delta, fallback = compatible_candidates[0]
            actor_context = {}

            async def reply(context, retry_leaked=None):
                actor_context.update(deepcopy(context))
                allowed = {clue["id"] for clue in context["available_clues"]}
                return {
                    "reply": expected["reply"],
                    "reveal": [clue["id"] for clue in expected["new_clues"] if clue["id"] in allowed],
                    "trust_delta": delta,
                    "_fallback": fallback,
                }

            async def check_reply(context, candidate):
                return {"ok": True, "leaked": [], "contradiction": ""}

            async def confront(contexts, event):
                matching = next(item for item in expected["events"]
                                if item["type"] == "confront"
                                and {line["speaker"] for line in item["lines"]} == set(event["confront"]))
                return deepcopy(matching["lines"])

            body = {"character_id": cid}
            body["text" if turn["action"] == "talk" else "clue_id"] = turn.get("text", turn.get("clue_id"))
            with patch.object(agents, "reply", reply), patch.object(agents, "check_reply", check_reply), patch.object(agents, "confront", confront):
                response = await client.post(f"/api/games/{game_id}/{turn['action']}", json=body)
            assert response.status_code == 200, (entry["name"], index, response.text)
            assert response.json() == expected, (entry["name"], index, "changed public result")
            turns.append({
                "index": index + 1, "action": turn["action"], "character_id": cid,
                "clue_id": turn.get("clue_id"), "http_status": response.status_code,
                "matches_recorded_result": True,
                "replayed_fallback": fallback,
                "allowed_fact_ids": [fact["id"] for fact in actor_context["facts"]],
                "exposed_lie_ids": [lie["id"] for lie in actor_context["exposed_lies"]],
                "new_clue_ids": [clue["id"] for clue in expected["new_clues"]],
                "event_types": [event["type"] for event in expected["events"]],
            })
        state = engine.games[game_id]
        for field in ("acquired_clues", "exposed_lies", "triggered_events"):
            assert sorted(getattr(state, field)) == previous[field]
        final_permissions = permissions(engine, state)
        final_answers = previous["public_transcript_answers"]["answers"]
        response = await client.post(f"/api/games/{game_id}/accuse", json={"answers": final_answers})
        assert response.status_code == 200
        assert response.json() == previous["actual_accusation"]["result"]
        correct_result = response.json()
        wrong_results = []
        questions = story["ending"]["questions"]
        wrong_answers = {question["id"]: next(option for option in question["options"] if option != question["answer"])
                         for question in questions}
        one_wrong = {**final_answers, questions[0]["id"]: wrong_answers[questions[0]["id"]]}
        for answers in (one_wrong, wrong_answers):
            response = await client.post("/api/games", json={"story_id": entry["revised_id"]})
            assert response.status_code == 201
            response = await client.post(f"/api/games/{response.json()['game_id']}/accuse", json={"answers": answers})
            assert response.status_code == 200 and response.json()["ending"]["retry"] is True
            wrong_results.append(response.json())

    complete_count = 0
    combinations = 0
    for options in itertools.product(*(question["options"] for question in questions)):
        combinations += 1
        answers = dict(zip((question["id"] for question in questions), options))
        results = {question["id"]: answers[question["id"]] == question["answer"] for question in questions}
        ending = next(ending for ending in story["ending"]["endings"] if GameEngine._ending_matches(ending, answers, results))
        if not ending["retry"]:
            complete_count += 1
            assert all(results.values())
    assert complete_count == 1
    return {
        "name": entry["name"], "title": entry["title"], "checked": story["checked"],
        "original_sha256": sha256(original_path), "revised_sha256": sha256(revised_path),
        "prior_real_acceptance_sha256": sha256(previous_path), "structure": structure, "playability": playability,
        "prior_tested_story_sha256": previous["tested_story_sha256"],
        "initial_permissions": initial_permissions, "final_permissions": final_permissions,
        "turns": turns, "acquired_clues": sorted(state.acquired_clues),
        "exposed_lies": sorted(state.exposed_lies), "triggered_events": sorted(state.triggered_events),
        "accusation": correct_result, "wrong_accusations": wrong_results,
        "ending_enumeration": {"combinations": combinations, "complete_combinations": complete_count, "wrong_complete": 0},
        "compatible": True,
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    sys.path.insert(0, str(source_root))
    os.environ["LLM_MOCK"] = "1"
    with tempfile.TemporaryDirectory(prefix="kanshan-demo-compat-") as temp:
        os.environ["KANSHAN_DATA_DIR"] = temp
        os.environ.pop("KANSHAN_DESKTOP", None)
        from backend import llm
        from backend.app import create_app
        from backend.studio import check

        def unexpected_client(*args, **kwargs):
            raise AssertionError("兼容回放禁止真实模型调用")

        application = create_app(stories_dir=Path(temp) / "official", generated_stories_dir=SAMPLES / "revised")
        entries = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))
        with patch.object(llm, "AsyncOpenAI", unexpected_client), patch.object(check, "AsyncOpenAI", unexpected_client):
            cases = [await replay_case(entry, application) for entry in entries]
    runtime_paths = (
        Path("backend/engine.py"), Path("backend/agents.py"), Path("backend/app.py"),
        Path("backend/llm.py"), Path("backend/studio/check.py"), Path("backend/studio/service.py"),
    )
    runtime_diff = subprocess.check_output(
        ["git", "diff", "HEAD", "--name-only", "--", *(path.as_posix() for path in runtime_paths)],
        cwd=source_root, text=True,
    )
    result = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "offline HTTP replay of previously accepted actor and confrontation outputs",
        "real_model_calls": 0,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source_root, text=True).strip(),
        "source_runtime_dirty": bool(runtime_diff.strip()),
        "source_sha256": {path.as_posix(): sha256(source_root / path) for path in runtime_paths},
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_commit": result["source_commit"], "real_model_calls": 0,
                      "compatible": [case["name"] for case in cases]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
