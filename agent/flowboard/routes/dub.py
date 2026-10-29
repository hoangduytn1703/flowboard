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

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from flowboard.services import dub, dub_links, dub_remotion, tts

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
    # several links started together share a batch id (client-made); the editor groups them
    batch_id: str = Field(default="", max_length=40)
    # "★ Mẫu chỉnh sửa": start with that saved look (layout, style, engine, key-moment settings)
    look_preset_id: Optional[int] = None


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
    # timeline editor: new [start, end] (seconds) for every line
    timings: Optional[list[list[float]]] = Field(default=None, max_length=2000)
    # timeline editor: a line's own {x, y, scale, w} (null = the clip-wide layout)
    looks: Optional[list[Optional[dict[str, Any]]]] = Field(default=None, max_length=2000)
    # "✨ Nhấn chữ quan trọng": {on, words, zoom, sfx, sfx_set, y, points: [{at, words, line}]}
    highlights: Optional[dict[str, Any]] = None


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
        look = _look_preset(body.look_preset_id)
        job = dub.start_job(url=body.url, source_media_id=body.source_media_id, voice=body.voice, keep_bgm=body.keep_bgm,
                            style=look["style"] if look else body.style, engine=look["engine"] if look else body.engine, channel_id=body.channel_id, name=body.name,
                            auto_render=body.auto_render, batch_id=body.batch_id,
                            layout=look["layout"] if look else None, highlights=look["highlights"] if look else None)
    except dub.DubError as exc:
        raise HTTPException(400, str(exc))
    return job.public()


@router.get("/jobs")
def list_jobs(batch: Optional[str] = Query(None, max_length=40), all: bool = False,
              limit: int = Query(20, ge=1, le=200), brief: bool = False) -> list[dict[str, Any]]:
    """Recent jobs, newest first (``limit``, or every saved one with ``all``); ``batch`` = only that batch,
    oldest first (the order the links were pasted). ``brief`` drops the lines (``lines`` = their count) —
    the "Xem tất cả" list only needs names, states and dates."""
    dub.load_jobs()
    if batch:
        return [j.public() for j in sorted((j for j in dub.JOBS.values() if j.batch_id == batch), key=lambda j: j.started_at)]
    dub.backfill_snapshots()
    jobs = sorted(dub.JOBS.values(), key=lambda j: j.started_at, reverse=True)
    picked = jobs if all else jobs[:limit]
    if brief:
        return [j.public() | {"segments": [], "lines": len(j.segments)} for j in picked]
    return [j.public() for j in picked]


def _job(job_id: str) -> dub.Job:
    job = dub.find_job(job_id)  # job.json on this machine, else the snapshot its clip keeps
    if job is None:
        raise HTTPException(404, "Không thấy việc lồng tiếng này (thư mục làm việc đã bị xoá và clip không còn bản lưu)")
    return job


MAX_IDENTIFY_BYTES = 2 * 1024 * 1024 * 1024


@router.post("/identify")
async def identify_video(file: UploadFile = File(...)) -> dict[str, Any]:
    """"📂 Mở lại video đã làm": a video downloaded from this tool → the project that made it.
    The file is only read (hashed + its tag), never kept."""
    import asyncio
    import hashlib
    import os
    import tempfile

    fd, tmp = tempfile.mkstemp(prefix="flowboard_identify_", suffix=Path(file.filename or "x.mp4").suffix or ".mp4")
    h = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_IDENTIFY_BYTES:
                    raise HTTPException(413, "Video lớn hơn 2 GB")
                h.update(chunk)
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "File rỗng")
        found = await asyncio.to_thread(dub.identify, Path(tmp), sha256=h.hexdigest())
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if found is None:
        raise HTTPException(404, "Không nhận ra video này — chỉ mở lại được video tải về từ tool (bản tải lại từ TikTok / "
                                 "Facebook hay đã qua CapCut, Zalo bị nén lại nên không còn giống). Dùng file đã tải ở nút ⬇ Tải.")
    if found["kind"] == "dub":
        return {"kind": "dub", "via": found["via"], "job": found["job"].public()}
    return {"kind": "clip", "board_id": found["board_id"], "name": found["name"]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    return _job(job_id).public()


@router.post("/jobs/{job_id}/render")
async def render(job_id: str, body: RenderBody) -> dict[str, Any]:
    job = _job(job_id)
    try:
        sent = body.model_dump(exclude_unset=True)
        dub.render_job(job, lines=body.lines, voice=body.voice, style=body.style, keep_bgm=body.keep_bgm,
                       name=body.name, layout=body.layout, engine=body.engine, timings=body.timings, looks=body.looks,
                       highlights=body.highlights,
                       **({"channel_id": body.channel_id} if "channel_id" in sent else {}))
    except dub.DubError as exc:
        raise HTTPException(400, str(exc))
    return job.public()


class PickBody(BaseModel):
    # the lines as they stand in the editor (unsaved edits included); None = the job's own
    lines: Optional[list[str]] = Field(default=None, max_length=2000)
    timings: Optional[list[list[float]]] = Field(default=None, max_length=2000)


@router.post("/jobs/{job_id}/highlights/pick")
async def pick_highlights(job_id: str, body: PickBody) -> dict[str, Any]:
    """"✨ AI chọn chữ quan trọng" in the editor: the key moments for the lines, without rendering.
    → {points: [{at, words, line}], picked: "ai" | "fallback"}"""
    import asyncio
    import copy

    job = _job(job_id)
    probe = copy.copy(job)
    probe.segments = [copy.copy(s) for s in job.segments]
    if body.lines is not None and len(body.lines) == len(probe.segments):
        for seg, line in zip(probe.segments, body.lines):
            seg.text = str(line or "").strip()
    if body.timings is not None and len(body.timings) == len(probe.segments):
        for seg, (a, b) in zip(probe.segments, body.timings):
            seg.start, seg.end = float(a), float(b)
    points, how = await asyncio.to_thread(dub.pick_highlights, probe)
    return {"points": points, "picked": how}


_MASCOT_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
MAX_MASCOT_BYTES = 10 * 1024 * 1024


@router.post("/mascot", status_code=201)
async def upload_mascot(file: UploadFile = File(...)) -> dict[str, Any]:
    """An image or animated GIF for the dancing sticker (services/dub_decor):
    stored on this machine as an image Asset, never sent to Flow."""
    import uuid

    from flowboard.db import get_session
    from flowboard.db.models import Asset
    from flowboard.services import media as media_service

    mime = (file.content_type or "").lower().split(";")[0].strip()
    ext = _MASCOT_EXT.get(mime) or (Path(file.filename or "").suffix.lower() if Path(file.filename or "").suffix.lower() in _MASCOT_EXT.values() else None)
    if ext is None:
        raise HTTPException(415, "Chỉ nhận ảnh PNG / JPG / WEBP hoặc GIF động")
    raw = await file.read(MAX_MASCOT_BYTES + 1)
    if not raw:
        raise HTTPException(400, "File rỗng")
    if len(raw) > MAX_MASCOT_BYTES:
        raise HTTPException(413, "Ảnh / GIF lớn hơn 10 MB")
    media_id = uuid.uuid4().hex
    media_service.MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = media_service.MEDIA_CACHE_DIR / f"{media_id}{ext}"
    path.write_bytes(raw)
    with get_session() as s:
        s.add(Asset(kind="image", uuid_media_id=media_id, local_path=str(path),
                    mime=next(m for m, e in _MASCOT_EXT.items() if e == ext)))
        s.commit()
    return {"media_id": media_id, "url": f"/media/{media_id}", "animated": ext == ".gif"}


# ── frames & stickers: AI chat, background removal, favourites ─────────────

class DecorChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=600)
    history: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    frame: Optional[dict[str, Any]] = None
    mascot: Optional[dict[str, Any]] = None
    orientation: str = "portrait"


@router.post("/decor/chat")
async def decor_chat(body: DecorChatBody) -> dict[str, Any]:
    """"💬 Nhờ AI": the AI designs the frame / sticker (services/decor_ai); the
    browser draws any picture it asks for with Flow, then cuts the sticker out."""
    from flowboard.db import get_session
    from flowboard.db.models import DecorPreset
    from flowboard.services import decor_ai
    from sqlmodel import select

    with get_session() as s:
        presets = [{"kind": p.kind, "name": p.name, "data": dict(p.data or {})}
                   for p in s.exec(select(DecorPreset).order_by(DecorPreset.uses.desc(), DecorPreset.id.desc()).limit(12)).all()]  # type: ignore[union-attr]
    try:
        return await decor_ai.chat(body.message, history=body.history, frame=body.frame, mascot=body.mascot,
                                   orientation=body.orientation if body.orientation in ("portrait", "landscape", "square") else "portrait",
                                   presets=presets)
    except decor_ai.DecorAIError as exc:
        raise HTTPException(502, str(exc))


class CutoutBody(BaseModel):
    media_id: str = Field(min_length=8, max_length=64)


@router.post("/decor/cutout", status_code=201)
async def decor_cutout(body: CutoutBody) -> dict[str, Any]:
    """A sticker picture without its plain background (a new PNG media).
    A picture Flow just drew is not on this machine yet: fetch it first."""
    import asyncio
    import uuid

    from flowboard.db import get_session
    from flowboard.db.models import Asset
    from flowboard.services import dub_decor
    from flowboard.services import media as media_service

    src = media_service.cached_path(body.media_id)
    if not src or not Path(src).is_file():
        fetched = await media_service.fetch_and_cache(body.media_id)
        src = fetched[2] if fetched else None
    if not src or not Path(src).is_file():
        raise HTTPException(404, "Không tải được ảnh này về máy (Flow chưa trả ảnh?)")
    media_id = uuid.uuid4().hex
    dst = media_service.MEDIA_CACHE_DIR / f"{media_id}.png"
    try:
        await asyncio.to_thread(dub_decor.cutout, Path(src), dst)
    except Exception as exc:  # noqa: BLE001 — a picture Pillow cannot read
        raise HTTPException(422, f"Không tách nền được: {exc}")
    with get_session() as s:
        s.add(Asset(kind="image", uuid_media_id=media_id, local_path=str(dst), mime="image/png"))
        s.commit()
    return {"media_id": media_id, "url": f"/media/{media_id}"}


def _look_preset(preset_id: Optional[int]) -> Optional[dict[str, Any]]:
    """The saved look to start a job with (None = the defaults). A missing id is an error, not a silent default."""
    if not preset_id:
        return None
    from flowboard.db import get_session
    from flowboard.db.models import DecorPreset

    with get_session() as s:
        p = s.get(DecorPreset, preset_id)
        if p is None or p.kind != "look":
            raise HTTPException(404, "Không thấy mẫu chỉnh sửa này (đã xoá?) — chọn mẫu khác hoặc để trống.")
        p.uses = (p.uses or 0) + 1
        s.add(p)
        s.commit()
        return dub.normalize_look_preset(p.data)


class PresetBody(BaseModel):
    kind: str = Field(pattern="^(frame|mascot|look)$")
    name: str = Field(default="", max_length=60)
    data: dict[str, Any]
    thumb: str = Field(default="", max_length=64)


def _preset_row(p: Any) -> dict[str, Any]:
    return {"id": p.id, "kind": p.kind, "name": p.name, "data": dict(p.data or {}), "thumb": p.thumb or "",
            "uses": p.uses, "created_at": p.created_at.isoformat() if p.created_at else None}


@router.get("/decor/presets")
def list_presets(kind: Optional[str] = None) -> list[dict[str, Any]]:
    from flowboard.db import get_session
    from flowboard.db.models import DecorPreset
    from sqlmodel import select

    with get_session() as s:
        q = select(DecorPreset).order_by(DecorPreset.uses.desc(), DecorPreset.id.desc())  # type: ignore[union-attr]
        if kind in ("frame", "mascot", "look"):
            q = q.where(DecorPreset.kind == kind)
        else:
            q = q.where(DecorPreset.kind != "look")  # the decor panel lists frames + stickers only
        return [_preset_row(p) for p in s.exec(q).all()]


class DefaultLookBody(BaseModel):
    id: Optional[int] = None


@router.get("/decor/presets/default")
def get_default_look() -> dict[str, Any]:
    """The look preset new dubbing jobs start with (``{id}``, None = plain defaults)."""
    from flowboard.db import get_session
    from flowboard.db.models import AppSetting, DecorPreset

    with get_session() as s:
        row = s.get(AppSetting, dub.LOOK_PRESET_KEY)
        pid = int(row.value) if row and row.value.isdigit() else None
        p = s.get(DecorPreset, pid) if pid else None
        return {"id": pid if p is not None and p.kind == "look" else None}


@router.put("/decor/presets/default")
def set_default_look(body: DefaultLookBody) -> dict[str, Any]:
    from flowboard.db import get_session
    from flowboard.db.models import AppSetting, DecorPreset

    with get_session() as s:
        if body.id:
            p = s.get(DecorPreset, body.id)
            if p is None or p.kind != "look":
                raise HTTPException(404, "Không thấy mẫu này")
        row = s.get(AppSetting, dub.LOOK_PRESET_KEY)
        if row is None:
            row = AppSetting(key=dub.LOOK_PRESET_KEY, value="")
        row.value = str(body.id or "")
        s.add(row)
        s.commit()
    return {"id": body.id or None}


@router.post("/decor/presets", status_code=201)
def save_preset(body: PresetBody) -> dict[str, Any]:
    """"★ Lưu": keep this frame / sticker (normalised) for later."""
    from flowboard.db import get_session
    from flowboard.db.models import DecorPreset
    from flowboard.services import dub_decor

    if body.kind == "look":
        data = dub.normalize_look_preset(body.data)
        lay = data["layout"]
        thumb = body.thumb or ((lay.get("mascot") or {}).get("media_id") or (lay.get("frame") or {}).get("bg_image") or "")
    else:
        data = dub_decor.normalize_frame(body.data) if body.kind == "frame" else dub_decor.normalize_mascot(body.data)
        if not data:
            raise HTTPException(400, "Chưa có gì để lưu" if body.kind == "frame" else "Nhân vật chưa có ảnh")
        thumb = body.thumb or (data.get("bg_image") or "" if body.kind == "frame" else data.get("media_id") or "")
    with get_session() as s:
        p = DecorPreset(kind=body.kind, name=(body.name or {"frame": "Khung", "mascot": "Nhân vật", "look": "Mẫu"}[body.kind]).strip()[:60],
                        data=data, thumb=thumb)
        s.add(p)
        s.commit()
        s.refresh(p)
        return _preset_row(p)


@router.post("/decor/presets/{preset_id}/use")
def use_preset(preset_id: int) -> dict[str, Any]:
    from flowboard.db import get_session
    from flowboard.db.models import DecorPreset

    with get_session() as s:
        p = s.get(DecorPreset, preset_id)
        if p is None:
            raise HTTPException(404, "Không thấy mẫu này")
        p.uses = (p.uses or 0) + 1
        s.add(p)
        s.commit()
        s.refresh(p)
        return _preset_row(p)


@router.delete("/decor/presets/{preset_id}")
def delete_preset(preset_id: int) -> dict[str, Any]:
    from flowboard.db import get_session
    from flowboard.db.models import DecorPreset

    with get_session() as s:
        p = s.get(DecorPreset, preset_id)
        if p is None:
            raise HTTPException(404, "Không thấy mẫu này")
        s.delete(p)
        s.commit()
    return {"ok": True}


@router.get("/jobs/{job_id}/nosub")
def nosub(job_id: str) -> FileResponse:
    """Remotion engine: the dubbed video without subtitles — what the live
    <Player> preview plays under the subtitles it draws itself."""
    job = _job(job_id)
    path = (job.work / "nosub.mp4") if job.work else None
    if path is None or not path.is_file():
        raise HTTPException(404, "Chưa có bản video không phụ đề cho job này")
    return FileResponse(str(path), media_type="video/mp4")


# ── timeline editor: what the preview plays and draws ──────────────────────

@router.get("/jobs/{job_id}/voice")
def voice_track(job_id: str) -> FileResponse:
    """The Vietnamese voice track (synced to the source video in the editor)."""
    job = _job(job_id)
    path = (job.work / "voice.wav") if job.work else None
    if path is None or not path.is_file():
        raise HTTPException(404, "Chưa có giọng đọc")
    return FileResponse(str(path), media_type="audio/wav", headers={"Cache-Control": "no-cache"})


@router.get("/jobs/{job_id}/bgm")
def bgm_track(job_id: str) -> FileResponse:
    job = _job(job_id)
    path = (job.work / "bgm.wav") if job.work else None
    if path is None or not path.is_file() or not job.keep_bgm:
        raise HTTPException(404, "Không giữ nhạc nền")
    return FileResponse(str(path), media_type="audio/wav")


@router.get("/jobs/{job_id}/filmstrip.jpg")
async def filmstrip(job_id: str) -> FileResponse:
    import asyncio

    job = _job(job_id)
    try:
        path = await asyncio.to_thread(dub.filmstrip, job)
    except dub.DubError as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(str(path), media_type="image/jpeg")


@router.get("/jobs/{job_id}/wave.png")
async def wave(job_id: str) -> FileResponse:
    import asyncio

    job = _job(job_id)
    try:
        path = await asyncio.to_thread(dub.waveform, job)
    except dub.DubError as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(str(path), media_type="image/png", headers={"Cache-Control": "no-cache"})


class DeleteJobsBody(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


@router.post("/jobs/delete")
def delete_jobs(body: DeleteJobsBody) -> dict[str, Any]:
    """Take jobs off the list (their work folders go too); exported videos, sources and clips stay."""
    deleted, skipped = dub.delete_jobs(body.ids)
    return {"deleted": deleted, "skipped": skipped}


@router.post("/jobs/{job_id}/stop")
def stop(job_id: str) -> dict[str, Any]:
    job = _job(job_id)
    if job.status in ("queued", "running", "rendering"):
        job.stop = True
    return job.public()


# ── "📚 Thư viện link": links imported from .txt / .md files, queued for dubbing (services/dub_links) ──

class LinkFile(BaseModel):
    name: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=dub_links.MAX_TEXT_CHARS)


class LinkImportBody(BaseModel):
    files: list[LinkFile] = Field(min_length=1, max_length=dub_links.MAX_FILES)


class LinkIdsBody(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=2000)


class LinkQueueBody(LinkIdsBody):
    voice: str = tts.DEFAULT_VOICE
    keep_bgm: bool = False
    style: str = "box_yellow"
    engine: str = "ass"
    channel_id: Optional[int] = None
    auto_render: bool = True
    look_preset_id: Optional[int] = None


@router.get("/links")
def list_links() -> dict[str, Any]:
    """Every library link with what it has become (new / waiting / running / review / done / error)."""
    dub_links.feed_quietly()  # after a restart the queue picks up again as soon as the library is looked at
    return dub_links.library()


@router.post("/links/import")
def import_links(body: LinkImportBody) -> dict[str, Any]:
    try:
        return dub_links.import_texts([f.model_dump() for f in body.files])
    except dub_links.LinkError as exc:
        raise HTTPException(400, str(exc))


@router.post("/links/queue")
def queue_links(body: LinkQueueBody) -> dict[str, Any]:
    """Queue links for dubbing with these options; they start one after another (one waits while one runs)."""
    look = _look_preset(body.look_preset_id)
    try:
        engine = dub._check_engine(look["engine"] if look else body.engine)
        options: dict[str, Any] = {"voice": body.voice, "keep_bgm": body.keep_bgm, "engine": engine,
                                   "style": dub._style_for(engine, look["style"] if look else body.style),
                                   "channel_id": body.channel_id, "auto_render": body.auto_render}
        if look:
            options["layout"], options["highlights"] = look["layout"], look["highlights"]
        return dub_links.queue(body.ids, options)
    except (dub_links.LinkError, dub.DubError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/links/unqueue")
def unqueue_links(body: LinkIdsBody) -> dict[str, Any]:
    return {"unqueued": dub_links.unqueue(body.ids)}


@router.post("/links/delete")
def delete_links(body: LinkIdsBody) -> dict[str, Any]:
    """Out of the library only — the dubbed videos and clips made from these links stay."""
    return {"deleted": dub_links.delete(body.ids)}
