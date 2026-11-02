"""验证部署口令和开局，不调用模型。"""

import argparse
import base64
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ready", action="store_true", help="只检查已认证的 API 文档")
    parser.add_argument("--wait", action="store_true", help="等待服务启动，最多 15 秒")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False, encoding="utf-8")
    credentials = f"{os.environ['DEPLOY_USERNAME']}:{os.environ['DEPLOY_PASSWORD']}"
    headers = {"Authorization": "Basic " + base64.b64encode(credentials.encode("utf-8")).decode("ascii")}

    def request(path, *, body=None, authenticated=True):
        request_headers = dict(headers) if authenticated else {}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        req = Request(
            args.base_url.rstrip("/") + path,
            headers=request_headers,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
        )
        return urlopen(req, timeout=5)

    deadline = time.monotonic() + (15 if args.wait else 0)
    while True:
        try:
            response = request("/openapi.json")
            break
        except URLError as error:
            if not isinstance(error.reason, ConnectionRefusedError) or time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
    with response:
        schema = json.load(response)
    if args.ready:
        return
    for path in ("/", "/docs", "/api/stories", "/api/games", "/studio/"):
        try:
            request(path, authenticated=False)
        except HTTPError as error:
            if error.code != 401 or not error.headers.get("WWW-Authenticate", "").startswith("Basic "):
                raise
        else:
            raise RuntimeError(f"{path} 没有要求访问口令。")
    with request("/") as response:
        if response.status != 200:
            raise RuntimeError("首页未正常返回。")
    with request("/api/stories") as response:
        stories = json.load(response)
        if not any(story["id"] == "lost-tuition" for story in stories):
            raise RuntimeError("案件列表中缺少招牌案件。")
    with request("/api/games", body={"story_id": "lost-tuition"}) as response:
        game = json.load(response)
        if (
            response.status != 201 or not game["game_id"] or not game["characters"]
            or not game["questions"] or not game["kanshan"]["greeting"]
            or game["kanshan"]["asks_left"] != 5
        ):
            raise RuntimeError("开局结果不完整。")
    print("通过：页面和 API 的口令保护、首页、API 文档、案件列表、第二版招牌案件开局。")
    if "/api/studio/chats" not in schema["paths"]:
        print("待联调：当前后端尚未挂载生成剧场接口。")


if __name__ == "__main__":
    main()
