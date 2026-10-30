"""A still picture of a video, for cards that have none ("Clip của tôi",
Lịch đăng, Hôm nay): a clip that only has its finished video — a dubbed
clip, a video brought back from CapCut, an uploaded one — showed an empty
🎬 tile. One frame from early in the video (past a fade-in), 480 px wide,
made once with ffmpeg and kept next to the account's media
(``<account>/posters/<media id>.jpg``).
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from flowboard.services import media as media_service
from flowboard.services.video_export import probe_clip

logger = logging.getLogger(__name__)

WIDTH = 480
_LOCKS: dict[str, asyncio.Lock] = {}


def poster_file(media_id: str) -> Path:
    # read at call time: the media folder moves with the account that is open (accounts.activate)
    return media_service.MEDIA_CACHE_DIR.parent / "posters" / f"{media_id}.jpg"


def frame_time(duration: float) -> float:
    """Where to take the frame: a tenth in, between 0.5 s and 3 s (past a fade from black, still the opening)."""
    if duration <= 0:
        return 0.0
    return round(min(max(duration * 0.1, 0.5), 3.0, duration / 2), 2)


def _grab(video: Path, out: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return False
    info = probe_clip(video)
    if info is None:  # not a video (or no video stream)
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.jpg")
    cmd = [ffmpeg, "-v", "error", "-y", "-ss", str(frame_time(info.duration)), "-i", str(video),
           "-frames:v", "1", "-vf", f"scale={WIDTH}:-2", "-q:v", "4", str(tmp)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, check=True)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        logger.warning("poster: ffmpeg failed for %s: %s", video.name, exc)
        tmp.unlink(missing_ok=True)
        return False
    if not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(out)
    return True


async def poster_for(media_id: str) -> Optional[Path]:
    """The poster of a video media id — made on first ask (fetching the video when this machine lacks it)."""
    out = poster_file(media_id)
    if out.is_file():
        return out
    lock = _LOCKS.setdefault(media_id, asyncio.Lock())
    async with lock:
        if out.is_file():
            return out
        video = media_service.cached_path(media_id)
        if video is None and not media_service.recently_missed(media_id):
            got = await media_service.fetch_and_cache(media_id)
            video = got[2] if got else None
            if video is None:
                media_service.remember_miss(media_id)
        if video is None:
            return None
        ok = await asyncio.to_thread(_grab, Path(video), out)
    _LOCKS.pop(media_id, None)
    return out if ok else None
