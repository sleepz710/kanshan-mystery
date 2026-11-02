"""部署入口：页面和 API 共用一个体验口令。"""

import base64
import hmac
import os
from pathlib import Path

from dotenv import load_dotenv
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


ROOT = Path(__file__).resolve().parents[1]


class AccessPasswordMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, username: str, password: str):
        super().__init__(app)
        self.token = base64.b64encode(f"{username}:{password}".encode("utf-8"))

    async def dispatch(self, request, call_next):
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "basic" or not hmac.compare_digest(
            token.encode("utf-8"), self.token
        ):
            return JSONResponse(
                {"detail": "请输入体验账号和口令。"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Kanshan", charset="UTF-8"'},
            )
        return await call_next(request)


def create_app():
    load_dotenv(ROOT / ".env", override=False, encoding="utf-8")
    username = os.environ.get("DEPLOY_USERNAME", "").strip()
    password = os.environ.get("DEPLOY_PASSWORD", "")
    if not username or ":" in username or len(password) < 12:
        raise RuntimeError("请在 .env 设置 DEPLOY_USERNAME（不含冒号）和至少 12 位的 DEPLOY_PASSWORD。")

    from backend.app import create_app as create_game_app

    application = create_game_app()
    application.add_middleware(
        AccessPasswordMiddleware, username=username, password=password
    )
    return application
