"""Remove text / logos / watermarks from a video the seller already has.

Two kinds of cleaning, both writing a new video Asset under
``storage/media`` so the result is addressable as ``/media/<id>`` like any
other clip:

* **boxes** (no AI): rectangles the user drew on a frame, removed by ffmpeg
  — ``delogo`` (interpolates the surroundings; good for small static logos)
  or ``boxblur`` through ``crop`` + ``overlay`` (blurs the patch).
* **AI bands**: hard-coded subtitles found and inpainted by the user's other
  project, pyvideotrans (``vi_dub_erase.py``: RapidOCR text detection +
  LaMa, GPU).  Torch never enters this venv: ``video_clean_runner.py`` is
  launched with pyvideotrans' own interpreter as a subprocess
  (``FLOWBOARD_ERASE_PYTHON`` / ``FLOWBOARD_ERASE_ROOT``).  Long, so it runs
  as a background job the route polls.  ``ai-blur`` is the fast fallback:
  the detected bands blurred with ffmpeg only.

Coordinates in the API are fractions 0–1 of the frame as ffmpeg decodes it
(rotation metadata already applied), so the frontend's canvas and ffmpeg's
filters agree on one geometry.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.services import media as media_service
from flowboard.services.video_export import _run, probe_clip

logger = logging.getLogger(__name__)

FRAME_CACHE_DIR = Path(tempfile.gettempdir()) / "flowboard-clean-frames"
ERASE_ROOT_DEFAULT = Path(r"D:\codes\pyvideotrans")
RUNNER_PATH = Path(__file__).with_name("video_clean_runner.py")
DETECT_TIMEOUT_S = 900
# Sentinel so a job's "error" is never silently None on a crash.
_NO_OUTPUT = "runner produced no output"

Method = str  # "delogo" | "blur"


class CleanError(Exception):
    """A user-facing failure (bad geometry, ffmpeg refused, runner missing)."""


class UnavailableError(CleanError):
    """The AI runner is not on this machine (the routes answer 503)."""


# ── geometry ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Box:
    """A rectangle as fractions of the frame (0–1)."""
    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Box":
        try:
            box = cls(float(raw["x"]), float(raw["y"]), float(raw["w"]), float(raw["h"]))
        except (KeyError, TypeError, ValueError):
            raise CleanError("each box needs numeric x, y, w, h")
        if not (0 <= box.x < 1 and 0 <= box.y < 1 and box.w > 0 and box.h > 0):
            raise CleanError("box must lie inside the frame (fractions 0–1)")
        return box

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Pixel rect clamped inside the frame, even-aligned for yuv420p."""
        x0 = max(0, min(width - 2, int(self.x * width)))
        y0 = max(0, min(height - 2, int(self.y * height)))
        x1 = max(x0 + 2, min(width, int(round((self.x + self.w) * width))))
        y1 = max(y0 + 2, min(height, int(round((self.y + self.h) * height))))
        x0, y0 = x0 // 2 * 2, y0 // 2 * 2
        w, h = max(2, (x1 - x0) // 2 * 2), max(2, (y1 - y0) // 2 * 2)
        return x0, y0, min(w, width - x0), min(h, height - y0)


def band_to_box(band: dict[str, Any]) -> Box:
    """A subtitle band ``{y0, y1}`` (fractions) as a full-width box."""
    try:
        y0, y1 = float(band["y0"]), float(band["y1"])
    except (KeyError, TypeError, ValueError):
        raise CleanError("each band needs numeric y0, y1")
    if not (0 <= y0 < y1 <= 1):
        raise CleanError("band must satisfy 0 <= y0 < y1 <= 1")
    return Box(0.0, y0, 1.0, y1 - y0)


# ── probing ────────────────────────────────────────────────────────────────

@dataclass
class VideoInfo:
    duration: float
    width: int
    height: int
    has_audio: bool


def probe_video(path: Path) -> VideoInfo:
    """Like ``probe_clip`` but with the display size: a phone clip stored
    sideways with a rotation tag is decoded upright by ffmpeg, and the
    filters (and the frame the user draws on) see the upright size."""
    info = probe_clip(path)
    if info is None or info.width <= 0 or info.height <= 0:
        raise CleanError("Không đọc được video (ffprobe).")
    width, height = info.width, info.height
    if _rotation_quarter_turns(path) % 2 == 1:
        width, height = height, width
    return VideoInfo(info.duration, width, height, info.has_audio)


def _rotation_quarter_turns(path: Path) -> int:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return 0
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-print_format", "json",
             "-show_entries", "stream_side_data=rotation:stream_tags=rotate", str(path)],
            capture_output=True, timeout=60, check=False,
        ).stdout.decode("utf-8", "replace")
        stream = (json.loads(out or "{}").get("streams") or [{}])[0]
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return 0
    rot = 0
    for sd in stream.get("side_data_list") or []:
        try:
            rot = int(float(sd.get("rotation") or 0))
        except (TypeError, ValueError):
            pass
    if not rot:
        try:
            rot = int(float((stream.get("tags") or {}).get("rotate") or 0))
        except (TypeError, ValueError):
            rot = 0
    return (abs(rot) // 90) % 4


# ── frames ─────────────────────────────────────────────────────────────────

def frame_at(path: Path, media_id: str, t: float, duration: float) -> Path:
    """One JPEG frame at second ``t`` (clamped into the clip), cached per
    ``(media_id, t)`` in a temp dir so scrubbing back is free."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise CleanError("ffmpeg not found on PATH")
    t = max(0.0, min(t, max(0.0, duration - 0.05)))
    FRAME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = FRAME_CACHE_DIR / f"{media_id}_{t:.2f}.jpg"
    if out.is_file() and out.stat().st_size > 0:
        return out
    err = _run([ffmpeg, "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
                "-frames:v", "1", "-q:v", "3", "-f", "image2", str(out)], timeout=60)
    if err is None and not (out.is_file() and out.stat().st_size > 0):
        err = "no frame written"
    if err is not None:
        out.unlink(missing_ok=True)
        raise CleanError(f"Không lấy được khung hình: {err}")
    return out


# ── ffmpeg erase ───────────────────────────────────────────────────────────

def _delogo_filter(boxes: list[Box], width: int, height: int) -> str:
    parts = []
    for box in boxes:
        x, y, w, h = box.to_pixels(width, height)
        # delogo needs one pixel of untouched frame around the rectangle.
        x, y = max(1, x), max(1, y)
        w = max(2, min(w, width - 1 - x))
        h = max(2, min(h, height - 1 - y))
        parts.append(f"delogo=x={x}:y={y}:w={w}:h={h}")
    return ",".join(parts)


def _blur_graph(boxes: list[Box], width: int, height: int) -> str:
    """Each box: crop → boxblur → overlay back, chained so N boxes compose."""
    n = len(boxes)
    labels = "".join(f"[t{i}]" for i in range(n))
    chains = [f"[0:v]split={n + 1}[base]{labels}"]
    for i, box in enumerate(boxes):
        x, y, w, h = box.to_pixels(width, height)
        # boxblur refuses a radius above half the plane size, and the chroma
        # planes of yuv420p are half the crop: size the radius off a quarter.
        radius = max(1, min(10, min(w, h) // 4 - 1))
        chains.append(f"[t{i}]crop={w}:{h}:{x}:{y},boxblur={radius}:3:{max(1, radius // 2)}:3[b{i}]")
    prev = "[base]"
    for i, box in enumerate(boxes):
        x, y, _, _ = box.to_pixels(width, height)
        out = "[vout]" if i == n - 1 else f"[v{i}]"
        chains.append(f"{prev}[b{i}]overlay={x}:{y}{out}")
        prev = out
    return ";".join(chains)


def erase_boxes(src: Path, dst: Path, boxes: list[Box], method: Method, info: VideoInfo) -> None:
    """Write ``dst`` = ``src`` with every box removed. Raises CleanError."""
    if not boxes:
        raise CleanError("Chưa khoanh vùng nào.")
    if method not in ("delogo", "blur"):
        raise CleanError(f"unknown method {method!r}")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise CleanError("ffmpeg not found on PATH")
    cmd = [ffmpeg, "-y", "-v", "error", "-nostdin", "-i", str(src)]
    if method == "delogo":
        cmd += ["-vf", _delogo_filter(boxes, info.width, info.height), "-map", "0:v:0"]
    else:
        cmd += ["-filter_complex", _blur_graph(boxes, info.width, info.height), "-map", "[vout]"]
    cmd += ["-map", "0:a?", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart", str(dst)]
    timeout = int(max(600, info.duration * 30))
    err = _run(cmd, timeout)
    if err is None and not (dst.is_file() and dst.stat().st_size > 0):
        err = "no output file"
    if err is not None:
        dst.unlink(missing_ok=True)
        raise CleanError(f"ffmpeg lỗi: {err}")


# ── output registration ────────────────────────────────────────────────────

def new_output_path() -> tuple[str, Path]:
    media_id = uuid.uuid4().hex
    media_service.MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return media_id, media_service.MEDIA_CACHE_DIR / f"{media_id}.mp4"


def register_output(media_id: str, path: Path) -> dict[str, Any]:
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(path), mime="video/mp4"))
        s.commit()
    info = probe_clip(path)
    return {"media_id": media_id, "url": f"/media/{media_id}",
            "duration_s": round(info.duration, 1) if info else None,
            "width": info.width if info else None, "height": info.height if info else None}


def clean_with_boxes(src: Path, boxes: list[Box], method: Method) -> dict[str, Any]:
    info = probe_video(src)
    media_id, dst = new_output_path()
    erase_boxes(src, dst, boxes, method, info)
    logger.info("video_clean: %s %d box(es) → %s", method, len(boxes), media_id)
    return register_output(media_id, dst)


# ── AI runner (pyvideotrans) ───────────────────────────────────────────────

def erase_root() -> Path:
    return Path(os.getenv("FLOWBOARD_ERASE_ROOT") or ERASE_ROOT_DEFAULT)


def erase_python() -> Optional[Path]:
    """pyvideotrans' interpreter, or None when it is not on this machine."""
    configured = os.getenv("FLOWBOARD_ERASE_PYTHON")
    if configured:
        p = Path(configured)
        return p if p.is_file() else None
    default = erase_root() / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return default if default.is_file() else None


def ai_status() -> dict[str, Any]:
    python = erase_python()
    root = erase_root()
    if python is None:
        return {"available": False,
                "reason": "Xoá chữ bằng AI cần bộ VieDub đầy đủ (torch + LaMa) — máy này chưa có. Dùng chế độ khoanh vùng (làm mờ / xoá logo).",
                "root": str(root)}
    if not (root / "vi_dub_erase.py").is_file():
        return {"available": False, "reason": f"Không thấy vi_dub_erase.py trong {root}.", "root": str(root)}
    from flowboard.services import machine

    off = machine.limit("ai_erase")
    if off is not None:  # no NVIDIA card: LaMa on the CPU takes hours — off, not a job that never ends
        return {"available": False, "reason": off["reason"], "root": str(root), "no_gpu": True}
    model = root / "models" / "lama" / "big-lama.pt"
    return {"available": True, "python": str(python), "root": str(root),
            "model_cached": model.is_file() and model.stat().st_size > (100 << 20)}


def _runner_cmd(*args: str) -> tuple[list[str], dict[str, str], str]:
    python = erase_python()
    if python is None:
        raise UnavailableError(ai_status()["reason"])
    root = erase_root()
    env = dict(os.environ, FLOWBOARD_ERASE_ROOT=str(root), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    return [str(python), str(RUNNER_PATH), *args], env, str(root)


def detect_bands(src: Path) -> dict[str, Any]:
    """``{bands: [{y0, y1, hits}], info}`` from the runner's ``detect`` — VieDub's, or on a machine with the
    "gói lồng tiếng" add-on instead, dub_runner's own RapidOCR version."""
    if erase_python() is None:
        from flowboard.services import dub, dub_addon

        if not dub_addon.ready():
            raise UnavailableError("Tự tìm chữ gốc cần gói lồng tiếng — cài ở trang 🎙 Lồng tiếng video (một lần).")
        try:
            data = dub._runner("detect", str(src), timeout=DETECT_TIMEOUT_S)
        except dub.DubError as exc:
            raise CleanError(f"Tìm phụ đề lỗi: {exc}")
        return {"bands": data.get("bands") or [], "info": data.get("info") or ""}
    cmd, env, cwd = _runner_cmd("detect", str(src))
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, timeout=DETECT_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        raise CleanError(f"Tìm phụ đề quá {DETECT_TIMEOUT_S}s.")
    except OSError as exc:
        raise CleanError(f"Không chạy được pyvideotrans: {exc}")
    stdout = proc.stdout.decode("utf-8", "replace")
    payload = next((line[6:] for line in reversed(stdout.splitlines()) if line.startswith("BANDS ")), None)
    if proc.returncode != 0 or payload is None:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-4:]
        raise CleanError("Tìm phụ đề lỗi: " + (" ".join(tail)[-500:] or _NO_OUTPUT))
    try:
        data = json.loads(payload)
    except ValueError:
        raise CleanError("Tìm phụ đề lỗi: runner trả JSON hỏng")
    return {"bands": data.get("bands") or [], "info": data.get("info") or ""}


def run_erase(src: Path, dst: Path, bands: list[dict[str, Any]],
              on_progress: Callable[[int], None], should_stop: Callable[[], bool] = lambda: False) -> None:
    """Blocking: run the runner's ``erase`` and report ``PROGRESS`` lines."""
    cmd, env, cwd = _runner_cmd("erase", str(src), str(dst), json.dumps(bands))
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise CleanError(f"Không chạy được pyvideotrans: {exc}")
    done = False
    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("PROGRESS "):
                try:
                    on_progress(max(0, min(100, int(float(line[9:])))))
                except ValueError:
                    pass
            elif line == "DONE":
                done = True
            if should_stop():
                proc.kill()
                raise CleanError("Đã dừng.")
        stderr = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace")
        code = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if code != 0 or not done or not (dst.is_file() and dst.stat().st_size > 0):
        tail = " ".join(stderr.strip().splitlines()[-4:])[-500:]
        dst.unlink(missing_ok=True)
        raise CleanError("Xoá bằng AI lỗi: " + (tail or _NO_OUTPUT))


# ── jobs (one at a time, in memory) ────────────────────────────────────────

@dataclass
class Job:
    id: str
    source_media_id: str
    status: str = "queued"  # queued | running | done | error
    progress: int = 0
    media_id: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    stop: bool = False
    started_at: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {"job_id": self.id, "status": self.status, "progress": self.progress,
                               "source_media_id": self.source_media_id}
        if self.media_id:
            out["media_id"] = self.media_id
            out["url"] = f"/media/{self.media_id}"
        if self.result:
            out.update({k: v for k, v in self.result.items() if k not in out})
        if self.error:
            out["error"] = self.error
        return out


JOBS: dict[str, Job] = {}


def active_job() -> Optional[Job]:
    return next((j for j in JOBS.values() if j.status in ("queued", "running")), None)


def _run_job(job: Job, src: Path, bands: list[dict[str, Any]]) -> None:
    media_id, dst = new_output_path()
    job.status = "running"

    def progress(p: int) -> None:
        job.progress = p

    try:
        run_erase(src, dst, bands, progress, lambda: job.stop)
        job.result = register_output(media_id, dst)
        job.media_id = media_id
        job.progress = 100
        job.status = "done"
        logger.info("video_clean: ai job %s done → %s", job.id, media_id)
    except CleanError as exc:
        job.status, job.error = "error", str(exc)
        logger.warning("video_clean: ai job %s failed: %s", job.id, exc)
    except Exception as exc:  # noqa: BLE001 — a job must never die silently
        job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
        logger.exception("video_clean: ai job %s crashed", job.id)


def start_ai_job(source_media_id: str, src: Path, bands: list[dict[str, Any]]) -> Job:
    """Launch the LaMa erase in a worker thread. Raises CleanError when the
    runner is unavailable or another job is still going."""
    if active_job() is not None:
        raise CleanError("Đang có một tiến trình xoá AI chạy — đợi xong rồi thử lại.")
    _runner_cmd("erase")  # raises when pyvideotrans is missing
    st = ai_status()
    if not st["available"]:  # no NVIDIA card: refused here too, not only by the greyed-out button
        raise UnavailableError(st["reason"])
    if not bands:
        raise CleanError("Chưa có dải phụ đề nào.")
    for band in bands:
        band_to_box(band)  # validates
    job = Job(id=uuid.uuid4().hex[:12], source_media_id=source_media_id)
    JOBS[job.id] = job
    # Drop finished jobs older than an hour so the dict stays small.
    cutoff = time.time() - 3600
    for jid in [j.id for j in JOBS.values() if j.status in ("done", "error") and j.started_at < cutoff]:
        JOBS.pop(jid, None)
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _run_job, job, src, bands)
    return job
