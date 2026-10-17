"""The "Xuất video" node: join clips in order, optionally smooth to 60 fps.

Joining is ``video_concat.concat_video_assets``. Smoothing is frame
interpolation after the join: Veo renders 24 fps and has no other rate, so
60 fps can only come from synthesising the in-between frames. ffmpeg's
``minterpolate`` (motion-compensated) does that on the CPU at roughly
15 s of work per second of 720p footage; the encode goes through NVENC
when the build has it. A RIFE path (GPU, better edges) can slot in here
later — BUGLOG FB-017.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Optional

from flowboard import config
from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.services import video_concat

logger = logging.getLogger(__name__)

# 24 s of footage ≈ 6 min on a laptop CPU; leave headroom for longer joins.
_SMOOTH_TIMEOUT_S = 1800
_MINTERPOLATE = "minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"


@lru_cache(maxsize=1)
def _nvenc_available(ffmpeg: str) -> bool:
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                             timeout=20, check=False).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "h264_nvenc" in out


def _encode_args(ffmpeg: str) -> list[str]:
    if _nvenc_available(ffmpeg):
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]


def smooth_to_60fps(src: Path, dst: Path) -> Optional[str]:
    """Interpolate ``src`` to 60 fps into ``dst``. None on success, else why."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return "ffmpeg_not_found"
    cmd = [ffmpeg, "-y", "-i", str(src), "-vf", _MINTERPOLATE,
           *_encode_args(ffmpeg), "-pix_fmt", "yuv420p",
           "-c:a", "copy", "-movflags", "+faststart", str(dst)]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              timeout=_SMOOTH_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return f"timed out after {_SMOOTH_TIMEOUT_S}s"
    except OSError as exc:
        return f"could not launch ffmpeg: {exc}"
    if proc.returncode != 0 or not dst.is_file():
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip()
        return tail[-500:] if tail else f"exit code {proc.returncode}"
    return None


def export_video(asset_ids: list[int], *, smooth60: bool) -> tuple[Optional[str], Optional[str]]:
    """Join ``asset_ids`` in order (+ optional 60 fps). Returns (media_id, error)."""
    joined_id, err = video_concat.concat_video_assets(asset_ids)
    if err or joined_id is None:
        return None, err or "concat_failed"
    with get_session() as s:
        joined = s.get(Asset, joined_id)
        joined_media, joined_path = joined.uuid_media_id, Path(joined.local_path)
    if not smooth60:
        return joined_media, None

    out_dir = config.STORAGE_DIR / "media"
    out_path = out_dir / f"smooth60_{uuid.uuid4().hex}.mp4"
    err = smooth_to_60fps(joined_path, out_path)
    if err:
        # The join itself is fine; hand it back rather than lose the work.
        logger.warning("video_export: 60 fps smoothing failed (%s); returning the 24 fps join", err[:160])
        return joined_media, None
    with get_session() as s:
        row = Asset(kind="video", node_id=None, uuid_media_id=uuid.uuid4().hex,
                    local_path=str(out_path), mime="video/mp4")
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.uuid_media_id, None
