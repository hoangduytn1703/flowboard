"""The prompt library: scene prompts, motion prompts and voice lines saved
from step 2 of the wizard and put back on another clip.

  GET    /api/prompt-library?kind=image|video|narration&q=
  POST   /api/prompt-library            {kind, text, title?, tags?, source_board_id?}
  PATCH  /api/prompt-library/{id}       {title?, text?, tags?}
  DELETE /api/prompt-library/{id}
  POST   /api/prompt-library/{id}/use   → bumps the use counter
  POST   /api/prompt-library/samples    → puts back every missing sample prompt
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlmodel import or_, select

from flowboard.db import get_session
from flowboard.db.models import SavedPrompt
from flowboard.timestamps import utc_iso

router = APIRouter(prefix="/api/prompt-library", tags=["prompt-library"])

KINDS = ("image", "video", "narration")
MAX_TEXT = 4000


class PromptCreate(BaseModel):
    kind: str
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    title: Optional[str] = Field(default=None, max_length=120)
    tags: Optional[list[str]] = None
    source_board_id: Optional[int] = None


class PromptPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=120)
    text: Optional[str] = Field(default=None, min_length=1, max_length=MAX_TEXT)
    tags: Optional[list[str]] = None


def _row(r: SavedPrompt) -> dict[str, Any]:
    return {
        "id": r.id, "kind": r.kind, "title": r.title, "text": r.text, "tags": list(r.tags or []),
        "source_board_id": r.source_board_id, "uses": r.uses, "created_at": utc_iso(r.created_at),
    }


def _default_title(text: str) -> str:
    words = text.strip().split()
    return " ".join(words[:8]) + ("…" if len(words) > 8 else "")


@router.get("")
def list_prompts(kind: Optional[str] = None, q: Optional[str] = None, limit: int = 200) -> list[dict]:
    if kind is not None and kind not in KINDS:
        raise HTTPException(400, f"kind phải là một trong {list(KINDS)}")
    with get_session() as s:
        stmt = select(SavedPrompt)
        if kind:
            stmt = stmt.where(SavedPrompt.kind == kind)
        if q and q.strip():
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(SavedPrompt.title.ilike(like), SavedPrompt.text.ilike(like)))  # type: ignore[attr-defined]
        stmt = stmt.order_by(SavedPrompt.uses.desc(), SavedPrompt.created_at.desc()).limit(max(1, min(limit, 500)))  # type: ignore[attr-defined]
        return [_row(r) for r in s.exec(stmt).all()]


@router.post("", status_code=201)
def create_prompt(body: PromptCreate) -> dict:
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind phải là một trong {list(KINDS)}")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "prompt trống")
    with get_session() as s:
        # Saving the same text twice is a no-op: hand back the existing row.
        existing = s.exec(select(SavedPrompt).where(SavedPrompt.kind == body.kind, SavedPrompt.text == text)).first()
        if existing is not None:
            return _row(existing)
        row = SavedPrompt(
            kind=body.kind, text=text, title=(body.title or "").strip() or _default_title(text),
            tags=[t.strip() for t in (body.tags or []) if t.strip()][:10], source_board_id=body.source_board_id,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return _row(row)


@router.post("/samples")
def restore_samples() -> dict:
    """Put back the sample prompts the user deleted (or never had)."""
    from flowboard.services.prompt_seeds import add_missing

    return {"added": add_missing()}


@router.patch("/{prompt_id}")
def patch_prompt(prompt_id: int, body: PromptPatch) -> dict:
    with get_session() as s:
        row = s.get(SavedPrompt, prompt_id)
        if row is None:
            raise HTTPException(404, "không có prompt này")
        if body.title is not None:
            row.title = body.title.strip() or _default_title(row.text)
        if body.text is not None and body.text.strip():
            row.text = body.text.strip()
        if body.tags is not None:
            row.tags = [t.strip() for t in body.tags if t.strip()][:10]
        s.add(row)
        s.commit()
        s.refresh(row)
        return _row(row)


@router.delete("/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: int) -> Response:
    with get_session() as s:
        row = s.get(SavedPrompt, prompt_id)
        if row is None:
            raise HTTPException(404, "không có prompt này")
        s.delete(row)
        s.commit()
    return Response(status_code=204)


@router.post("/{prompt_id}/use")
def use_prompt(prompt_id: int) -> dict:
    with get_session() as s:
        row = s.get(SavedPrompt, prompt_id)
        if row is None:
            raise HTTPException(404, "không có prompt này")
        row.uses += 1
        s.add(row)
        s.commit()
        s.refresh(row)
        return _row(row)
