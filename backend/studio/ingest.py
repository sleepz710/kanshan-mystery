"""只读取当前会话的文本附件；网页请求限制到解析后的公网地址。"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from pathlib import PurePath
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura


MAX_FILE_BYTES = 256 * 1024
MAX_MATERIAL_CHARS = 80000


class InputError(ValueError):
    pass


def read_file(filename: str, files: dict[str, bytes]) -> str:
    if filename not in files:
        raise InputError("找不到当前会话的附件，请重新上传。")
    if PurePath(filename).suffix.lower() not in {".txt", ".md"}:
        raise InputError("请上传 txt 或 md 文本文件。")
    data = files[filename]
    if len(data) > MAX_FILE_BYTES:
        raise InputError("单个附件不能超过 256 KB。")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise InputError("附件需要使用 UTF-8 编码，请转换后上传。") from exc
    if "\x00" in text or not text.strip():
        raise InputError("附件需要包含有效的文本内容。")
    if len(text) > MAX_MATERIAL_CHARS:
        raise InputError("附件文字过长，请缩短到八万字以内。")
    return text


async def _public_address(url: str) -> tuple[httpx.URL, str]:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise InputError("网址需要是公开的 HTTP 或 HTTPS 页面。")
        if parsed.port not in {None, 80, 443}:
            raise InputError("只支持普通网页端口。")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        hostname = parsed.hostname.encode("idna").decode("ascii")
        addresses = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(hostname, port, type=socket.SOCK_STREAM), timeout=10)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise InputError("只支持公网网页，请改为粘贴文字。")
        # 请求固定到已校验的 IP，避免检查之后再次 DNS 解析指向内网。
        target = httpx.URL(url).copy_with(host=addresses[0][4][0], fragment=None)
        return target, hostname
    except (ValueError, UnicodeError, socket.gaierror, TimeoutError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError("网址无法解析，请检查地址或粘贴文字。") from exc


async def fetch_url(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            for _ in range(4):
                target, hostname = await _public_address(url)
                async with client.stream("GET", target, headers={"Host": httpx.URL(url).netloc.decode("ascii"), "User-Agent": "KanshanMystery/1.0"}, extensions={"sni_hostname": hostname}) as response:
                    if response.is_redirect:
                        if not response.headers.get("location"):
                            raise InputError("网页跳转地址无效，请粘贴文字。")
                        url = urljoin(url, response.headers["location"])
                        continue
                    if response.status_code != 200:
                        raise InputError("网页暂时无法读取，请粘贴正文。")
                    content_type = response.headers.get("content-type", "").lower()
                    if not any(t in content_type for t in ("text/html", "text/plain", "application/xhtml+xml")):
                        raise InputError("该网址不是文本网页，请粘贴正文。")
                    data = bytearray()
                    async for part in response.aiter_bytes():
                        data.extend(part)
                        if len(data) > 2 * 1024 * 1024:
                            raise InputError("网页过大，请只粘贴需要改编的部分。")
                    if "text/plain" in content_type:
                        text = bytes(data).decode(response.encoding or "utf-8", errors="replace")
                    else:
                        text = await asyncio.to_thread(trafilatura.extract, bytes(data), include_comments=False, include_tables=True)
                    if not text or len(text.strip()) < 20:
                        raise InputError("网页正文抓取不到，请粘贴文字。")
                    if len(text) > MAX_MATERIAL_CHARS:
                        raise InputError("网页正文过长，请粘贴其中一碗汤。")
                    return text
        raise InputError("网页跳转过多，请粘贴正文。")
    except httpx.HTTPError as exc:
        raise InputError("网页连接失败，请改为粘贴文字。") from exc
