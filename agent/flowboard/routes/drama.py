"""Drama clips: an article link or pasted story → Gemini plan → board.

1. ``POST /api/drama/analyze`` ``{url?, text?, beats?}`` → ``{source, plan}``
2. ``POST /api/drama/build``   ``{plan, name?}``             → board
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from flowboard.services import drama
from flowboard.services.llm import gemini_api

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/drama", tags=["drama"])


class AnalyzeBody(BaseModel):
    url: Optional[str] = Field(default=None, max_length=2000)
    text: Optional[str] = Field(default=None, max_length=30_000)
    beats: Optional[int] = Field(default=None, ge=drama.MIN_BEATS, le=drama.MAX_BEATS)
    model: Optional[str] = None


@router.post("/analyze")
async def analyze_drama(body: AnalyzeBody) -> dict[str, Any]:
    if not gemini_api.configured():
        raise HTTPException(400, "Chưa có Gemini API key — thêm trong Settings → Gemini API keys.")
    try:
        source = await drama.read_source(body.url, body.text)
        p = await drama.plan(source, beats=body.beats, model=body.model or drama.PLAN_MODEL)
    except drama.DramaError as exc:
        raise HTTPException(502 if "Gemini" in str(exc) else 400, str(exc))
    return {"source": {"title": source["title"], "url": source["url"], "chars": len(source["text"])}, "plan": p}


class BuildBody(BaseModel):
    plan: dict
    name: Optional[str] = Field(default=None, max_length=80)


@router.post("/build")
def build_drama(body: BuildBody) -> dict[str, Any]:
    try:
        p = drama.normalize(body.plan, {"url": body.plan.get("source_url"), "title": body.plan.get("title_vi")})
    except drama.DramaError as exc:
        raise HTTPException(400, str(exc))
    return drama.build_board(p, name=body.name)
