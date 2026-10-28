"""✂️ Edit auto CapCut — ``services/capcut_auto`` (jobs, sources, styles) and
``services/capcut_draft`` (the CapCut files).

  GET    /api/capcut/status                 what this machine has (Windows, CapCut, styles, AI, Whisper)
  POST   /api/capcut/learn                  scan the user's CapCut: text styles + sound effects
  PUT    /api/capcut/styles                 {subtitle?, emphasis?, title?} → which style does what
  GET    /api/capcut/sources                dubbed videos + finished clips that can go in
  POST   /api/capcut/upload                 the user's own video (multipart ``file``) → {media_id}
  POST   /api/capcut/fetch                  {url} → the video by link, like an upload
  POST   /api/capcut/jobs                   {source: {kind, id, title?}, name?, subtitles, highlights, zoom, sfx,
                                             cut_silence, sub_position} → a job
  GET    /api/capcut/jobs[/{id}]            running jobs / one job
  GET    /api/capcut/projects               projects made here (newest first)
  GET    /api/capcut/projects/{id}/srt      its subtitles as .srt (CapCut → Captions → Import = real captions)
  POST   /api/capcut/projects/{id}/return   the video exported from CapCut (multipart ``file``) → the clip's final video
  DELETE /api/capcut/projects/{id}?remove_folder=  off the list (and out of CapCut)
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field

from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.services import capcut_auto as auto
from flowboard.services import capcut_draft as cc
from flowboard.services import media as media_service

router = APIRouter(prefix="/api/capcut", tags=["capcut"])

MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
_VIDEO_EXT = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm", "video/x-matroska": ".mkv"}


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(400, str(exc))


@router.get("/status")
async def get_status() -> dict[str, Any]:
    return await auto.status()


@router.post("/learn")
def learn() -> dict[str, Any]:
    try:
        return auto.public_styles(auto.learn()) or {}
    except (auto.CapcutAutoError, cc.CapcutError) as exc:
        raise _fail(exc)


class StylesBody(BaseModel):
    subtitle: Optional[str] = None
    emphasis: Optional[str] = None
    title: Optional[str] = None


@router.put("/styles")
def put_styles(body: StylesBody) -> dict[str, Any]:
    try:
        return auto.public_styles(auto.choose_styles(body.model_dump())) or {}
    except auto.CapcutAutoError as exc:
        raise _fail(exc)


@router.get("/sources")
def get_sources() -> dict[str, Any]:
    return auto.sources()


async def _save_upload(file: UploadFile) -> tuple[Path, str]:
    mime = (file.content_type or "").lower().split(";")[0].strip()
    ext = _VIDEO_EXT.get(mime) or (Path(file.filename or "").suffix.lower() or ".mp4")
    if ext not in _VIDEO_EXT.values():
        raise HTTPException(415, "Chỉ nhận video MP4 / MOV / WEBM / MKV")
    media_service.MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    media_id = uuid.uuid4().hex
    path = media_service.MEDIA_CACHE_DIR / f"{media_id}{ext}"
    size = 0
    with path.open("wb") as fh:
        while chunk := await file.read(4 * 1024 * 1024):
            size += len(chunk)
            if size > MAX_VIDEO_BYTES:
                fh.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, "Video lớn hơn 2 GB")
            fh.write(chunk)
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(400, "File rỗng")
    return path, next((m for m, e in _VIDEO_EXT.items() if e == ext), "video/mp4")


@router.post("/upload", status_code=201)
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    from flowboard.services.video_export import probe_clip

    path, mime = await _save_upload(file)
    info = probe_clip(path)
    if info is None:
        path.unlink(missing_ok=True)
        raise HTTPException(400, "Không đọc được video này")
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=path.stem, local_path=str(path), mime=mime))
        s.commit()
    return {"media_id": path.stem, "name": Path(file.filename or "video").stem[:80], "duration": round(info.duration, 2),
            "width": info.width, "height": info.height, "url": f"/media/{path.stem}"}


class LinkBody(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@router.post("/fetch", status_code=201)
def fetch(body: LinkBody) -> dict[str, Any]:
    """A video by link (TikTok / Douyin / YouTube…) → like an upload."""
    try:
        return auto.fetch_link(body.url)
    except auto.CapcutAutoError as exc:
        raise _fail(exc)


class SourceBody(BaseModel):
    kind: Literal["dub", "clip", "upload", "dub_new"]
    id: str = Field(default="", max_length=80)
    title: Optional[str] = Field(None, max_length=120)
    media_id: Optional[str] = Field(None, max_length=64)  # dub_new: the uploaded / fetched video


class DubSpec(BaseModel):
    """Dub first, like "🎙 Lồng tiếng video" (source ``dub_new``)."""
    url: Optional[str] = Field(None, max_length=2000)
    source_media_id: Optional[str] = Field(None, max_length=64)
    voice: Optional[str] = None
    keep_bgm: bool = True
    channel_id: Optional[int] = None


class JobBody(BaseModel):
    source: SourceBody
    name: Optional[str] = Field(None, max_length=80)
    subtitles: Literal["tiktok", "line", "off"] = "tiktok"
    highlights: bool = True
    zoom: bool = True
    sfx: bool = True
    cut_silence: bool = False
    sub_position: Literal["video", "style"] = "video"
    # no subtitle texts in the project, only the .srt (CapCut → Captions → Import: real captions)
    srt_only: bool = False
    dub: Optional[DubSpec] = None


@router.post("/jobs", status_code=201)
def start_job(body: JobBody) -> dict[str, Any]:
    if body.source.kind != "dub_new" and not body.source.id:
        raise HTTPException(422, "Thiếu video nguồn")
    try:
        job = auto.start(body.source.model_dump(), body.model_dump(exclude={"source", "dub"}),
                         body.dub.model_dump() if body.dub else None)
    except auto.CapcutAutoError as exc:
        raise _fail(exc)
    return job.public()


@router.get("/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return [j.public() for j in sorted(auto.JOBS.values(), key=lambda j: j.started_at, reverse=True)]


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = auto.JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Không thấy việc này (agent đã khởi động lại?)")
    return job.public()


@router.get("/projects")
def list_projects() -> list[dict[str, Any]]:
    return auto.projects()


@router.get("/projects/{pid}/srt")
def project_srt(pid: str) -> Response:
    """The project's subtitles as SubRip, to import in CapCut (Captions → Import)."""
    from urllib.parse import quote

    try:
        name, text = auto.project_srt(pid)
    except auto.CapcutAutoError as exc:
        raise HTTPException(404, str(exc))
    ascii_name = name.encode("ascii", "ignore").decode() or "phu-de.srt"
    return Response(text, media_type="application/x-subrip; charset=utf-8", headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"})


@router.post("/projects/{pid}/return")
async def return_video(pid: str, file: UploadFile = File(...)) -> dict[str, Any]:
    path, mime = await _save_upload(file)
    try:
        return auto.return_video(pid, path, mime)
    except auto.CapcutAutoError as exc:
        path.unlink(missing_ok=True)
        raise _fail(exc)


@router.delete("/projects/{pid}")
def forget(pid: str, remove_folder: bool = Query(False)) -> dict[str, Any]:
    try:
        ok = auto.forget_project(pid, remove_folder)
    except cc.CapcutError as exc:
        raise _fail(exc)
    if not ok:
        raise HTTPException(404, "Không thấy dự án này")
    return {"ok": True}
