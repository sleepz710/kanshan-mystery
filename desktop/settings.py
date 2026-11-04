"""用户本地模型配置，只公开掩码，连接测试不会写入设置。"""

import json
import os
from pathlib import Path
from threading import RLock
from typing import Literal

from fastapi import APIRouter, HTTPException
from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider: Literal["deepseek", "openai"] = "deepseek"
    api_key: str | None = Field(default=None, max_length=2048)
    actor_model: str = Field(default="deepseek-flash", max_length=150)
    writer_model: str = Field(default="deepseek-flash", max_length=150)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


class ModelSettings:
    def __init__(self, directory: Path):
        self.path = directory / "config.json"
        self.lock = RLock()
        self.value = {"provider": "deepseek", "api_key": "", "actor_model": "deepseek-flash", "writer_model": "deepseek-flash"}
        if self.path.exists():
            try:
                self.value = SettingsInput.model_validate(json.loads(self.path.read_text(encoding="utf-8"))).model_dump()
            except (OSError, ValueError):
                raise RuntimeError("模型设置文件无法读取，请备份数据目录中的 config.json 后重试。") from None
        self.apply()

    def public(self):
        with self.lock:
            key = self.value.get("api_key") or ""
            return {"provider": self.value["provider"], "actor_model": self.value["actor_model"],
                    "writer_model": self.value["writer_model"], "has_key": bool(key), "key_suffix": key[-4:] if key else "",
                    "configured": bool(key and self.value["actor_model"] and self.value["writer_model"])}

    def candidate(self, incoming: SettingsInput):
        value = incoming.model_dump()
        if value["provider"] == "openai" and not {"actor_model", "writer_model"} <= incoming.model_fields_set:
            raise HTTPException(422, "OpenAI 需要明确填写演员和编剧的模型名称。")
        with self.lock:
            if not value["api_key"] and value["provider"] == self.value["provider"]:
                value["api_key"] = self.value.get("api_key") or ""
        if not value["api_key"]:
            raise HTTPException(422, "请填写当前服务的 API key。")
        if not value["actor_model"] or not value["writer_model"]:
            raise HTTPException(422, "请填写演员和编剧的模型名称。")
        return value

    def apply(self):
        value = self.value
        os.environ.update(LLM_MOCK="0", LLM_BASE_URL=self.base_url(value), LLM_API_KEY=value.get("api_key") or "",
                          LLM_ACTOR_MODEL=value["actor_model"], LLM_WRITER_MODEL=value["writer_model"],
                          LLM_WRITER_BASE_URL="", LLM_WRITER_API_KEY="", LLM_MODEL="")

    @staticmethod
    def base_url(value):
        return "https://api.deepseek.com" if value["provider"] == "deepseek" else "https://api.openai.com/v1"

    def save(self, incoming: SettingsInput):
        with self.lock:
            value = self.candidate(incoming)
            write_json(self.path, value)
            self.value = value
            self.apply()
            return self.public()


def settings_router(settings: ModelSettings) -> APIRouter:
    router = APIRouter(tags=["桌面模型设置"])

    @router.get("/api/settings")
    async def get_settings():
        return settings.public()

    @router.put("/api/settings")
    async def save_settings(body: SettingsInput):
        return settings.save(body)

    @router.post("/api/settings/test")
    async def test_settings(body: SettingsInput):
        value = settings.candidate(body)
        request = {"model": value["actor_model"], "messages": [{"role": "user", "content": "Reply OK."}], "max_tokens": 8}
        if value["provider"] == "deepseek":
            request["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            async with AsyncOpenAI(api_key=value["api_key"], base_url=settings.base_url(value), timeout=15, max_retries=0) as client:
                result = await client.chat.completions.create(**request)
            if not result.choices or not result.choices[0].message.content:
                return {"ok": False, "message": "服务已响应，但没有返回回复，请检查模型名称。"}
        except APIError:
            return {"ok": False, "message": "连接失败，请检查网络、服务、密钥和模型名称。"}
        return {"ok": True, "message": "连接成功，可以保存并开始探案。"}

    return router
