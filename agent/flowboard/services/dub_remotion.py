"""Second subtitle engine for the dubbing tool: Remotion (React → Chrome →
mp4), run through ``frontend/remotion/render.mjs``.

The ffmpeg/ASS engine in :mod:`flowboard.services.dub` is untouched; a job
with ``engine == "remotion"`` gets the video + dubbed audio muxed by ffmpeg
without subtitles (``nosub.mp4``) and this module draws the subtitles and
the blur band on top. Same ``layout`` (x, y, scale, blur) as the ASS engine,
so the CapCut-style positioner drives both; the browser shows the very same
component through ``<Player>``, so what you see is what gets rendered.

Needs: ``node`` on PATH and the Remotion packages installed in ``frontend/``
(``npm install`` there — they are in package.json). Chrome Headless Shell is
downloaded by Remotion itself on the first render (~150 MB).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from flowboard.config import ROOT

logger = logging.getLogger(__name__)

FRONTEND = ROOT / "frontend"
SCRIPT = FRONTEND / "remotion" / "render.mjs"
#: keys the composition understands (`frontend/src/remotion/DubSubtitles.tsx` DUB_REMOTION_STYLES)
STYLES: dict[str, str] = {
    "rm_box": "Remotion · hộp vàng bo góc, font Việt, emoji màu",
    "rm_karaoke": "Remotion · bật sáng từng từ (kiểu TikTok)",
    "rm_outline": "Remotion · chữ trắng viền đen",
}
DEFAULT_STYLE = "rm_box"
FPS = 30
#: the first render also downloads Chrome and builds the webpack bundle
RENDER_TIMEOUT_S = 120 * 60  # a 30-minute video draws at roughly 1-2x real time on CPU


class RemotionError(RuntimeError):
    pass


def node_path() -> Optional[str]:
    return os.getenv("FLOWBOARD_NODE") or shutil.which("node")


def available() -> tuple[bool, str]:
    """(usable, reason when not)."""
    if node_path() is None:
        return False, "Không thấy Node.js trên PATH (cần Node 20+)."
    if not SCRIPT.is_file():
        return False, f"Thiếu {SCRIPT}."
    if not (FRONTEND / "node_modules" / "@remotion" / "renderer" / "package.json").is_file():
        return False, "Chưa cài gói Remotion — chạy `npm install` trong thư mục frontend."
    return True, ""


def _cue(c: tuple) -> dict[str, Any]:
    out: dict[str, Any] = {"start": round(float(c[0]), 3), "end": round(float(c[1]), 3), "text": c[2]}
    if len(c) > 3 and c[3]:
        out["look"] = dict(c[3])  # this line's own x / y / scale / w
    return out


def build_spec(*, src: Path, out: Path, cues: list[tuple], layout: dict[str, Any], style: str,
               width: int, height: int, duration_s: float, fps: int = FPS, concurrency: Optional[Any] = None,
               highlights: Optional[dict[str, Any]] = None, sfx: Optional[list[tuple[float, float]]] = None) -> dict[str, Any]:
    """``highlights`` = {words, zoom, y, points: [{at, words}]} (the key moments, None = off);
    ``sfx`` = [(at, seconds)] — the files go in ``spec["sfx_files"]`` in the same order (render.mjs serves them)."""
    if style not in STYLES:
        style = DEFAULT_STYLE
    return {
        "composition": "DubSubtitles",
        "src": str(src),
        "out": str(out),
        "concurrency": concurrency,
        "props": {
            "width": int(width), "height": int(height), "fps": int(fps), "durationS": float(duration_s),
            "cues": [_cue(c) for c in cues if c[2].strip()],
            "layout": {"x": layout.get("x", 0.5), "y": layout.get("y", 0.8), "scale": layout.get("scale", 1.0), "w": layout.get("w"),
                       "blur": layout.get("blur") or None, "frame": layout.get("frame") or None,
                       "mascot": layout.get("mascot") or None},
            "style": style,
            "muted": False,
            "highlights": highlights,
            "sfx": [{"at": round(float(a), 3), "dur": round(float(d), 3)} for a, d in (sfx or [])],
        },
    }


def render(spec: dict[str, Any], *, progress: Optional[Callable[[float, str], None]] = None,
           stop: Optional[Callable[[], bool]] = None, timeout_s: int = RENDER_TIMEOUT_S) -> Path:
    """Run the render script; ``progress(fraction, phase)`` as it goes. Returns the output path."""
    ok, reason = available()
    if not ok:
        raise RemotionError(reason)
    out = Path(spec["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    spec_path = out.with_suffix(".remotion.json")
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    cmd = [node_path() or "node", str(SCRIPT), str(spec_path)]
    env = dict(os.environ)
    env.setdefault("REMOTION_DISABLE_TELEMETRY", "1")
    proc = subprocess.Popen(cmd, cwd=str(FRONTEND), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0)
    tail: list[str] = []
    phase = "render"
    error: Optional[str] = None

    def drain_err() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                tail.append(line)
                del tail[:-25]

    threading.Thread(target=drain_err, daemon=True).start()
    assert proc.stdout is not None
    timer = threading.Timer(timeout_s, proc.kill)
    timer.start()
    try:
        for raw in proc.stdout:
            line = raw.strip()
            if stop is not None and stop():
                proc.kill()
                raise RemotionError("Đã dừng theo yêu cầu")
            if line.startswith("PHASE "):
                phase = line[6:]
                if progress:
                    progress(0.0, phase)
            elif line.startswith("PROGRESS "):
                try:
                    frac = float(line.split()[1])
                except (IndexError, ValueError):
                    continue
                if progress:
                    progress(frac, "render")
            elif line.startswith("BROWSER ") or line.startswith("BUNDLE "):
                if progress:
                    progress(0.0, line.lower())
            elif line.startswith("ERROR "):
                error = line[6:]
        proc.wait()
    finally:
        timer.cancel()
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        detail = error or " | ".join(tail[-6:]) or f"exit {proc.returncode}"
        raise RemotionError(f"Remotion render lỗi: {detail}")
    return out
