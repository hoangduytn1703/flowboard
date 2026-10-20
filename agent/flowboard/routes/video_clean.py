"""``/api/clean`` — remove text / logos / watermarks from an uploaded video.

The video itself arrives through ``POST /api/reference-video/upload`` (a
video Asset in ``storage/media``); everything here takes its ``media_id``.

    GET  /api/clean/ai-status                  is pyvideotrans (LaMa) usable?
    GET  /api/clean/{id}/info                  duration / display size
    GET  /api/clean/{id}/frame?t=1.0           JPEG frame to draw boxes on
    POST /api/clean/{id}/detect                AI: subtitle bands {y0,y1}
    POST /api/clean/{id}/erase                 mode box | ai-blur → new asset
                                               mode ai → {job_id}
    GET  /api/clean/jobs/{job_id}              queued|running|done|error
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.services import media as media_service
from flowboard.services import video_clean

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/clean", tags=["clean"])


def _video_path(media_id: str) -> tuple[str, Path]:
    media_id = media_service.normalize_media_id(media_id)
    if not media_service.is_valid_media_id(media_id):
        raise HTTPException(400, "invalid media_id")
    with get_session() as s:
        row = s.exec(select(Asset).where(Asset.uuid_media_id == media_id)).first()
    if row is None or row.kind != "video" or not row.local_path or not Path(row.local_path).is_file():
        raise HTTPException(404, "video not found — upload it first")
    return media_id, Path(row.local_path)


def _info(path: Path) -> video_clean.VideoInfo:
    try:
        return video_clean.probe_video(path)
    except video_clean.CleanError as exc:
        raise HTTPException(422, str(exc))


@router.get("/ai-status")
def get_ai_status() -> dict[str, Any]:
    return video_clean.ai_status()


@router.get("/{media_id}/info")
def get_info(media_id: str) -> dict[str, Any]:
    media_id, path = _video_path(media_id)
    info = _info(path)
    return {"media_id": media_id, "url": f"/media/{media_id}", "duration_s": round(info.duration, 2),
            "width": info.width, "height": info.height, "has_audio": info.has_audio}


@router.get("/{media_id}/frame")
async def get_frame(media_id: str, t: float = Query(default=0.0, ge=0.0)) -> FileResponse:
    media_id, path = _video_path(media_id)
    info = _info(path)
    try:
        frame = await asyncio.to_thread(video_clean.frame_at, path, media_id, t, info.duration)
    except video_clean.CleanError as exc:
        raise HTTPException(422, str(exc))
    return FileResponse(str(frame), media_type="image/jpeg",
                        headers={"X-Frame-Width": str(info.width), "X-Frame-Height": str(info.height),
                                 "Cache-Control": "private, max-age=3600"})


@router.post("/{media_id}/detect")
async def detect(media_id: str) -> dict[str, Any]:
    """Subtitle bands found by pyvideotrans (RapidOCR over ~24–48 frames)."""
    media_id, path = _video_path(media_id)
    info = _info(path)
    try:
        found = await asyncio.to_thread(video_clean.detect_bands, path)
    except video_clean.CleanError as exc:
        raise HTTPException(503 if "Không thấy Python" in str(exc) else 502, str(exc))
    return {"media_id": media_id, "bands": found["bands"], "info": found["info"],
            "preview_t": round(min(max(0.0, info.duration * 0.3), max(0.0, info.duration - 0.1)), 2)}


class BoxIn(BaseModel):
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class BandIn(BaseModel):
    y0: float = Field(ge=0, lt=1)
    y1: float = Field(gt=0, le=1)


class EraseBody(BaseModel):
    mode: Literal["box", "ai", "ai-blur"]
    boxes: list[BoxIn] = Field(default_factory=list)
    bands: list[BandIn] = Field(default_factory=list)
    method: Literal["delogo", "blur"] = "delogo"


@router.post("/{media_id}/erase")
async def erase(media_id: str, body: EraseBody) -> dict[str, Any]:
    media_id, path = _video_path(media_id)
    try:
        if body.mode == "box":
            boxes = [video_clean.Box.from_dict(b.model_dump()) for b in body.boxes]
            return await asyncio.to_thread(video_clean.clean_with_boxes, path, boxes, body.method)
        bands = [b.model_dump() for b in body.bands]
        if body.mode == "ai-blur":
            boxes = [video_clean.band_to_box(b) for b in bands]
            return await asyncio.to_thread(video_clean.clean_with_boxes, path, boxes, "blur")
        job = video_clean.start_ai_job(media_id, path, bands)
    except video_clean.CleanError as exc:
        msg = str(exc)
        if video_clean.active_job() is not None and "Đang có" in msg:
            raise HTTPException(409, msg)
        if "Không thấy Python" in msg:
            raise HTTPException(503, msg)
        raise HTTPException(422, msg)
    return {"job_id": job.id, "status": job.status}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = video_clean.JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job.public()


@router.post("/jobs/{job_id}/stop")
def stop_job(job_id: str) -> dict[str, Any]:
    job = video_clean.JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    if job.status in ("queued", "running"):
        job.stop = True
    return job.public()
