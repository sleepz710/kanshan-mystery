import asyncio

import pytest

from backend.studio import check as checker
from backend.studio.service import StudioService


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_request", [False, True])
async def test_close_waits_for_material_model_cleanup(monkeypatch, tmp_path, cancel_request):
    service = StudioService(tmp_path / "stories")
    chat = service.create_chat("play")
    entered, cleanup_started, release_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def complete(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            cleanup = asyncio.create_task(release_cleanup.wait())
            while True:
                try:
                    await asyncio.shield(cleanup)
                    break
                except asyncio.CancelledError:
                    if cleanup.cancelled():
                        raise

    monkeypatch.setattr(checker, "complete_for", complete)
    request = asyncio.create_task(service.message(chat["chat_id"], "校园书店里发生的案件", {}))
    close = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if cancel_request:
            request.cancel()
            await asyncio.wait_for(cleanup_started.wait(), 1)
        close = asyncio.create_task(service.close())
        await asyncio.wait_for(cleanup_started.wait(), 1)
        await asyncio.sleep(0)
        assert not close.done()
        release_cleanup.set()
        await asyncio.wait_for(close, 1)
        with pytest.raises(asyncio.CancelledError):
            await request
        assert not service.tasks
        assert service.chats[chat["chat_id"]].materials == []
        assert service.chats[chat["chat_id"]].history == []
    finally:
        release_cleanup.set()
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        if close is not None:
            await asyncio.gather(close, return_exceptions=True)


@pytest.mark.asyncio
async def test_completed_material_request_leaves_no_shutdown_task(monkeypatch, tmp_path):
    service = StudioService(tmp_path / "stories")
    chat = service.create_chat("play")

    async def complete(*args, **kwargs):
        return {"action": "clarify", "strategy": "new", "reply": "希望全新创作还是沿用已有谜底？"}

    monkeypatch.setattr(checker, "complete_for", complete)
    response = await service.message(chat["chat_id"], "校园书店的现实推理", {})
    assert response["job"] is None
    assert not service.tasks
    assert service.chats[chat["chat_id"]].materials == ["校园书店的现实推理"]
    await service.close()
