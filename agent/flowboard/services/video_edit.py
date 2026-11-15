"""🎞 Chỉnh sửa video — the one place where finished videos are edited, many at a time.

A video on the list is a dubbing-editor project (``dub.Job``): the one a dubbed video / a cut part already has,
or a new one made here for a file from this machine or for a clip of "Clip của tôi" (kind "cut" with
``cut.origin == "edit"``: no voice, subtitles off, nothing heard — its frame, background, text, colours,
speed… are edited and rendered like a cut part's). The list itself is the account's (AppSetting
``edit_list``, job ids, newest first). The words of an imported video are only heard (Whisper) when the
seller asks for subtitles: ``hear``.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import AppSetting, Board
from flowboard.services import dub
from flowboard.services import media as media_service
from flowboard.services.proc import Stopped
from flowboard.services.video_export import probe_clip

logger = logging.getLogger(__name__)

LIST_KEY = "edit_list"
MAX_LIST = 300
#: files / clips taken in one go
MAX_IMPORT = 30
ORIGIN = "edit"
WORKING = ("queued", "running", "rendering")


class EditError(RuntimeError):
    pass


# ── the list ─────────────────────────────────────────────────────────────────

def _ids() -> list[str]:
    with get_session() as db:
        row = db.get(AppSetting, LIST_KEY)
    try:
        raw = json.loads(row.value or "[]") if row is not None else []
    except (TypeError, ValueError):
        raw = []
    return [str(x) for x in raw if isinstance(x, str) and x][:MAX_LIST]


def _save_ids(ids: list[str]) -> list[str]:
    ids = list(dict.fromkeys(i for i in ids if i))[:MAX_LIST]
    with get_session() as db:
        row = db.get(AppSetting, LIST_KEY) or AppSetting(key=LIST_KEY, value="")
        row.value = json.dumps(ids)
        db.add(row)
        db.commit()
    return ids


def add(job_ids: list[str]) -> list[str]:
    """Put these projects on top of the list (ones already there move up); unknown ids are left out."""
    known = [i for i in dict.fromkeys(job_ids) if dub.find_job(i) is not None]
    if known:
        _save_ids(known + [i for i in _ids() if i not in known])
    return known


def is_import(job: dub.Job) -> bool:
    return job.kind == "cut" and (job.cut or {}).get("origin") == ORIGIN


def edited(job: dub.Job) -> bool:
    """It has been exported from the editor at least once (its video is no longer the one that came in)."""
    return bool(job.outputs) or (job.kind == "cut" and bool(job.media_id) and job.media_id != job.source_media_id)


def view(job: dub.Job) -> dict[str, Any]:
    return {
        "job_id": job.id, "name": job.name or job.title or "Video", "kind": job.kind, "mode": job.mode,
        "origin": "import" if is_import(job) else "cut" if job.kind == "cut" else "dub",
        "status": job.status, "phase": job.phase, "progress": job.progress, "error": job.error,
        "stopping": bool(job.stop and job.status in WORKING),
        "duration_s": job.duration_s, "width": job.width, "height": job.height,
        "media_id": job.media_id or job.source_media_id, "board_id": job.board_id,
        "lines": len(job.segments), "edited": edited(job), "started_at": job.started_at,
        "hear": hear_state(job.id),
    }


def items() -> list[dict[str, Any]]:
    """The list, newest first. A project this machine no longer has stays off it (and off the saved list)."""
    ids = _ids()
    jobs = [(i, dub.find_job(i)) for i in ids]
    alive = [i for i, j in jobs if j is not None]
    if len(alive) != len(ids):
        _save_ids(alive)
    return [view(j) for _i, j in jobs if j is not None]


# ── bringing videos in ───────────────────────────────────────────────────────

def _new_job(media_id: str, name: str, *, from_board: Optional[int] = None, channel_id: Optional[int] = None) -> dub.Job:
    path = media_service.cached_path(media_id)
    if path is None or not Path(path).is_file():
        raise EditError("Không thấy file video này trên máy.")
    info = probe_clip(Path(path))
    if info is None:
        raise EditError(f"Không đọc được video “{name or media_id}”.")
    job = dub.Job(id=uuid.uuid4().hex[:12], url=None, source_media_id=media_id, sub_lang="none")
    job.kind, job.mode = "cut", "sub"
    job.media_id = media_id
    job.name = job.title = (name or "Video").strip()[:80]
    job.cut = {"origin": ORIGIN, "index": 1, "total": 1, "start": 0.0, "end": round(float(info.duration), 3),
               "source_title": job.name, "subtitle": ""}
    if from_board:
        job.cut["from_board"] = int(from_board)
    job.channel_id = channel_id
    job.duration_s = float(info.duration)
    job.width, job.height = int(info.width), int(info.height)
    job.segments, job.voice_key, job.outputs = [], "", []
    job.status, job.phase, job.progress, job.error, job.stop = "done", "Chưa chỉnh", 100, None, False
    job.work = dub._jobs_root() / job.id
    job.work.mkdir(parents=True, exist_ok=True)
    job.src_path = Path(path)
    job.started_at = time.time()
    # no clip yet: the first export makes it (thirty files dropped in must not flood "Clip của tôi")
    job.board_id = None
    dub.JOBS[job.id] = job
    dub.persist(job)
    return job


def import_media(media: list[dict[str, Any]]) -> dict[str, Any]:
    """Videos already uploaded (``[{media_id, name}]``) → one project each, on top of the list."""
    made: list[str] = []
    errors: list[dict[str, str]] = []
    for m in media[:MAX_IMPORT]:
        media_id = str(m.get("media_id") or "").strip()
        name = Path(str(m.get("name") or "")).stem or "Video"
        try:
            made.append(_new_job(media_id, name).id)
        except EditError as exc:
            errors.append({"name": name, "error": str(exc)})
    add(made)
    return {"job_ids": made, "errors": errors}


def _job_of_board(board: Board) -> Optional[str]:
    qt = (board.data or {}).get("quicktool") or {}
    if qt.get("template_id") in ("dub", "cut_part"):
        return (qt.get("dub") or {}).get("job_id") or None
    return None


async def import_clips(board_ids: list[int]) -> dict[str, Any]:
    """Clips of "Clip của tôi": a dubbed / cut clip brings its own project; any other clip with a finished video
    gets a new one for that video (the clip itself is never changed — the export becomes a clip of its own)."""
    from flowboard.routes.exports import _final_media

    board_ids = list(dict.fromkeys(int(b) for b in board_ids))[:MAX_IMPORT]
    with get_session() as db:
        boards = {b.id: b for b in db.exec(select(Board).where(Board.id.in_(board_ids))).all()} if board_ids else {}
    # an import made earlier for the same clip is opened again rather than doubled
    dub.load_jobs()
    earlier = {int(j.cut["from_board"]): j.id for j in dub.JOBS.values() if is_import(j) and j.cut.get("from_board")}
    got: list[str] = []
    errors: list[dict[str, str]] = []
    for bid in board_ids:
        b = boards.get(bid)
        if b is None:
            continue
        jid = _job_of_board(b)
        if jid and dub.find_job(jid) is not None:
            got.append(jid)
            continue
        if bid in earlier:
            got.append(earlier[bid])
            continue
        media_id = _final_media(bid)
        if not media_id:
            errors.append({"name": b.name, "error": "Clip này chưa có video (chưa ghép / chưa xuất)."})
            continue
        if media_service.cached_path(media_id) is None:
            try:
                await media_service.fetch_and_cache(media_id)
            except Exception:  # noqa: BLE001 — reported just below as a missing file
                pass
        try:
            qt = (b.data or {}).get("quicktool") or {}
            got.append(_new_job(media_id, b.name, from_board=bid, channel_id=qt.get("channel_id")).id)
        except EditError as exc:
            errors.append({"name": b.name, "error": str(exc)})
    add(got)
    return {"job_ids": got, "errors": errors}


def remove(job_ids: list[str]) -> dict[str, Any]:
    """Off the list. Clips, exported videos and the files that came in stay; only an import that was never
    exported loses its (empty) project folder. A video being exported / heard is kept."""
    kept: list[dict[str, str]] = []
    gone: list[str] = []
    for jid in dict.fromkeys(job_ids):
        job = dub.find_job(jid)
        if job is not None and (job.status in WORKING or hear_state(jid)["state"] in ("wait", "run")):
            kept.append({"job_id": jid, "why": "đang xuất / đang nghe lời — dừng trước rồi bỏ"})
            continue
        gone.append(jid)
        if job is not None and is_import(job) and not job.board_id and not edited(job):
            dub.delete_jobs([jid])
    _save_ids([i for i in _ids() if i not in gone])
    return {"removed": gone, "kept": kept}


# ── hearing the words, when subtitles are wanted ─────────────────────────────

_HEAR: dict[str, dict[str, Any]] = {}
_HEAR_LOCK = threading.Lock()   # one video heard at a time (Whisper shares the card)


def hear_state(job_id: str) -> dict[str, Any]:
    h = _HEAR.get(job_id)
    return {"state": h["state"], "progress": h["progress"], "error": h["error"]} if h else {"state": "", "progress": 0, "error": ""}


def hear(job: dub.Job) -> dict[str, Any]:
    """Hear this video's words in the background → its lines (subtitles "the words heard"). Nothing is rendered."""
    if job.segments:
        raise EditError("Video này đã có lời rồi.")
    if job.status in WORKING:
        raise EditError("Video đang xuất — đợi xong rồi nghe lời.")
    if not dub.status().get("available"):
        raise EditError("Máy này chưa có gói lồng tiếng (AI nghe lời) — cài ở Cài đặt → 🖥 Máy này.")
    if job.src_path is None or not Path(job.src_path).is_file():
        raise EditError("Không thấy file video gốc trên máy.")
    cur = _HEAR.get(job.id)
    if cur and cur["state"] in ("wait", "run"):
        return hear_state(job.id)
    _HEAR[job.id] = {"state": "wait", "progress": 0, "error": "", "stop": False}
    threading.Thread(target=_hear_bg, args=(job,), name=f"edit-hear-{job.id}", daemon=True).start()
    return hear_state(job.id)


def hear_stop(job_id: str) -> dict[str, Any]:
    h = _HEAR.get(job_id)
    if h and h["state"] in ("wait", "run"):
        h["stop"] = True
    return hear_state(job_id)


def _whisper_lock() -> threading.Lock:
    """The cut page hears videos too: the two never run Whisper at once."""
    from flowboard.services import video_cut
    return video_cut._WHISPER_LOCK


def _hear_bg(job: dub.Job) -> None:
    h = _HEAR[job.id]
    try:
        with _HEAR_LOCK, _whisper_lock():
            if h["stop"]:
                raise Stopped()
            h["state"] = "run"
            lines, language = _transcribe(job, progress=lambda p: h.__setitem__("progress", int(p)), stop=lambda: h["stop"])
        if h["stop"]:
            raise Stopped()
        if not lines:
            h.update(state="error", error="Không nghe ra câu nào (video chỉ có nhạc / tiếng động).")
            return
        job.segments = [dub.Segment(a, b, text, text) for a, b, text in lines]
        job.language = language
        job.sub_lang = "orig"      # the words as heard; another language is picked in the editor
        dub.persist(job)
        if job.board_id:
            dub._save_board(job)   # the clip's snapshot follows (another machine reopens it with its lines)
        h.update(state="done", progress=100)
    except Stopped:
        h.update(state="", progress=0, error="")
    except Exception as exc:  # noqa: BLE001 — shown on the video's row
        if h["stop"]:
            h.update(state="", progress=0, error="")
            return
        logger.exception("edit: hearing %s failed", job.id)
        h.update(state="error", error=str(exc)[:300])


def _transcribe(job: dub.Job, *, progress: Any, stop: Any) -> tuple[list[tuple[float, float, str]], str]:
    assert job.work is not None and job.src_path is not None
    src = Path(job.src_path)
    info = probe_clip(src)
    if info is None or not info.has_audio:
        return [], ""
    job.work.mkdir(parents=True, exist_ok=True)
    wav, out = job.work / "speech16.wav", job.work / "asr.json"
    progress(0)
    dub._extract_wav(dub._ffmpeg(), src, wav, 16000, True)
    try:
        # no hint: the name of a file brought in says nothing about the words in it
        dub._runner("transcribe", str(wav), str(out), "auto", "-", "", progress=progress, stop=stop)
    finally:
        wav.unlink(missing_ok=True)
    data = json.loads(out.read_text(encoding="utf-8"))
    lines = [(round(float(x["start"]), 3), round(float(x["end"]), 3), str(x.get("text") or "").strip())
             for x in data.get("segments") or [] if float(x["end"]) > float(x["start"]) and str(x.get("text") or "").strip()]
    return lines, str(data.get("language") or "")
