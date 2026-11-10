"""yt-dlp, the downloader behind every non-Douyin link (TikTok, YouTube, Instagram, Facebook, X).

The installed app does not carry it, and a friend's machine has no ``winget install yt-dlp`` (seen 10/11: "Cắt video" from a
YouTube link stopped at "yt-dlp không có trên máy"). So the agent takes, in order: ``FLOWBOARD_YTDLP``, a ``yt-dlp`` on PATH,
or its own copy in ``<data folder>/tools`` — downloaded on first need from yt-dlp's official GitHub release, checked against
the release's ``SHA2-256SUMS``. Sites (YouTube above all) change often and an old yt-dlp stops working, so its own copy
updates itself (``yt-dlp -U``) when it is older than :data:`UPDATE_AFTER_S`.

YouTube: without a JavaScript runtime yt-dlp still finds the formats (it warns this is deprecated); a ``node`` on PATH is
handed to it (only deno is used by default).
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import httpx

from flowboard import config

logger = logging.getLogger(__name__)

RELEASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
ASSETS = {"win32": "yt-dlp.exe", "linux": "yt-dlp_linux", "darwin": "yt-dlp_macos"}
#: an own copy older than this runs ``yt-dlp -U`` before the next download
UPDATE_AFTER_S = 3 * 24 * 3600

_lock = threading.Lock()


class YtdlpError(RuntimeError):
    pass


def _asset() -> Optional[str]:
    return ASSETS.get("linux" if sys.platform.startswith("linux") else sys.platform)


def tools_dir() -> Path:
    raw = os.environ.get("FLOWBOARD_TOOLS_DIR", "").strip()
    return Path(raw) if raw else Path(config.HOME or config.ROOT) / "tools"


def own_path() -> Path:
    return tools_dir() / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")


def find() -> Optional[str]:
    """The yt-dlp to run, if this machine has one already."""
    raw = os.environ.get("FLOWBOARD_YTDLP", "").strip()
    if raw and Path(raw).is_file():
        return raw
    on_path = shutil.which("yt-dlp")
    if on_path:
        return on_path
    own = own_path()
    return str(own) if own.is_file() else None


def available() -> bool:
    """yt-dlp is here, or the agent can fetch it for this system."""
    return find() is not None or _asset() is not None


def _client() -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0),
                        headers={"User-Agent": "DFlow (yt-dlp)"})


def _expected_sha256(sums: str, asset: str) -> str:
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == asset:
            return parts[0].lower()
    raise YtdlpError(f"bản phát hành yt-dlp không ghi mã kiểm tra của {asset}")


def download() -> Path:
    """Fetch the latest official yt-dlp for this system into :func:`tools_dir`, checked against SHA2-256SUMS."""
    asset = _asset()
    if asset is None:
        raise YtdlpError("yt-dlp không có bản cho hệ điều hành này")
    dest = own_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with _client() as client:
            sums = client.get(RELEASE + "SHA2-256SUMS")
            sums.raise_for_status()
            want = _expected_sha256(sums.text, asset)
            digest = hashlib.sha256()
            with client.stream("GET", RELEASE + asset) as r:
                r.raise_for_status()
                with open(part, "wb") as fh:
                    for chunk in r.iter_bytes(1 << 20):
                        fh.write(chunk)
                        digest.update(chunk)
    except httpx.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise YtdlpError(f"không tải được yt-dlp từ GitHub ({exc})") from exc
    if digest.hexdigest() != want:
        part.unlink(missing_ok=True)
        raise YtdlpError("yt-dlp tải về không khớp mã kiểm tra của bản phát hành — đã bỏ, thử lại sau")
    os.replace(part, dest)
    if sys.platform != "win32":
        dest.chmod(0o755)
    logger.info("ytdlp: downloaded %s → %s", asset, dest)
    return dest


def _refresh(path: Path) -> None:
    """``yt-dlp -U`` on our own copy when it is old; the clock restarts even when the update fails (no retry per link)."""
    try:
        if time.time() - path.stat().st_mtime < UPDATE_AFTER_S:
            return
    except OSError:
        return
    try:
        out = subprocess.run([str(path), "-U"], capture_output=True, timeout=120, check=False)
        logger.info("ytdlp: -U → %s", out.stdout.decode("utf-8", "replace").strip().splitlines()[-1:] or out.returncode)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("ytdlp: update failed: %s", exc)
    try:
        os.utime(path)
    except OSError:
        pass


def ensure() -> str:
    """The yt-dlp to run: this machine's, or our own copy (downloaded / refreshed here). Raises :class:`YtdlpError`."""
    with _lock:
        found = find()
        if found:
            if Path(found) == own_path():
                _refresh(Path(found))
            return found
        return str(download())


def js_args() -> list[str]:
    """Hand a ``node`` on PATH to yt-dlp for YouTube (it only looks for deno by itself)."""
    if shutil.which("deno") is None and shutil.which("node") is not None:
        return ["--js-runtimes", "node"]
    return []
