"""Vietnamese dubbing of a foreign short video ("Lồng tiếng video").

  GET  /api/dub/status                   runner / model availability, styles
  POST /api/dub/jobs                     {url | source_media_id, voice, keep_bgm, style, channel_id, name, auto_render}
  GET  /api/dub/jobs                     recent jobs (newest first)
  GET  /api/dub/jobs/{id}
  POST /api/dub/jobs/{id}/render         {lines?, voice?, style?, keep_bgm?, name?, channel_id?}
  POST /api/dub/jobs/{id}/stop
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from flowboard.services import dub, dub_remotion, tts

router = APIRouter(prefix="/api/dub", tags=["dub"])


class StartBody(BaseModel):
    url: Optional[str] = Field(default=None, max_length=2000)
    source_media_id: Optional[str] = Field(default=None, max_length=64)
    voice: str = tts.DEFAULT_VOICE
    keep_bgm: bool = False
    style: str = "box_yellow"
    # "ass" (ffmpeg/libass, default) or "remotion" (HTML/CSS subtitles, live preview)
    engine: str = "ass"
    channel_id: Optional[int] = None
    name: str = Field(default="", max_length=80)
    auto_render: bool = True


class RenderBody(BaseModel):
    lines: Optional[list[str]] = Field(default=None, max_length=2000)
    voice: Optional[str] = None
    style: Optional[str] = None
    engine: Optional[str] = None
    keep_bgm: Optional[bool] = None
    name: Optional[str] = Field(default=None, max_length=80)
    channel_id: Optional[int] = None
    # {x, y, scale}: where the subtitle box sits (fractions of the frame) and its size.
    layout: Optional[dict[str, Any]] = None


@router.get("/status")
def get_status() -> dict[str, Any]:
    st = dub.status()
    st["styles"] = [{"key": k, "label": v} for k, v in dub.STYLES.items()]
    st["remotion_styles"] = [{"key": k, "label": v} for k, v in dub_remotion.STYLES.items()]
    st["max_minutes"] = dub.MAX_DURATION_S // 60
    st["default_layout"] = dict(dub.DEFAULT_LAYOUT)
    return st


@router.post("/jobs", status_code=201)
async def start(body: StartBody) -> dict[str, Any]:
    try:
        job = dub.start_job(url=body.url, source_media_id=body.source_media_id, voice=body.voice, keep_bgm=body.keep_bgm,
                            style=body.style, engine=body.engine, channel_id=body.channel_id, name=body.name,
                            auto_render=body.auto_render)
    except dub.DubError as exc:
        raise HTTPException(400, str(exc))
    return job.public()


@router.get("/jobs")
def list_jobs() -> list[dict[str, Any]]:
    dub.load_jobs()
    return [j.public() for j in sorted(dub.JOBS.values(), key=lambda j: j.started_at, reverse=True)[:20]]


def _job(job_id: str) -> dub.Job:
    dub.load_jobs()
    job = dub.JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Không thấy việc lồng tiếng này (agent đã khởi động lại?)")
    return job


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    return _job(job_id).public()


@router.post("/jobs/{job_id}/render")
async def render(job_id: str, body: RenderBody) -> dict[str, Any]:
    job = _job(job_id)
    try:
        sent = body.model_dump(exclude_unset=True)
        dub.render_job(job, lines=body.lines, voice=body.voice, style=body.style, keep_bgm=body.keep_bgm,
                       name=body.name, layout=body.layout, engine=body.engine, **({"channel_id": body.channel_id} if "channel_id" in sent else {}))
    except dub.DubError as exc:
        raise HTTPException(400, str(exc))
    return job.public()


@router.get("/jobs/{job_id}/nosub")
def nosub(job_id: str) -> FileResponse:
    """Remotion engine: the dubbed video without subtitles — what the live
    <Player> preview plays under the subtitles it draws itself."""
    job = _job(job_id)
    path = (job.work / "nosub.mp4") if job.work else None
    if path is None or not path.is_file():
        raise HTTPException(404, "Chưa có bản video không phụ đề cho job này")
    return FileResponse(str(path), media_type="video/mp4")


@router.post("/jobs/{job_id}/stop")
def stop(job_id: str) -> dict[str, Any]:
    job = _job(job_id)
    if job.status in ("queued", "running", "rendering"):
        job.stop = True
    return job.public()
