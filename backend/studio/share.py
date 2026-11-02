"""出题人的剧本与进度，访问权限由不可猜测的 owner_token 提供。"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets

import yaml
from fastapi import APIRouter, Header, HTTPException, Request


router = APIRouter(tags=["出题给朋友"])


def publish(stories_dir: Path, story_id: str, save_story) -> str:
    """先落盘所有权，再发布 YAML；只有二者都成功才返回原始令牌。"""
    token = secrets.token_urlsafe(32)
    private_dir = stories_dir / ".owners"
    private_dir.mkdir(parents=True, exist_ok=True)
    target = private_dir / f"{story_id}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"story_id": story_id, "token_hash": hashlib.sha256(token.encode()).hexdigest()}), encoding="utf-8")
    temporary.replace(target)
    save_story()
    return token


def owned_story(stories_dir: Path, story_id: str, token: str | None) -> dict:
    if not token or len(token) > 256:
        raise HTTPException(403, "请使用出题时保存的访问令牌。")
    if not re.fullmatch(r"generated-[a-f0-9]{32}", story_id):
        raise HTTPException(404, "找不到分享案件。")
    try:
        metadata = json.loads((stories_dir / ".owners" / f"{story_id}.json").read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or not isinstance(metadata.get("token_hash"), str):
            raise HTTPException(503, "分享信息无法读取，请联系出题人。")
        supplied = hashlib.sha256(token.encode()).hexdigest()
        if metadata.get("story_id") != story_id or not hmac.compare_digest(metadata["token_hash"], supplied):
            raise HTTPException(403, "访问令牌不匹配，请使用本案件的出题人链接。")
        story = yaml.safe_load((stories_dir / f"{story_id}.yaml").read_text(encoding="utf-8"))
        if not isinstance(story, dict) or story.get("id") != story_id:
            raise HTTPException(503, "分享剧本无法读取，请联系出题人。")
        return story
    except FileNotFoundError as exc:
        raise HTTPException(404, "找不到分享案件。") from exc
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise HTTPException(503, "分享信息无法读取，请稍后重试。") from exc


def game_progress(engine, story_id: str) -> list[dict]:
    games = []
    for game_id, state in list(engine.games.items()):
        if state.story["id"] != story_id:
            continue
        ending = getattr(state, "ending", None)
        games.append({
            "game_id": game_id,
            "turns": getattr(state, "turns", sum(m.get("role") == "user" for history in state.histories.values() for m in history)),
            "clues": sorted(state.acquired_clues),
            "exposed": sorted(getattr(state, "exposed", set())),
            "ending": ending.get("id") if isinstance(ending, dict) else ending,
        })
    return games


@router.get("/api/stories/{story_id}/owner")
async def owner(story_id: str, request: Request, x_owner_token: str | None = Header(default=None)):
    studio = request.app.state.studio
    story = await asyncio.to_thread(owned_story, studio.stories_dir, story_id, x_owner_token)
    return {"story": story, "games": game_progress(request.app.state.engine, story_id)}
