"""SPEC 6.2：编剧对话、附件上传、生成进度。"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from backend.studio.ingest import InputError, MAX_FILE_BYTES


router = APIRouter(tags=["生成剧场"])


class NewChat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["play", "share"] = "play"


@router.post("/api/studio/chats", status_code=201)
async def new_chat(body: NewChat, request: Request):
    return request.app.state.studio.create_chat(body.mode)


@router.post("/api/studio/chats/{chat_id}/messages")
async def message(chat_id: str, request: Request):
    service = request.app.state.studio
    if chat_id not in service.chats:
        raise HTTPException(404, "找不到编剧对话，请新建对话。")
    try:
        async with request.form(max_files=5, max_fields=1, max_part_size=MAX_FILE_BYTES) as form:
            if any(key not in {"text", "files"} for key in form):
                raise HTTPException(422, "只接受 text 与 files 字段。")
            text = form.get("text", "")
            if not isinstance(text, str):
                raise HTTPException(422, "text 必须是文字。")
            attachments = {}
            for uploaded in form.getlist("files"):
                if isinstance(uploaded, str) or not uploaded.filename:
                    raise HTTPException(422, "files 必须是文本附件。")
                if uploaded.filename in attachments:
                    raise HTTPException(422, "同一次上传的附件名称不能重复。")
                attachments[uploaded.filename] = await uploaded.read(MAX_FILE_BYTES + 1)
            return await service.message(chat_id, text, attachments)
    except InputError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/studio/jobs/{job_id}")
async def job_status(job_id: str, request: Request):
    job = request.app.state.studio.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "找不到生成任务，请重新生成。")
    return job.public()
