"""🤖 Trợ lý AI chat (services/assistant).

  GET    /api/assistant              the conversation + the tasks it started (running ones carry on in the background)
  POST   /api/assistant/chat {message}   one turn: the reply, and the task it started (if any)
  DELETE /api/assistant              forget the conversation (what the tasks made stays)
  POST   /api/assistant/tasks/{id}/confirm   run a plan that waits for the go-ahead (it posts publicly by itself)
  POST   /api/assistant/tasks/{id}/cancel    drop it
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from flowboard.services import assistant

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=assistant.MAX_MESSAGE)


@router.get("")
def get_state() -> dict[str, Any]:
    return assistant.state()


@router.post("/chat")
async def chat(body: ChatBody) -> dict[str, Any]:
    try:
        return await assistant.chat(body.message)
    except assistant.AssistantError as exc:
        raise HTTPException(400, str(exc))


@router.delete("")
def clear() -> dict[str, Any]:
    return {"removed": assistant.clear()}


@router.post("/tasks/{task_id}/confirm")
async def confirm(task_id: int) -> dict[str, Any]:
    task = assistant.confirm(task_id)
    if task is None:
        raise HTTPException(404, "Kế hoạch này không còn chờ xác nhận.")
    return {"task": task}


@router.post("/tasks/{task_id}/cancel")
def cancel(task_id: int) -> dict[str, Any]:
    if not assistant.cancel(task_id):
        raise HTTPException(404, "Kế hoạch này không còn chờ xác nhận.")
    assistant._add_message("assistant", "Ok, mình huỷ kế hoạch đó rồi.", task_id=task_id)
    return {"ok": True}
