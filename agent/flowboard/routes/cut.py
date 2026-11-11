"""✂️ Cắt video (services/video_cut): links / files → many short videos, each editable in the dubbing editor.

  GET  /api/cut/status
  POST /api/cut/sessions                 {links, media: [{media_id, name}], how (ai | prompt | manual | even), rows (manual), prompt, min_s, max_s, max_parts, review, channel_id,
                                          look_preset_id} — the parts come out rendered in that ★ Mẫu chỉnh sửa
  GET  /api/cut/sessions                 newest first (brief: no lines)
  GET  /api/cut/sessions/{id}
  POST /api/cut/sessions/{id}/suggest    {how, prompt, min_s, max_s, max_parts, title_lang} → {rows, by, note, name} (nothing cut)
  POST /api/cut/sessions/{id}/cut        {rows} — cut / cut again
  POST /api/cut/sessions/{id}/stop | /again
  POST /api/cut/sessions/{id}/hear       {on} — hear the words in the background now / stop hearing
  POST /api/cut/sessions/delete          {ids} — the list only; the parts (clips + projects) stay
  GET  /api/cut/parts?run=|session=      the parts' editing projects (dub jobs of kind "cut"), in cut order
  GET  /api/cut/prompts | PUT {prompts: [{id, name, text}]}   the account's saved cut prompts (whole list)
  POST /api/cut/clips                    {board_ids} → the clips' final videos (dubbing a cut part later)
The parts are edited through the dubbing editor's routes (/api/dub/jobs/{id}/render, …).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from flowboard.services import dub, video_cut

router = APIRouter(prefix="/api/cut", tags=["cut"])


class MediaItem(BaseModel):
    media_id: str = Field(max_length=64)
    name: str = Field(default="", max_length=200)


class Row(BaseModel):
    start: float
    end: float
    title: str = Field(default="", max_length=200)
    #: a second line under the name (optional)
    subtitle: str = Field(default="", max_length=300)


class StartBody(BaseModel):
    links: list[str] = Field(default_factory=list, max_length=video_cut.MAX_LINKS)
    media: list[MediaItem] = Field(default_factory=list, max_length=video_cut.MAX_LINKS)
    how: str = Field(default="ai", pattern="^(ai|prompt|manual|even)$")
    #: "Tự cắt" (how manual): the parts typed by the seller, [{start, end, title, subtitle?}] in seconds
    rows: list[Row] = Field(default_factory=list, max_length=100)
    #: "🔍 Phân tích": download + hear only; each video then waits for its parts (typed, or the AI's via /suggest)
    analyze: bool = False
    prompt: str = Field(default="", max_length=8000)
    #: the language of the titles the AI writes ("" = what the request says, else Vietnamese)
    title_lang: str = Field(default="", max_length=40)
    min_s: float = video_cut.DEFAULT_MIN_S
    max_s: float = video_cut.DEFAULT_MAX_S
    max_parts: int = Field(default=0, ge=0, le=100)
    review: bool = False
    channel_id: Optional[int] = None
    #: a saved "★ Mẫu chỉnh sửa" (frame, background, sticker, blur boxes…) every part is rendered in
    look_preset_id: Optional[int] = None


class SuggestBody(BaseModel):
    how: str = Field(default="ai", pattern="^(ai|prompt|even)$")
    prompt: str = Field(default="", max_length=8000)
    #: the language of the titles the AI writes ("" = what the request says, else Vietnamese)
    title_lang: str = Field(default="", max_length=40)
    min_s: float = video_cut.DEFAULT_MIN_S
    max_s: float = video_cut.DEFAULT_MAX_S
    max_parts: int = Field(default=0, ge=0, le=100)


class CutBody(BaseModel):
    rows: list[Row] = Field(max_length=100)
    #: "manual" = the seller typed these rows
    how: Optional[str] = Field(default=None, pattern="^(manual)$")
    #: "Sáng / tối" of the preview: {brightness, contrast, saturation} put on every part ({} = untouched)
    adjust: Optional[dict[str, Any]] = None
    #: "Tốc độ" of the preview (0.8–3): every part is exported at that speed (1 = the source's)
    speed: Optional[float] = Field(default=None, ge=0.1, le=10)


class HearBody(BaseModel):
    #: true = hear the words now (Whisper, in the background); false = stop / skip it
    on: bool = True


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


class SavedPrompt(BaseModel):
    id: str = Field(default="", max_length=40)
    name: str = Field(default="", max_length=200)
    text: str = Field(max_length=8000)


class PromptsBody(BaseModel):
    prompts: list[SavedPrompt] = Field(max_length=video_cut.MAX_SAVED_PROMPTS)


@router.get("/prompts")
def get_prompts() -> list[dict[str, str]]:
    return video_cut.saved_prompts()


@router.put("/prompts")
def put_prompts(body: PromptsBody) -> list[dict[str, str]]:
    return video_cut.save_prompts([p.model_dump() for p in body.prompts])


@router.post("/sessions", status_code=201)
def start(body: StartBody) -> dict[str, Any]:
    try:
        look = dub.look_preset(body.look_preset_id)
    except dub.DubError as exc:
        raise HTTPException(404, str(exc))
    try:
        run_id, made = video_cut.start(links=body.links, media=[m.model_dump() for m in body.media], how=body.how,
                                       prompt=body.prompt, min_s=body.min_s, max_s=body.max_s, max_parts=body.max_parts,
                                       review=body.review, channel_id=body.channel_id, look=look,
                                       title_lang=body.title_lang, rows=[r.model_dump() for r in body.rows], analyze=body.analyze)
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
                                             max_parts=body.max_parts, title_lang=body.title_lang)
    except video_cut.CutError as exc:
        raise HTTPException(400, str(exc))


@router.post("/sessions/{session_id}/cut")
def cut(session_id: str, body: CutBody) -> dict[str, Any]:
    s = _session(session_id)
    try:
        video_cut.cut(s, [r.model_dump() for r in body.rows], how=body.how, adjust=body.adjust, speed=body.speed)
    except video_cut.CutError as exc:
        raise HTTPException(400, str(exc))
    return video_cut.public(s, brief=True)


@router.post("/sessions/{session_id}/hear")
def hear(session_id: str, body: HearBody) -> dict[str, Any]:
    """Whisper for a video that was analysed: start it (it was skipped, failed, or the agent restarted) or stop it."""
    s = _session(session_id)
    if body.on:
        if not video_cut.status()["whisper"]:
            raise HTTPException(400, "Máy này chưa có gói nghe lời (Whisper) — cài ở Cài đặt → 🖥 Máy này → Gói lồng tiếng.")
        video_cut.hear_later(s)
    else:
        video_cut.hear_skip(s)
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
