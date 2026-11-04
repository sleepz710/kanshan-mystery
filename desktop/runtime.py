"""桌面专用挂载、随机端口的浏览器存储迁移和局内状态保存。"""

import asyncio
from dataclasses import asdict, fields
import json
import logging
from pathlib import Path
from threading import RLock

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from backend.engine import GameError, GameState
from backend.paths import data_root
from desktop.settings import ModelSettings, settings_router, write_json


class BrowserStorage:
    def __init__(self, directory):
        self.path = directory / "browser-storage.json"
        self.lock = RLock()
        try:
            self.values = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except (OSError, ValueError):
            raise RuntimeError("浏览器记录文件无法读取，请备份 browser-storage.json 后重试。") from None

    def snapshot(self):
        with self.lock:
            return dict(self.values)

    def save(self, values):
        if not isinstance(values, dict) or any(not isinstance(k, str) or not k.startswith("kanshan:") or not isinstance(v, str) for k, v in values.items()):
            raise HTTPException(422, "只能保存看山谜案馆的字符串记录。")
        with self.lock:
            write_json(self.path, values)
            self.values = values

    def bootstrap(self):
        initial = json.dumps(self.snapshot(), ensure_ascii=True).replace("<", "\\u003c")
        return '''<script>(()=>{
const initial=INITIAL;
const set=Storage.prototype.setItem,remove=Storage.prototype.removeItem,clear=Storage.prototype.clear;
Object.keys(localStorage).filter(k=>k.startsWith('kanshan:')).forEach(k=>remove.call(localStorage,k));
Object.entries(initial).forEach(([k,v])=>set.call(localStorage,k,v));
function persist(){
 const values={}; Object.keys(localStorage).filter(k=>k.startsWith('kanshan:')).forEach(k=>values[k]=localStorage.getItem(k));
 const xhr=new XMLHttpRequest();xhr.open('PUT','/api/desktop/storage',false);xhr.setRequestHeader('Content-Type','application/json');xhr.send(JSON.stringify(values));
 if(xhr.status!==200)throw Error('本地记录保存失败，请检查磁盘空间。');
}
Storage.prototype.setItem=function(k,v){set.call(this,k,v);if(this===localStorage&&String(k).startsWith('kanshan:'))persist();};
Storage.prototype.removeItem=function(k){remove.call(this,k);if(this===localStorage&&String(k).startsWith('kanshan:'))persist();};
Storage.prototype.clear=function(){clear.call(this);if(this===localStorage)persist();};
window.KANSHAN_DESKTOP=true;
document.documentElement.classList.add('desktop-window');
})();</script><link rel="stylesheet" href="/css/window.css"><script src="/js/window.js" defer></script>'''.replace("INITIAL", initial)


def game_snapshot(engine):
    def serializable(value):
        if isinstance(value, set):
            return sorted(value)
        raise TypeError("游戏状态包含无法保存的值。")
    return json.loads(json.dumps({gid: asdict(state) for gid, state in engine.games.items()}, default=serializable))


def restore_games(engine, path):
    if not path.exists():
        return
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        for gid, values in saved.items():
            values["story"] = engine._load_story(values["story"]["id"])
            for key in ("acquired_clues", "triggered_events", "exposed_lies"):
                values[key] = set(values[key])
            values["shown"] = {cid: set(clues) for cid, clues in values["shown"].items()}
            values["hint_counts"] = {int(k): v for k, v in values["hint_counts"].items()}
            state = GameState(**{f.name: values[f.name] for f in fields(GameState) if f.name in values})
            engine.games[gid] = state
            engine._locks[gid] = asyncio.Lock()
    except (OSError, ValueError, TypeError, KeyError, GameError):
        logging.getLogger(__name__).warning("保存的对局记录无法恢复，保留文件以便检查。")


def mount_desktop(application):
    directory = data_root()
    settings = ModelSettings(directory)
    storage = BrowserStorage(directory)
    application.state.desktop_settings = settings
    application.state.desktop_storage = storage
    application.include_router(settings_router(settings))
    games_path = directory / "games.json"
    restore_games(application.state.engine, games_path)

    @application.put("/api/desktop/storage")
    async def save_storage(request: Request):
        if len(await request.body()) > 16 * 1024 * 1024:
            raise HTTPException(413, "本地记录过大。")
        storage.save(await request.json())
        return {"ok": True}

    @application.get("/settings/", response_class=HTMLResponse)
    async def settings_page():
        return (Path(__file__).resolve().parent / "ui" / "index.html").read_text(encoding="utf-8")

    @application.middleware("http")
    async def desktop_requests(request: Request, call_next):
        path = request.url.path
        origin = request.headers.get("origin")
        if path.startswith(("/api/settings", "/api/desktop/")) and origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "请在桌面窗口内操作。"}, status_code=403)
        if request.method == "POST" and (path == "/api/games" or path.endswith("/messages")) and not settings.public()["configured"]:
            return JSONResponse({"detail": "请先打开模型设置，填写自己的 API key。", "settings_url": "/settings/"}, status_code=503)
        is_page = request.method == "GET" and not path.startswith("/api/") and (path.endswith("/") or path.endswith(".html"))
        if is_page:
            request.scope["headers"] = [(k, v) for k, v in request.scope["headers"] if k not in (b"if-none-match", b"if-modified-since")]
        response = await call_next(request)
        if request.method == "POST" and path.startswith("/api/games") and response.status_code < 400:
            write_json(games_path, game_snapshot(application.state.engine))
        if is_page and response.status_code == 200 and "text/html" in response.headers.get("content-type", ""):
            body = b"".join([chunk async for chunk in response.body_iterator]).decode("utf-8")
            body = body.replace("<head>", "<head>" + storage.bootstrap(), 1)
            headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "etag", "last-modified")}
            headers["cache-control"] = "no-store"
            return HTMLResponse(body, headers=headers)
        return response
