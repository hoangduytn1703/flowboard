"""Auto-prompt route.

`POST /api/prompt/auto { node_id }` returns a Claude-composed prompt built
from the immediate-upstream context (character / visual_asset / image
nodes' aiBriefs). Frontend calls this when the user clicks Generate
without typing a prompt.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from flowboard.services import prompt_synth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompt", tags=["prompt"])


class AutoPromptBody(BaseModel):
    node_id: int
    # Optional video-only constraint: e.g. "static" → synth uses the camera-
    # locked system prompt and avoids dolly/zoom suggestions.
    camera: Optional[str] = None


class AutoPromptResponse(BaseModel):
    node_id: int
    prompt: str


@router.post("/auto", response_model=AutoPromptResponse)
async def auto_prompt(body: AutoPromptBody) -> AutoPromptResponse:
    try:
        text = await prompt_synth.auto_prompt(body.node_id, camera=body.camera)
    except prompt_synth.PromptSynthError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return AutoPromptResponse(node_id=body.node_id, prompt=text)


class RefinePromptBody(BaseModel):
    node_id: int
    draft: str
    camera: Optional[str] = None


@router.post("/refine", response_model=AutoPromptResponse)
async def refine_prompt(body: RefinePromptBody) -> AutoPromptResponse:
    """The user's rough prompt (any language) → one polished English prompt
    that follows the same rules as auto-prompt. Nothing is persisted."""
    try:
        text = await prompt_synth.refine_prompt(body.node_id, body.draft, camera=body.camera)
    except prompt_synth.PromptSynthError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return AutoPromptResponse(node_id=body.node_id, prompt=text)


class RevisePromptBody(BaseModel):
    node_id: int
    request: str
    # The prompt to revise; defaults to the one stored on the node.
    current: Optional[str] = None


@router.post("/revise", response_model=AutoPromptResponse)
async def revise_prompt(body: RevisePromptBody) -> AutoPromptResponse:
    """"Tạo lại" with a request: the node's prompt rewritten to do what the
    user asked (any language). Nothing is persisted."""
    try:
        text = await prompt_synth.revise_prompt(body.node_id, body.request, current=body.current)
    except prompt_synth.PromptSynthError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return AutoPromptResponse(node_id=body.node_id, prompt=text)


class AutoPromptBatchBody(BaseModel):
    node_id: int
    count: int
    camera: Optional[str] = None


class AutoPromptBatchResponse(BaseModel):
    node_id: int
    prompts: list[str]


@router.post("/auto-batch", response_model=AutoPromptBatchResponse)
async def auto_prompt_batch(body: AutoPromptBatchBody) -> AutoPromptBatchResponse:
    """Return N pose-distinct prompts so that an N-variant image gen
    actually produces N different shots instead of N seeds of the same
    stance."""
    if body.count < 1 or body.count > 8:
        raise HTTPException(status_code=400, detail="count must be 1..8")
    try:
        prompts = await prompt_synth.auto_prompt_batch(
            body.node_id, body.count, camera=body.camera
        )
    except prompt_synth.PromptSynthError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return AutoPromptBatchResponse(node_id=body.node_id, prompts=prompts)


class NarrationBody(BaseModel):
    board_id: int
    # Video nodes in clip order (the export node's join order).
    node_ids: list[int]
    instructions: Optional[str] = None


class NarrationResponse(BaseModel):
    narrations: dict[int, str]


@router.post("/narration", response_model=NarrationResponse)
async def write_narration(body: NarrationBody) -> NarrationResponse:
    """One Vietnamese voice-over line per video node, written onto the nodes
    (``data.narration``) so the export picks them up."""
    from flowboard.services import narration as narration_service

    try:
        lines = await narration_service.write_narrations(
            body.board_id, body.node_ids, instructions=body.instructions
        )
    except narration_service.NarrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return NarrationResponse(narrations=lines)
