"""Media cache routes.

`GET /media/:media_id` streams bytes (cache hit → immediate; miss → one-shot
fetch from GCS then cache). `GET /api/media/:media_id/status` exposes cache
state for the frontend to poll while it waits for a URL to arrive.
"""
from __future__ import annotations

import logging

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from flowboard.services import media as media_service
from flowboard.services import face_check, poster, watermark

logger = logging.getLogger(__name__)

bytes_router = APIRouter(tags=["media"])
api_router = APIRouter(prefix="/api/media", tags=["media"])


@bytes_router.get("/media/{media_id:path}")
async def get_media_bytes(media_id: str):
    media_id = media_service.normalize_media_id(media_id)
    if not media_service.is_valid_media_id(media_id):
        raise HTTPException(status_code=400, detail="invalid media_id")

    cached = media_service.cached_path(media_id)
    if cached is not None:
        return FileResponse(
            path=str(cached),
            media_type=media_service._mime_from_ext(cached.suffix),
        )

    # Cache miss — try one fetch through the stored URL, unless that already
    # failed a moment ago: a page listing media that never reached this
    # machine (probe clips, other projects) asked again on every visit and
    # each miss cost ~0.7 s (History took 6 s, 2026-10-24).
    if media_service.recently_missed(media_id):
        return JSONResponse(status_code=404, content={"available": False, "reason": "recent_miss"})
    result = await media_service.fetch_and_cache(media_id)
    if result is None:
        media_service.remember_miss(media_id)
        status = media_service.status(media_id)
        return JSONResponse(status_code=404, content=status)
    _bytes, mime, path = result
    return FileResponse(path=str(path), media_type=mime)


class CleanMarksBody(BaseModel):
    enabled: bool


@api_router.get("/clean-marks")
def clean_marks_status() -> dict:
    """The Gemini-sparkle switch and how many cached generated images are on this machine."""
    return {"enabled": watermark.enabled(), "candidates": len(watermark.cached_image_files())}


@api_router.put("/clean-marks")
def set_clean_marks(body: CleanMarksBody) -> dict:
    watermark.set_enabled(body.enabled)
    return {"enabled": watermark.enabled(), "candidates": len(watermark.cached_image_files())}


@api_router.post("/clean-marks/run")
async def run_clean_marks() -> dict:
    """Strip the sparkle from every cached generated image that still carries it."""
    return await asyncio.to_thread(watermark.clean_cached_images)


@api_router.get("/{media_id}/poster")
async def get_media_poster(media_id: str):
    """A still of a video (services/poster) — the card picture of a clip that has only its finished video."""
    media_id = media_service.normalize_media_id(media_id)
    if not media_service.is_valid_media_id(media_id):
        raise HTTPException(status_code=400, detail="invalid media_id")
    path = await poster.poster_for(media_id)
    if path is None:
        raise HTTPException(status_code=404, detail="no video to take a picture from")
    return FileResponse(path=str(path), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@api_router.get("/{media_id}/faces")
async def get_media_faces(media_id: str) -> dict:
    """How many faces an image shows — a shop photo with a real model makes
    Flow drop the clips (see services/face_check)."""
    media_id = media_service.normalize_media_id(media_id)
    if not media_service.is_valid_media_id(media_id):
        raise HTTPException(status_code=400, detail="invalid media_id")
    path = media_service.cached_path(media_id)
    if path is None:
        fetched = await media_service.fetch_and_cache(media_id)
        path = fetched[2] if fetched else None
    if path is None:
        return {"faces": None}
    return {"faces": await asyncio.to_thread(face_check.count_faces, path)}


@api_router.get("/{media_id}/status")
def get_media_status(media_id: str):
    media_id = media_service.normalize_media_id(media_id)
    if not media_service.is_valid_media_id(media_id):
        return JSONResponse(
            status_code=400,
            content={"available": False, "has_url": False, "reason": "invalid_id"},
        )
    return media_service.status(media_id)


@api_router.get("/_debug/assets")
def debug_assets():
    """Dev-only dump of every Asset row so we can see what URLs the extension
    has actually pushed to the agent. Remove once media flow is stable.
    """
    from sqlmodel import select as _select

    from flowboard.db import get_session
    from flowboard.db.models import Asset

    with get_session() as s:
        rows = s.exec(_select(Asset)).all()
        return {
            "count": len(rows),
            "rows": [
                {
                    "id": r.id,
                    "media_id": r.uuid_media_id,
                    "has_url": bool(r.url),
                    "url_head": (r.url or "")[:80] if r.url else None,
                    "mime": r.mime,
                    "cached": bool(r.local_path),
                    "node_id": r.node_id,
                }
                for r in rows
            ],
        }
