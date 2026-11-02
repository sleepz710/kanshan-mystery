"""OpenAI 兼容的 JSON 调用层，默认使用离线模拟模式。"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI


_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class LLMError(RuntimeError):
    """提供给接口层的模型错误，不携带服务商原始响应或密钥。"""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def is_mock_mode() -> bool:
    """读取固定项目目录的 .env，进程环境变量优先；默认模拟模式。"""

    load_dotenv(_ENV_FILE, override=False, encoding="utf-8")
    mode = os.environ.get("LLM_MOCK", "1").strip()
    if mode not in {"0", "1"}:
        raise LLMError("LLM_MOCK 需要填写 0 或 1。", status_code=503)
    return mode == "1"


def _real_settings() -> tuple[str, str, str]:
    names = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")
    values = [os.environ.get(name, "").strip() for name in names]
    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        raise LLMError(
            "真实模型模式缺少配置：" + "、".join(missing) + "。",
            status_code=503,
        )
    base_url, api_key, model = values
    try:
        url = urlsplit(base_url)
        valid_url = url.scheme in {"http", "https"} and bool(url.hostname)
    except ValueError:
        valid_url = False
    if not valid_url:
        raise LLMError("LLM_BASE_URL 需要填写 HTTP 或 HTTPS 接口地址。", status_code=503)
    return base_url, api_key, model


def _reject_non_json_number(value: str) -> None:
    raise ValueError("JSON 不支持的数值：" + value)


async def complete_json(
    messages: list[dict], *, mock_response: dict | None = None
) -> dict:
    """返回 JSON 对象；调用方负责校验自己的业务字段。

    真实调用使用 Chat Completions，兼容项目待选的模型服务。
    messages 中必须明确要求模型输出 JSON。单次请求超时 30 秒，最多重试一次。
    模拟模式只返回 mock_response 的副本，不创建模型客户端。
    """

    if is_mock_mode():
        if not isinstance(mock_response, dict):
            raise LLMError("模拟调用需要提供 mock_response JSON 对象。", status_code=503)
        return deepcopy(mock_response)

    base_url, api_key, model = _real_settings()
    try:
        async with AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=30.0,
            max_retries=1,
        ) as client:
            completion = await client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
            )
    except APITimeoutError as exc:
        raise LLMError("模型服务响应超时，请稍后重试。", status_code=504) from exc
    except APIConnectionError as exc:
        raise LLMError("无法连接模型服务，请检查服务地址和连接。") from exc
    except APIError as exc:
        raise LLMError("模型服务请求失败，请检查模型配置后重试。") from exc

    if not completion.choices:
        raise LLMError("模型没有返回回复内容。")
    choice = completion.choices[0]
    if choice.finish_reason == "length":
        raise LLMError("模型回复超过长度限制，请缩短输入后重试。")
    content = choice.message.content
    if not isinstance(content, str) or not content.strip():
        raise LLMError("模型没有返回回复内容。")
    try:
        result = json.loads(content, parse_constant=_reject_non_json_number)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LLMError("模型没有返回有效的 JSON，请重试。") from exc
    if not isinstance(result, dict):
        raise LLMError("模型返回的 JSON 必须是对象。")
    return result
