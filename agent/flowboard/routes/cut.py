"""✂️ Cắt video (services/video_cut): links / files → many short videos, each editable in the dubbing editor.

  GET  /api/cut/status
  POST /api/cut/sessions                 {links, media: [{media_id, name}], how, prompt, min_s, max_s, max_parts, review, channel_id}
  GET  /api/cut/sessions                 newest first (brief: no lines)
  GET  /api/cut/sessions/{id}
  POST /api/cut/sessions/{id}/suggest    {how, prompt, min_s, max_s, max_parts} → {rows, by, note} (nothing cut)
  POST /api/cut/sessions/{id}/cut        {rows} — cut / cut again
  POST /api/cut/sessions/{id}/stop | /again
  POST /api/cut/sessions/delete          {ids} — the list only; the parts (clips + projects) stay
  GET  /api/cut/parts?run=|session=      the parts' editing projects (dub jobs of kind "cut"), in cut order
  POST /api/cut/clips                    {board_ids} → the clips' final videos (dubbing a cut part later)
The parts are edited through the dubbing editor's routes (/api/dub/jobs/{id}/render, …).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from flowboard.services import video_cut

router = APIRouter(prefix="/api/cut", tags=["cut"])


class MediaItem(BaseModel):
    media_id: str = Field(max_length=64)
    name: str = Field(default="", max_length=200)


class StartBody(BaseModel):
    links: list[str] = Field(default_factory=list, max_length=video_cut.MAX_LINKS)
    media: list[MediaItem] = Field(default_factory=list, max_length=video_cut.MAX_LINKS)
    how: str = Field(default="ai", pattern="^(ai|prompt|even)$")
    prompt: str = Field(default="", max_length=2000)
    min_s: float = video_cut.DEFAULT_MIN_S
    max_s: float = video_cut.DEFAULT_MAX_S
    max_parts: int = Field(default=0, ge=0, le=100)
    review: bool = False
    channel_id: Optional[int] = None


class SuggestBody(BaseModel):
    how: str = Field(default="ai", pattern="^(ai|prompt|even)$")
    prompt: str = Field(default="", max_length=2000)
    min_s: float = video_cut.DEFAULT_MIN_S
    max_s: float = video_cut.DEFAULT_MAX_S
    max_parts: int = Field(default=0, ge=0, le=100)


class Row(BaseModel):
    start: float
    end: float
    title: str = Field(default="", max_length=200)


class CutBody(BaseModel):
    rows: list[Row] = Field(max_length=100)


class IdsBody(BaseModel):
    ids: list[str] = Field(max_length=200)


class ClipsBody(BaseModel):
    board_ids: list[int] = Field(max_length=50)


def _session(session_id: str) -> video_cut.Session:
    s = video_cut.find(session_id)
    if s is None:
        raise HTTPException(404, "Không thấy video cắt này")
    return s


@router.get("/status")
def get_status() -> dict[str, Any]:
    return video_cut.status()


@router.post("/sessions", status_code=201)
def start(body: StartBody) -> dict[str, Any]:
    try:
        run_id, made = video_cut.start(links=body.links, media=[m.model_dump() for m in body.media], how=body.how,
                                       prompt=body.prompt, min_s=body.min_s, max_s=body.max_s, max_parts=body.max_parts,
                                       review=body.review, channel_id=body.channel_id)
    except video_cut.CutError as exc:
        raise HTTPException(400, str(exc))
    return {"run_id": run_id, "sessions": [video_cut.public(s, brief=True) for s in made]}


@router.get("/sessions")
def list_sessions(limit: int = Query(60, ge=1, le=300)) -> list[dict[str, Any]]:
    return [video_cut.public(s, brief=True) for s in video_cut.sessions()[:limit]]


@router.post("/sessions/delete")
def delete_sessions(body: IdsBody) -> dict[str, Any]:
    deleted, skipped = video_cut.delete(body.ids)
    return {"deleted": deleted, "skipped": skipped}


@router.get("/sessions/{session_id}")
def get_session_(session_id: str) -> dict[str, Any]:
    return video_cut.public(_session(session_id))


@router.post("/sessions/{session_id}/suggest")
async def suggest(session_id: str, body: SuggestBody) -> dict[str, Any]:
    s = _session(session_id)
    try:
        return await video_cut.suggest_again(s, how=body.how, prompt=body.prompt, min_s=body.min_s, max_s=body.max_s,
                                             max_parts=body.max_parts)
    except video_cut.CutError as exc:
        raise HTTPException(400, str(exc))


@router.post("/sessions/{session_id}/cut")
def cut(session_id: str, body: CutBody) -> dict[str, Any]:
    s = _session(session_id)
    try:
        video_cut.cut(s, [r.model_dump() for r in body.rows])
    except video_cut.CutError as exc:
        raise HTTPException(400, str(exc))
    return video_cut.public(s, brief=True)


@router.post("/sessions/{session_id}/stop")
def stop(session_id: str) -> dict[str, Any]:
    return video_cut.public(video_cut.stop(_session(session_id)), brief=True)


@router.post("/sessions/{session_id}/again")
def again(session_id: str) -> dict[str, Any]:
    try:
        return video_cut.public(video_cut.again(_session(session_id)), brief=True)
    except video_cut.CutError as exc:
        raise HTTPException(400, str(exc))


@router.get("/parts")
def parts(run: Optional[str] = Query(None, max_length=40), session: Optional[str] = Query(None, max_length=40)) -> list[dict[str, Any]]:
    if not run and not session:
        raise HTTPException(400, "Cần run hoặc session")
    return [j.public() for j in video_cut.part_jobs(run_id=run, session_id=session)]


@router.post("/clips")
def clips(body: ClipsBody) -> list[dict[str, Any]]:
    return video_cut.clip_media(body.board_ids)
