"""演员与编剧共用的 JSON 调用层，默认使用离线模拟模式。"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI


_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODELS = {"actor": "deepseek-flash", "writer": "deepseek-flash"}
_DEFAULT_MAX_TOKENS = {"actor": 1024, "writer": 8192}
_JSON_REPAIR_INSTRUCTION = "只返回合法 JSON 对象，字符串正确转义，不要 Markdown 或解释。"


class LLMError(RuntimeError):
    """提供给接口层的模型错误，不携带服务商原始响应或密钥。"""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def is_mock_mode() -> bool:
    """读取固定项目目录的 .env，进程环境变量优先；默认模拟模式。"""

    if os.environ.get("KANSHAN_DESKTOP") != "1":
        load_dotenv(_ENV_FILE, override=False, encoding="utf-8")
    mode = os.environ.get("LLM_MOCK", "1").strip()
    if mode not in {"0", "1"}:
        raise LLMError("LLM_MOCK 需要填写 0 或 1。", status_code=503)
    return mode == "1"


def _setting(name: str) -> str:
    return os.environ.get(name, "").strip()


def _is_deepseek_url(base_url: str, setting_name: str) -> bool:
    try:
        url = urlsplit(base_url)
        valid_url = (
            url.scheme in {"http", "https"}
            and bool(url.hostname)
            and url.username is None
            and url.password is None
            and not any(char.isspace() for char in base_url)
        )
        # 访问 port 会验证 "https://host:invalid" 这类配置。
        url.port
    except ValueError:
        valid_url = False
    if not valid_url:
        raise LLMError(f"{setting_name} 需要填写有效的 HTTP 或 HTTPS 接口地址。", status_code=503)
    return url.hostname == "api.deepseek.com"


def _real_settings(purpose: str = "actor") -> tuple[str, str, str]:
    base_url = _setting("LLM_BASE_URL") or _DEFAULT_BASE_URL
    api_key = _setting("LLM_API_KEY")
    base_name = "LLM_BASE_URL"
    key_name = "LLM_API_KEY"
    model_name = "LLM_ACTOR_MODEL" if purpose == "actor" else "LLM_WRITER_MODEL"

    if purpose == "writer":
        if writer_base := _setting("LLM_WRITER_BASE_URL"):
            base_url = writer_base
            base_name = "LLM_WRITER_BASE_URL"
        api_key = _setting("LLM_WRITER_API_KEY") or api_key
        key_name = "LLM_WRITER_API_KEY 或 LLM_API_KEY"

    is_deepseek = _is_deepseek_url(base_url, base_name)
    model = _setting(model_name)
    if purpose == "actor":
        model = model or _setting("LLM_MODEL")
    if not model and is_deepseek:
        model = _DEFAULT_MODELS[purpose]

    missing = []
    if not api_key:
        missing.append(key_name)
    if not model:
        missing.append(model_name)
    if missing:
        raise LLMError("真实模型模式缺少配置：" + "、".join(missing) + "。", status_code=503)
    return base_url, api_key, model


def _openai_reasoning_options(base_url: str, model: str, purpose: str) -> dict:
    if (urlsplit(base_url).hostname == "api.openai.com"
            and model in {"gpt-5.4", "gpt-5.4-2026-03-05"}):
        return {"reasoning_effort": "none" if purpose == "actor" else "high"}
    return {}


def _reject_non_json_number(value: str) -> None:
    raise ValueError("JSON 不支持的数值：" + value)


class _JSONFormatError(LLMError):
    """只对可修复的回复格式错误触发一次应用层重试。"""


def _decode_completion(completion) -> dict:
    if not completion.choices:
        raise LLMError("模型没有返回回复内容。")
    choice = completion.choices[0]
    if choice.finish_reason == "length":
        raise LLMError("模型回复超过长度限制，请缩短输入后重试。")
    content = choice.message.content
    if not isinstance(content, str) or not content.strip():
        raise _JSONFormatError("模型没有返回回复内容。")
    try:
        result = json.loads(content, parse_constant=_reject_non_json_number)
    except (json.JSONDecodeError, ValueError) as exc:
        raise _JSONFormatError("模型没有返回有效的 JSON，请重试。") from exc
    if not isinstance(result, dict):
        raise _JSONFormatError("模型返回的 JSON 必须是对象。")
    return result


async def complete_json(
    messages: list[dict],
    *,
    purpose: str = "actor",
    mock_response: dict | None = None,
    max_tokens: int | None = None,
) -> dict:
    """返回 JSON 对象；调用方负责校验自己的业务字段。

    purpose="actor" 用于角色、核查、对质和汤主问答，默认 1024 tokens；
    purpose="writer" 用于编剧与审稿，默认 8192 tokens。调用方可覆盖 max_tokens。
    DeepSeek 官方接口分别关闭、开启思考模式；官方 GPT-5.4 使用 none/high 和 max_completion_tokens。
    messages 中必须明确要求模型输出 JSON。单次请求超时 30 秒，SDK 最多重试一次。
    格式错误会追加通用 JSON 说明后重发一次，不回灌无效回复；网络与截断错误直接返回。
    模拟模式只返回 mock_response 的副本，不创建模型客户端。
    """

    if purpose not in ("actor", "writer"):
        raise LLMError("purpose 需要填写 actor 或 writer。", status_code=503)
    if max_tokens is not None and (type(max_tokens) is not int or max_tokens <= 0):
        raise LLMError("max_tokens 需要填写正整数。", status_code=503)
    token_limit = max_tokens if max_tokens is not None else _DEFAULT_MAX_TOKENS[purpose]

    if is_mock_mode():
        if not isinstance(mock_response, dict):
            raise LLMError("模拟调用需要提供 mock_response JSON 对象。", status_code=503)
        return deepcopy(mock_response)

    base_url, api_key, model = _real_settings(purpose)
    reasoning_options = _openai_reasoning_options(base_url, model, purpose)
    token_field = "max_completion_tokens" if reasoning_options else "max_tokens"
    request = {
        "model": model,
        "messages": deepcopy(messages),
        "response_format": {"type": "json_object"},
        token_field: token_limit,
        **reasoning_options,
    }
    if _is_deepseek_url(base_url, "LLM_BASE_URL"):
        request["extra_body"] = {
            "thinking": {"type": "disabled" if purpose == "actor" else "enabled"}
        }
        if purpose == "actor":
            request["temperature"] = 0
    try:
        async with AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=30.0,
            max_retries=1,
        ) as client:
            completion = await client.chat.completions.create(**request)
            try:
                return _decode_completion(completion)
            except _JSONFormatError:
                request["messages"] = [
                    *deepcopy(messages),
                    {"role": "user", "content": _JSON_REPAIR_INSTRUCTION},
                ]
                completion = await client.chat.completions.create(**request)
                return _decode_completion(completion)
    except _JSONFormatError as exc:
        raise LLMError(exc.message, status_code=exc.status_code) from exc
    except APITimeoutError as exc:
        raise LLMError("模型服务响应超时，请稍后重试。", status_code=504) from exc
    except APIConnectionError as exc:
        raise LLMError("无法连接模型服务，请检查服务地址和连接。") from exc
    except APIError as exc:
        raise LLMError("模型服务请求失败，请检查模型配置后重试。") from exc

