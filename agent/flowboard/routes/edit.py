"""🎞 Chỉnh sửa video (services/video_edit): the list of videos being edited, many at a time.

  GET  /api/edit/items                 the account's list, newest first
  GET  /api/edit/jobs?ids=a,b,c        those projects, full, in that order (the editor's "Video n/N")
  POST /api/edit/import                {media: [{media_id, name}]} — files already uploaded (/api/reference-video/upload) → one project each
  POST /api/edit/clips                 {board_ids} — clips of "Clip của tôi" (a dubbed / cut clip brings its own project)
  POST /api/edit/add                   {job_ids} — projects made by the other tools (Lồng tiếng, Cắt video, Cào video kênh)
  POST /api/edit/remove                {job_ids} — off the list only; clips and files stay
  POST /api/edit/jobs/{id}/hear        hear the words now (subtitles wanted) | GET the state | POST …/hear/stop
The videos are edited through the dubbing editor's routes (/api/dub/jobs/{id}/render, …).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from flowboard.services import dub, video_edit

router = APIRouter(prefix="/api/edit", tags=["edit"])

#: how many videos one editor session takes (each one is a full project with its lines)
MAX_EDIT_TOGETHER = 60


class MediaItem(BaseModel):
    media_id: str = Field(max_length=64)
    name: str = Field(default="", max_length=2000)


class ImportBody(BaseModel):
    media: list[MediaItem] = Field(max_length=video_edit.MAX_IMPORT)


class ClipsBody(BaseModel):
    board_ids: list[int] = Field(max_length=video_edit.MAX_IMPORT)


class JobsBody(BaseModel):
    job_ids: list[str] = Field(max_length=video_edit.MAX_LIST)


def _job(job_id: str) -> dub.Job:
    job = dub.find_job(job_id)
    if job is None:
        raise HTTPException(404, "Không thấy video này nữa trên máy.")
    return job


@router.get("/items")
def list_items() -> dict[str, Any]:
    return {"items": video_edit.items(), "max_import": video_edit.MAX_IMPORT}


@router.get("/jobs")
def jobs_by_ids(ids: str = Query(..., max_length=4000)) -> list[dict[str, Any]]:
    """Exactly these projects (full, with lines), in this order — the videos opened together in the editor.
    One this machine no longer has is left out."""
    wanted = list(dict.fromkeys(i.strip() for i in ids.split(",") if i.strip()))[:MAX_EDIT_TOGETHER]
    found = (dub.find_job(i) for i in wanted)
    return [j.public() for j in found if j is not None]


@router.post("/import")
def import_files(body: ImportBody) -> dict[str, Any]:
    return video_edit.import_media([m.model_dump() for m in body.media])


@router.post("/clips")
async def import_clips(body: ClipsBody) -> dict[str, Any]:
    return await video_edit.import_clips(body.board_ids)


@router.post("/add")
def add_jobs(body: JobsBody) -> dict[str, Any]:
    return {"job_ids": video_edit.add(body.job_ids)}


@router.post("/remove")
def remove_jobs(body: JobsBody) -> dict[str, Any]:
    return video_edit.remove(body.job_ids)


@router.post("/jobs/{job_id}/hear")
def hear(job_id: str) -> dict[str, Any]:
    try:
        return video_edit.hear(_job(job_id))
    except video_edit.EditError as exc:
        raise HTTPException(400, str(exc))


@router.get("/jobs/{job_id}/hear")
def hear_state(job_id: str) -> dict[str, Any]:
    return video_edit.hear_state(job_id)


@router.post("/jobs/{job_id}/hear/stop")
def hear_stop(job_id: str) -> dict[str, Any]:
    return video_edit.hear_stop(job_id)
