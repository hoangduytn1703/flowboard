"""Extras of the "Xuất video" step that are not the export itself:

1. ``POST /api/llm/music``                multipart → ``{media_id}``: a
   background-music track (mp3 / m4a / wav, ≤ 20 MB) stored locally and
   registered as an audio Asset for the export worker to loop under the clip.
2. ``POST /api/boards/{board_id}/cover``  ``{media_id, title, subtitle?,
   style?}`` → ``{media_id}``: a 1080×1920 PNG cover rendered from a scene
   image with the title burned in (``video_export.render_cover``),
   registered as an image Asset so ``/media/{id}`` serves it.
3. ``GET / POST /api/boards/{board_id}/smooth60``  → ``{total, ready, running}``: how many scenes already have their
   60 fps copy / start smoothing them in the background now (services/smooth_prewarm).
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Asset, Board
from flowboard.services import media as media_service
from flowboard.services import tts, video_export

logger = logging.getLogger(__name__)

router = APIRouter(tags=["export-extras"])

MAX_MUSIC_BYTES = 20 * 1024 * 1024
_AUDIO_EXT_BY_MIME = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/vnd.wave": ".wav",
}
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


@router.post("/api/llm/music")
async def upload_music(file: UploadFile = File(...)) -> dict[str, Any]:
    """Store a music track locally and register it as an audio Asset."""
    mime = (file.content_type or "").lower().split(";")[0].strip()
    ext = _AUDIO_EXT_BY_MIME.get(mime)
    guess = Path(file.filename or "").suffix.lower()
    if ext is None:
        # Browsers label audio inconsistently ("application/octet-stream"
        # for .m4a is common); trust the extension then.
        if guess in (".mp3", ".m4a", ".wav"):
            ext = guess
            mime = next(m for m, e in _AUDIO_EXT_BY_MIME.items() if e == guess)
        else:
            raise HTTPException(415, f"unsupported audio type {mime or guess!r}; use mp3 / m4a / wav")
    raw = await file.read(MAX_MUSIC_BYTES + 1)
    if not raw:
        raise HTTPException(400, "empty file")
    if len(raw) > MAX_MUSIC_BYTES:
        raise HTTPException(413, f"music too large: {len(raw) // (1024 * 1024)} MB > 20 MB")
    media_id = uuid.uuid4().hex
    media_service.MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = media_service.MEDIA_CACHE_DIR / f"{media_id}{ext}"
    path.write_bytes(raw)
    duration = tts._probe_duration(path)
    if duration is not None and duration <= 0:
        path.unlink(missing_ok=True)
        raise HTTPException(415, "the file holds no audio")
    with get_session() as s:
        s.add(Asset(kind="audio", uuid_media_id=media_id, local_path=str(path), mime=mime))
        s.commit()
    name = Path(file.filename or f"nhac{ext}").name
    logger.info("music: stored %s (%s, %d bytes, %.1fs)", media_id, name, len(raw), duration or -1)
    return {"media_id": media_id, "name": name, "mime": mime, "size": len(raw),
            "duration_s": round(duration, 1) if duration else None}


class CoverBody(BaseModel):
    media_id: str
    title: str = Field(min_length=1, max_length=200)
    subtitle: Optional[str] = Field(default=None, max_length=120)
    style: Optional[str] = None  # yellow | white | red


def _image_path(media_id: str) -> Path:
    media_id = media_service.normalize_media_id(media_id)
    if not media_service.is_valid_media_id(media_id):
        raise HTTPException(400, "invalid media_id")
    path = media_service.cached_path(media_id)
    if path is None:
        with get_session() as s:
            row = s.exec(select(Asset).where(Asset.uuid_media_id == media_id)).first()
        if row is not None and row.local_path and Path(row.local_path).is_file():
            path = Path(row.local_path)
    if path is None or path.suffix.lower() not in _IMAGE_SUFFIXES:
        raise HTTPException(404, "scene image not found — render the scene first")
    return path


@router.post("/api/boards/{board_id}/cover")
def create_cover(board_id: int, body: CoverBody) -> dict[str, Any]:
    """Render the cover for ``board_id`` from one of its scene images."""
    with get_session() as s:
        if s.get(Board, board_id) is None:
            raise HTTPException(404, "board not found")
    src = _image_path(body.media_id)
    style = body.style if body.style in tts.COVER_STYLES else "yellow"
    media_id = uuid.uuid4().hex
    # Named after the id so the media route's cache glob finds it directly.
    dst = media_service.MEDIA_CACHE_DIR / f"{media_id}.png"
    err = video_export.render_cover(src, dst, body.title, subtitle=body.subtitle, style=style)
    if err:
        raise HTTPException(502, f"ffmpeg: {err}")
    with get_session() as s:
        s.add(Asset(kind="image", uuid_media_id=media_id, local_path=str(dst), mime="image/png"))
        s.commit()
    logger.info("cover: board %d → %s (%d bytes)", board_id, media_id, dst.stat().st_size)
    return {"media_id": media_id, "url": f"/media/{media_id}", "width": video_export.COVER_SIZE[0],
            "height": video_export.COVER_SIZE[1]}


def _board_or_404(board_id: int) -> None:
    with get_session() as s:
        if s.get(Board, board_id) is None:
            raise HTTPException(404, "Không thấy clip này.")


@router.get("/api/boards/{board_id}/smooth60")
def smooth60_status(board_id: int) -> dict[str, Any]:
    """How many of the clip's scenes already have their 60 fps copy (made in the background, services/smooth_prewarm)."""
    from flowboard.services import smooth_prewarm

    _board_or_404(board_id)
    return smooth_prewarm.board_status(board_id)


@router.post("/api/boards/{board_id}/smooth60")
def smooth60_warm(board_id: int) -> dict[str, Any]:
    """"Mượt 60 fps" just turned on: the clip's scenes are smoothed in the background now, so "Ghép" does not wait."""
    from flowboard.services import smooth_prewarm

    _board_or_404(board_id)
    return smooth_prewarm.warm_board(board_id)
