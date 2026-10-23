"""CRUD endpoints for the user-curated cross-board reference library.

A Reference is a snapshot of (media_id, label, kind, ai_brief,
aspect_ratio, tags, provenance) that the user explicitly saved from
a generated variant or an uploaded node. Distinct from Asset (the
auto-managed media cache index): references have user-curated
lifetime and metadata; cache files in storage/media/{id}.{ext} are
owned by Asset and never touched on reference DELETE.
"""
import copy
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlmodel import select, or_

from flowboard.db import get_session
from flowboard.db.models import Reference

router = APIRouter(prefix="/api/references", tags=["references"])


# Valid kinds — matches the source node types that can be saved.
_ALLOWED_KINDS = {"image", "character", "visual_asset", "storyboard_shot"}


class ReferenceCreate(BaseModel):
    media_id: str = Field(min_length=1)
    kind: str
    label: Optional[str] = None
    ai_brief: Optional[str] = None
    aspect_ratio: Optional[str] = None
    url: Optional[str] = None
    source_board_id: Optional[int] = None
    source_node_short_id: Optional[str] = None
    tags: Optional[list[str]] = None
    # Kind-specific extras (character: gender / country / vibe / extras /
    # prompt / product). Free-form so the wizard can grow it without a
    # schema change; the row is the only consumer.
    meta: Optional[dict[str, Any]] = None


class ReferencePatch(BaseModel):
    label: Optional[str] = None
    # A new photo for the same saved item (e.g. editing a saved model).
    media_id: Optional[str] = None
    aspect_ratio: Optional[str] = None
    ai_brief: Optional[str] = None
    pinned: Optional[bool] = None
    position: Optional[int] = None
    tags: Optional[list[str]] = None
    # Replaces the whole dict (no deep merge): the frontend always sends
    # the full set of keys it knows about.
    meta: Optional[dict[str, Any]] = None


def _default_label(body: ReferenceCreate) -> str:
    """Compute the fallback label when the user didn't supply one.

    Preference order:
      1. ai_brief truncated to 80 chars,
      2. "#" + source_node_short_id (provenance handle),
      3. "Untitled".
    """
    if body.ai_brief:
        return body.ai_brief[:80]
    if body.source_node_short_id:
        return f"#{body.source_node_short_id}"
    return "Untitled"


def _row_dict(row: Reference) -> dict[str, Any]:
    return {
        "id": row.id,
        "media_id": row.media_id,
        "url": row.url,
        "label": row.label,
        "kind": row.kind,
        "ai_brief": row.ai_brief,
        "aspect_ratio": row.aspect_ratio,
        "tags": list(row.tags or []),
        "pinned": row.pinned,
        "position": row.position,
        "source_board_id": row.source_board_id,
        "source_node_short_id": row.source_node_short_id,
        "meta": dict(row.meta or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("")
def create_reference(body: ReferenceCreate):
    """Save a media_id to the library.

    Idempotent on media_id: if a row with the same media_id already
    exists, return that row unchanged (200, not 409). Lets the
    frontend treat ★ Save as a "set membership" toggle without
    needing to pre-check.
    """
    if body.kind not in _ALLOWED_KINDS:
        raise HTTPException(
            400,
            f"invalid kind {body.kind!r}; must be one of {sorted(_ALLOWED_KINDS)}",
        )

    with get_session() as s:
        existing = s.exec(
            select(Reference).where(Reference.media_id == body.media_id)
        ).first()
        if existing is not None:
            return _row_dict(existing)

        label = body.label if body.label else _default_label(body)
        row = Reference(
            media_id=body.media_id,
            kind=body.kind,
            label=label,
            ai_brief=body.ai_brief,
            aspect_ratio=body.aspect_ratio,
            url=body.url,
            source_board_id=body.source_board_id,
            source_node_short_id=body.source_node_short_id,
            tags=list(body.tags or []),
            meta=dict(body.meta or {}),
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return _row_dict(row)


@router.get("")
def list_references(
    q: Optional[str] = None,
    kind: Optional[str] = None,
    pinned_first: bool = True,
    limit: int = 200,
):
    """List references, sorted (pinned DESC, position ASC, created_at DESC).

    ``q``: case-insensitive substring match against label OR ai_brief.
    ``kind``: only rows of that kind (e.g. ``character`` for the model
    library); must be one of the allowed kinds.
    ``pinned_first``: when False, drop pinned from the ORDER BY so
    raw insertion order surfaces (debug / testing convenience).
    """
    if kind is not None and kind not in _ALLOWED_KINDS:
        raise HTTPException(
            400,
            f"invalid kind {kind!r}; must be one of {sorted(_ALLOWED_KINDS)}",
        )
    with get_session() as s:
        stmt = select(Reference)
        if kind is not None:
            stmt = stmt.where(Reference.kind == kind)
        if q:
            needle = f"%{q.lower()}%"
            # SQLite's LIKE is case-insensitive for ASCII by default but
            # we lower() both sides for explicitness and unicode safety.
            from sqlalchemy import func
            stmt = stmt.where(
                or_(
                    func.lower(Reference.label).like(needle),
                    func.lower(Reference.ai_brief).like(needle),
                )
            )
        if pinned_first:
            stmt = stmt.order_by(
                Reference.pinned.desc(),
                Reference.position.asc(),
                Reference.created_at.desc(),
            )
        else:
            stmt = stmt.order_by(
                Reference.position.asc(),
                Reference.created_at.desc(),
            )
        stmt = stmt.limit(limit)
        rows = s.exec(stmt).all()
        return [_row_dict(r) for r in rows]


@router.patch("/{ref_id}")
def patch_reference(ref_id: int, body: ReferencePatch):
    """Partial update — only fields present in the request body are touched."""
    with get_session() as s:
        row = s.get(Reference, ref_id)
        if row is None:
            raise HTTPException(404, "reference not found")
        fields = body.model_fields_set
        if "label" in fields and body.label is not None:
            row.label = body.label
        if "pinned" in fields and body.pinned is not None:
            row.pinned = body.pinned
        if "position" in fields and body.position is not None:
            row.position = body.position
        if "tags" in fields and body.tags is not None:
            row.tags = list(body.tags)
        if "meta" in fields and body.meta is not None:
            row.meta = dict(body.meta)
        if "media_id" in fields and body.media_id and body.media_id != row.media_id:
            from flowboard.services import media as media_service

            new_id = media_service.normalize_media_id(body.media_id)
            if not media_service.is_valid_media_id(new_id):
                raise HTTPException(400, "invalid media_id")
            row.media_id = new_id
            # The old brief described the old photo.
            row.ai_brief = body.ai_brief if "ai_brief" in fields else None
        elif "ai_brief" in fields:
            row.ai_brief = body.ai_brief
        if "aspect_ratio" in fields and body.aspect_ratio:
            row.aspect_ratio = body.aspect_ratio
        s.add(row)
        s.commit()
        s.refresh(row)
        return _row_dict(row)


@router.post("/{ref_id}/clone")
def clone_reference(ref_id: int):
    """A copy of a saved item ("⧉ Nhân bản" on /models): same photo, name,
    meta, tags — nothing checked for duplicates, the copy may be identical.
    The new row is the newest, so it lists first."""
    with get_session() as s:
        row = s.get(Reference, ref_id)
        if row is None:
            raise HTTPException(404, "reference not found")
        clone = Reference(
            media_id=row.media_id, url=row.url, label=row.label, kind=row.kind, ai_brief=row.ai_brief,
            aspect_ratio=row.aspect_ratio, tags=list(row.tags or []), pinned=row.pinned, position=row.position,
            source_board_id=row.source_board_id, source_node_short_id=row.source_node_short_id,
            meta=copy.deepcopy(row.meta or {}),
        )
        s.add(clone)
        s.commit()
        s.refresh(clone)
        return _row_dict(clone)


@router.delete("/{ref_id}", status_code=204)
def delete_reference(ref_id: int):
    """Hard delete the reference row.

    The underlying ``storage/media/{media_id}.{ext}`` file is NOT
    touched — the Asset table owns cache lifetime.
    """
    with get_session() as s:
        row = s.get(Reference, ref_id)
        if row is None:
            raise HTTPException(404, "reference not found")
        s.delete(row)
        s.commit()
    return Response(status_code=204)
