"""60 fps made in the background, as soon as each clip lands (7/11).

"Mượt 60 fps" interpolates every clip of the join (video_export.smooth_sources, ~2.5 min for 4 clips of 8 s on this
machine, cached per clip). The clips arrive one by one during step 4, minutes before the seller presses "Ghép" — so when
a clip's board wants 60 fps (its export node has it on, or, before step 5 made that node, the account's last choice
``ui_prefs.smooth60``), the clip is fetched, its Flow stamp taken out (the copy the export uses) and smoothed right
away, below normal priority. The join then finds the smoothed copies ready and only lays the voice on.

Turning 60 fps on later (step 4 / 5) warms the board's clips the same way (:func:`warm_board`), and
:func:`board_status` says how many are ready for the line under the checkbox. A warm-up never blocks or fails an
export: the export smooths whatever is not ready itself (the per-file lock in video_export makes it wait for a clip
already being smoothed instead of doing it twice).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from sqlmodel import select

from flowboard.db import get_session, has_engine
from flowboard.db.models import AppSetting, Node

logger = logging.getLogger(__name__)

_pool: Optional[ThreadPoolExecutor] = None
_jobs: dict[str, Future] = {}
_guard = threading.Lock()
#: the video node types whose clips get warmed (a clip of the board's join)
VIDEO_TYPES = ("video",)


def _executor() -> ThreadPoolExecutor:
    global _pool
    from flowboard.services.video_export import SMOOTH_PARALLEL

    with _guard:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=SMOOTH_PARALLEL, thread_name_prefix="smooth60")
        return _pool


def account_wants() -> bool:
    """The account's last 60 fps choice (``ui_prefs.smooth60``), for a board whose step 5 has not been opened yet."""
    with get_session() as s:
        row = s.get(AppSetting, "ui_prefs")
    try:
        return bool(row and json.loads(row.value).get("smooth60") is True)
    except ValueError:
        return False


def board_wants(board_id: int) -> bool:
    """Does this board's join want 60 fps: its export node says so, else (no export node yet) the account's choice."""
    with get_session() as s:
        exports = s.exec(select(Node).where(Node.board_id == board_id, Node.type == "export")).all()
    if exports:
        return any((n.data or {}).get("smooth60") is True for n in exports)
    return account_wants()


def _board_media(board_id: int) -> list[str]:
    """The media ids of the board's rendered clips (its video nodes)."""
    with get_session() as s:
        nodes = s.exec(select(Node).where(Node.board_id == board_id, Node.type.in_(VIDEO_TYPES))).all()  # type: ignore[union-attr]
    out = []
    for n in nodes:
        mid = (n.data or {}).get("mediaId")
        if isinstance(mid, str) and mid and mid not in out:
            out.append(mid)
    return out


def _local(media_id: str) -> Optional[Path]:
    """The clip on this machine — fetched (from Flow / the account's cloud copy) when it is not here yet."""
    from flowboard.services import media as media_service

    path = media_service.cached_path(media_id)
    if path is None:
        try:
            asyncio.run(media_service.fetch_and_cache(media_id))
        except Exception as exc:  # noqa: BLE001 — try again at export time
            logger.info("smooth60: could not fetch %s: %s", media_id, exc)
            return None
        path = media_service.cached_path(media_id)
    return path


def _make(media_id: str) -> Optional[Path]:
    from flowboard.services import media as media_service, video_export, video_watermark

    src = _local(media_id)
    if src is None or not src.is_file():
        return None
    clean = video_watermark.cleaned_copy(src, media_service.MEDIA_CACHE_DIR / "clean")  # the copy the export uses
    out, err = video_export.smoothed_copy(clean, media_service.MEDIA_CACHE_DIR / "smooth60", low_priority=True)
    if err:
        logger.warning("smooth60: warm-up of %s failed: %s", media_id, err[:160])
        return None
    logger.info("smooth60: %s ready for the join (%s)", media_id, out.name)
    return out


def warm(media_id: str) -> None:
    """Smooth one clip in the background (once; a second ask while it runs or after it is done is a no-op)."""
    with _guard:
        job = _jobs.get(media_id)
        if job is not None and (not job.done() or job.exception() is None and job.result() is not None):
            return
    fut = _executor().submit(_make, media_id)
    with _guard:
        _jobs[media_id] = fut


def after_clip(node_id: Optional[int], media_id: Optional[str]) -> None:
    """A Flow clip just finished for this node (the worker): warm it when its board wants 60 fps."""
    if not node_id or not media_id or not has_engine():
        return
    try:
        with get_session() as s:
            node = s.get(Node, node_id)
            board_id = node.board_id if node is not None and node.type in VIDEO_TYPES else None
        if board_id is not None and board_wants(board_id):
            warm(media_id)
    except Exception as exc:  # noqa: BLE001 — a warm-up is never in the way of the render
        logger.warning("smooth60: not started for node %s: %s", node_id, exc)


def warm_board(board_id: int) -> dict[str, Any]:
    """60 fps was just turned on for this board: every clip it has is warmed. → :func:`board_status`."""
    for media_id in _board_media(board_id):
        warm(media_id)
    return board_status(board_id)


def board_status(board_id: int) -> dict[str, Any]:
    """How many of the board's clips already have their 60 fps copy (``ready``), are being made (``running``), of
    ``total``."""
    from flowboard.services import media as media_service, video_export, video_watermark

    ids = _board_media(board_id)
    ready = running = 0
    for media_id in ids:
        path = media_service.cached_path(media_id)
        clean = video_watermark.known_clean(path, media_service.MEDIA_CACHE_DIR / "clean") if path else None
        if clean is not None and clean.is_file() and video_export.smoothed_path(clean, media_service.MEDIA_CACHE_DIR / "smooth60").is_file():
            ready += 1
            continue
        with _guard:
            job = _jobs.get(media_id)
        if job is not None and not job.done():
            running += 1
    return {"total": len(ids), "ready": ready, "running": running}
