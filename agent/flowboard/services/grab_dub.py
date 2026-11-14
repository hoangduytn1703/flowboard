""""🎙 Lồng tiếng ngay" on the grab list: the picked videos are downloaded (when not here yet) and handed to the
dubbing queue by the agent — one click on the list, no second page, and it goes on when the page is left.

One ``Item`` per video on its way: ``download`` (the file is coming; a passing failure is retried by the downloader)
→ ``wait`` (the dubbing queue is full: handed over as soon as there is room) → handed over (the item is dropped: the
dub job itself is what ``channel_grab.work_of_videos`` shows from then on) or ``failed`` (kept so the card says why).
A video that fails never holds the others. In memory: a restart forgets the videos not handed over yet (the ones
already in the dubbing queue are dub jobs — saved).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from flowboard.db import get_session
from flowboard.db.models import GrabVideo
from flowboard.services import channel_grab as grab

logger = logging.getLogger(__name__)

MAX_AT_ONCE = 30
#: a failed hand-over stays on the card this long
KEEP_FAILED_S = 6 * 3600


class GrabDubError(RuntimeError):
    pass


@dataclass
class Item:
    video_id: int
    owner: str
    options: dict[str, Any]
    status: str = "download"  # download | wait | failed
    error: str = ""
    stop: bool = False
    at: float = field(default_factory=time.time)


ITEMS: dict[tuple[str, int], Item] = {}
_LOCK = threading.Lock()
_WORKER: Optional[threading.Thread] = None


def clean_options(raw: dict[str, Any]) -> dict[str, Any]:
    """What a dub job is started with, checked once for the whole lot (a wrong voice fails here, not ten times)."""
    from flowboard.services import dub, tts

    voice = str(raw.get("voice") or tts.DEFAULT_VOICE)
    if not tts.is_voice(voice):
        raise GrabDubError("Giọng đọc không hợp lệ — chọn lại giọng")
    mode = dub.normalize_mode(raw.get("mode") or "dub")
    look = None
    if raw.get("look_preset_id"):
        try:
            look = dub.look_preset(int(raw["look_preset_id"]))
        except dub.DubError as exc:
            raise GrabDubError(str(exc)) from exc
    st = dub.status()
    if not st["available"]:
        raise GrabDubError(st.get("reason") or "Lồng tiếng chưa dùng được trên máy này")
    return {"voice": voice, "mode": mode, "keep_bgm": bool(raw.get("keep_bgm")) and bool(st.get("separate")),
            "sub_lang": dub.normalize_sub_lang(raw.get("sub_lang") or "vi"), "look": look,
            "translator": dub.normalize_translator(raw.get("translator") or dub.DEFAULT_TRANSLATOR),
            "channel_id": raw.get("channel_id"), "style": str(raw.get("style") or "box_yellow"),
            "engine": str(raw.get("engine") or "ass")}


def start(ids: list[int], options: dict[str, Any]) -> dict[str, int]:
    """Send the videos to be dubbed. → ``{queued, skipped}`` (skipped = already on their way)."""
    global _WORKER
    ids = list(dict.fromkeys(int(i) for i in ids))
    if not ids:
        raise GrabDubError("Chọn ít nhất một video")
    if len(ids) > MAX_AT_ONCE:
        raise GrabDubError(f"Tối đa {MAX_AT_ONCE} video một lượt")
    opts = clean_options(options)
    owner = grab._owner()
    with get_session() as db:
        from sqlmodel import select

        known = {int(v.id) for v in db.exec(select(GrabVideo).where(GrabVideo.id.in_(ids))).all()}  # type: ignore[union-attr,arg-type]
    queued = skipped = 0
    with _LOCK:
        for vid in ids:
            cur = ITEMS.get((owner, vid))
            if vid not in known or (cur is not None and cur.status in ("download", "wait")):
                skipped += 1
                continue
            ITEMS[(owner, vid)] = Item(video_id=vid, owner=owner, options=opts)
            queued += 1
        if queued and (_WORKER is None or not _WORKER.is_alive()):
            _WORKER = threading.Thread(target=_work, name="grab-dub", daemon=True)
            _WORKER.start()
    return {"queued": queued, "skipped": skipped}


def stop_all() -> dict[str, int]:
    """"Dừng tất cả": the videos not handed over yet are dropped (their downloads stopped), the dub jobs started
    from the grab list that still run or wait are stopped."""
    from flowboard.services import dub

    owner, dropped = grab._owner(), []
    with _LOCK:
        for key, it in list(ITEMS.items()):
            if it.owner == owner and it.status in ("download", "wait"):
                it.stop = True
                dropped.append(it.video_id)
                ITEMS.pop(key, None)
    if dropped:
        grab.stop_downloads(dropped)
    stopped = 0
    work = grab.work_of_videos()
    for view in work.values():
        d = view.get("dub") or {}
        job = dub.JOBS.get(str(d.get("id") or ""))
        if d.get("state") == "running" and job is not None:
            dub.stop_job(job)
            stopped += 1
    return {"dropped": len(dropped), "stopped": stopped}


def _work() -> None:
    while True:
        with _LOCK:
            live = [it for it in ITEMS.values() if it.status in ("download", "wait") and not it.stop]
            cutoff = time.time() - KEEP_FAILED_S
            for key in [k for k, it in ITEMS.items() if it.status == "failed" and it.at < cutoff]:
                ITEMS.pop(key, None)
        if not live:
            return
        for it in sorted(live, key=lambda x: x.at):
            try:
                _step(it)
            except Exception as exc:  # noqa: BLE001 — one video never ends the others
                logger.exception("grab_dub: video %s crashed", it.video_id)
                _fail(it, f"{type(exc).__name__}: {exc}")
        time.sleep(0.7)


def _fail(it: Item, error: str) -> None:
    it.status, it.error, it.at = "failed", error[:400], time.time()


def _step(it: Item) -> None:
    from flowboard.services import dub

    if it.owner != grab._owner():
        _fail(it, "Đã đổi tài khoản — chọn lại video")
        return
    with get_session() as db:
        v = db.get(GrabVideo, it.video_id)
        if v is None:
            _fail(it, "Video đã bị xoá khỏi danh sách")
            return
        media_id, title, error = v.media_id, v.title or "", v.download_error or ""
    if grab.local_media(media_id) is None:
        d = grab.DOWNLOADS.get((it.owner, it.video_id))
        if d is not None and d.status in ("queued", "running"):
            it.status = "download"
            return
        if d is not None and d.status == "error" and d.error == grab.STOPPED and d.started_at >= it.at - 1:
            with _LOCK:  # the seller stopped this download: not a failure, the video just leaves the lot
                ITEMS.pop((it.owner, it.video_id), None)
            return
        if d is not None and d.status == "error" and d.started_at >= it.at - 1:
            _fail(it, d.error or error or "Không tải được video")  # the downloader already tried a few times
            return
        it.status = "download"
        grab.download([it.video_id])
        return
    o = it.options
    look = o.get("look")
    try:
        job = dub.start_job(url=None, source_media_id=media_id, voice=o["voice"], keep_bgm=o["keep_bgm"],
                            style=look["style"] if look else o["style"], engine=look["engine"] if look else o["engine"],
                            channel_id=o.get("channel_id"), name="", title=title[:grab.TITLE_MAX], auto_render=True,
                            translator=o["translator"], mode=o["mode"], sub_lang=o["sub_lang"],
                            layout=look["layout"] if look else None, highlights=look["highlights"] if look else None)
    except dub.DubError as exc:
        if "Hàng đợi" in str(exc):  # the dubbing queue is full: it waits here for room
            it.status = "wait"
            return
        _fail(it, str(exc))
        return
    logger.info("grab_dub: video %s → dub job %s", it.video_id, job.id)
    try:
        grab.mark_used([it.video_id], "dub")
    except Exception:  # noqa: BLE001 — the mark is a nicety
        pass
    with _LOCK:
        ITEMS.pop((it.owner, it.video_id), None)


def pending_views() -> dict[int, dict[str, Any]]:
    """The videos not in the dubbing queue yet, as ``work_of_videos`` shows a tool run."""
    owner = grab._owner()
    out: dict[int, dict[str, Any]] = {}
    for it in list(ITEMS.values()):
        if it.owner != owner:
            continue
        d = grab.DOWNLOADS.get((owner, it.video_id))
        if it.status == "download":
            tries = d.tries if d is not None else 1
            waiting = d is not None and d.status == "queued"
            if d is None or d.status not in ("queued", "running"):
                phase = "Đang chuẩn bị"  # here already (or just asked for): handed over within a second
            else:
                phase = "Chờ tải về" if waiting else ("Đang tải video về" + (f" (thử lần {tries})" if tries > 1 else ""))
            view = {"state": "downloading", "phase": phase}
        elif it.status == "wait":
            view = {"state": "running", "phase": "Chờ hàng đợi lồng tiếng có chỗ", "ahead": 99}
        else:
            view = {"state": "error", "phase": "Chưa lồng tiếng được"}
        out[it.video_id] = {"id": "", "progress": 0, "error": it.error, "at": it.at, "link": "", "media_id": None,
                            "name": "", "mode": it.options.get("mode", "dub"), "ahead": None, **view}
    return out
