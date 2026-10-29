"""Dub a foreign short video into Vietnamese ("Lồng tiếng video"), the way
VieDub / pyvideotrans does, trimmed to one flow:

  link (or uploaded video) → yt-dlp → Whisper (original speech, timed)
  → LLM translation to spoken Vietnamese → Edge / Gemini TTS per line,
  fitted to each line's slot → original speech dropped (optionally the
  background music kept via spleeter) → Vietnamese subtitles burned in
  (yellow box, dark bold text — the style of the seller's page) → an mp4
  that becomes a clip (board) so it can be saved to a channel and get a
  Facebook post like any other clip.

Whisper and spleeter run in pyvideotrans' virtualenv through
``dub_runner.py`` (same arrangement as the AI subtitle eraser). Jobs run in
a worker thread and are polled; after transcription + translation a job can
pause in ``review`` so the lines can be edited before rendering.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Asset, Board, Node
from flowboard.services import media as media_service
from flowboard.services import dub_decor, dub_remotion, key_moments, sfx, tts
from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError
from flowboard.services.video_clean import erase_python, erase_root
from flowboard.services.video_export import _encode_args, _run, probe_clip
from flowboard.short_id import generate_unique_short_id

logger = logging.getLogger(__name__)

RUNNER_PATH = Path(__file__).with_name("dub_runner.py")
MAX_DURATION_S = 30 * 60
#: how much faster than natural a Vietnamese line may be spoken to fit its slot
MAX_SPEEDUP = 1.45
#: one subtitle line (as in the reference page: one short yellow box)
SUB_MAX_CHARS = 34
BGM_VOLUME = 0.6
LLM_TIMEOUT_S = 180
STEP_TIMEOUT_S = 45 * 60  # Whisper / spleeter on a 30-minute track (CPU fallback is the slow case)
#: Re-encoding the dubbed video (subtitles burned in) of a 30-minute source.
ENCODE_TIMEOUT_S = 60 * 60
#: Lines per translation call: a 30-minute video has hundreds of lines, and one
#: call for all of them runs past the LLM timeout or comes back short.
TRANSLATE_BATCH = 60
#: Already-translated lines shown to the next batch so the voice stays consistent.
TRANSLATE_CONTEXT = 4

STYLES: dict[str, str] = {
    "box_yellow": "Hộp vàng, chữ đen (như page mẫu)",
    "box_white": "Hộp trắng, chữ đen",
    "outline": "Chữ trắng viền đen",
}

_TRANSLATE_SYSTEM = (
    "You translate the timed transcript of a short social video into natural spoken Vietnamese for a Vietnamese "
    "voice-over and subtitles. Rules: keep the SAME number of lines, same order, one Vietnamese line per source line; "
    "casual spoken Vietnamese (xưng 'mình', gọi 'các mẹ' / 'mọi người' / 'bạn' as fits the topic); each line must be "
    "speakable in its time slot: every line comes with a word budget (≤ N từ) — NEVER go over it, Vietnamese "
    "takes longer to say than most languages, so cut filler, merge repeats and say it shorter; never add facts; "
    "numbers, product names and brand names stay as they are; no translator notes, no quotes. Also give a short "
    "Vietnamese clip title (<= 60 chars). Output ONLY one JSON object: {\"title\": str, \"lines\": [str, ...]}."
)


class DubError(RuntimeError):
    pass


# ── availability ───────────────────────────────────────────────────────────

def status() -> dict[str, Any]:
    python = erase_python()
    root = erase_root()
    out: dict[str, Any] = {"available": False, "root": str(root), "ytdlp": shutil.which("yt-dlp") is not None,
                           "whisper": False, "separate": False}
    rm_ok, rm_why = dub_remotion.available()
    out["remotion"] = rm_ok
    if not rm_ok:
        out["remotion_reason"] = rm_why
    if python is None:
        out["reason"] = f"Không thấy Python của pyvideotrans ({root / '.venv'}). Đặt FLOWBOARD_ERASE_PYTHON trong .env."
        return out
    from flowboard.services.dub_runner import WHISPER_DIR

    out["whisper"] = (root / "models" / WHISPER_DIR / "model.bin").is_file()
    out["separate"] = (root / "models" / "onnx" / "vocals.fp16.onnx").is_file()
    out["sfx_sets"] = sfx.sets()
    if not out["whisper"]:
        out["reason"] = f"Chưa có mô hình Whisper large-v3-turbo trong {root / 'models'} — mở VieDub chạy một video để nó tải về."
        return out
    out["available"] = True
    return out


def _runner(*args: str, progress: Optional[Callable[[int], None]] = None,
            stop: Optional[Callable[[], bool]] = None, timeout: int = STEP_TIMEOUT_S) -> dict[str, Any]:
    python = erase_python()
    if python is None:
        raise DubError(status().get("reason", "pyvideotrans không có trên máy"))
    env = dict(os.environ, FLOWBOARD_ERASE_ROOT=str(erase_root()), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    cmd = [str(python), str(RUNNER_PATH), *args]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(erase_root()))
    tail: list[str] = []
    deadline = time.time() + timeout

    def pump() -> None:
        assert proc.stderr is not None
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            if line.startswith("PROGRESS "):
                try:
                    if progress:
                        progress(int(line.split()[1]))
                except (IndexError, ValueError):
                    pass
            elif line:
                tail.append(line)
                del tail[:-12]

    import threading

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    while proc.poll() is None:
        if stop and stop():
            proc.kill()
            raise DubError("Đã dừng theo yêu cầu")
        if time.time() > deadline:
            proc.kill()
            raise DubError(f"bước {args[0]} quá {timeout}s")
        time.sleep(0.5)
    t.join(timeout=5)
    out = (proc.stdout.read() if proc.stdout else b"").decode("utf-8", "replace").strip().splitlines()
    if proc.returncode != 0:
        raise DubError(" ".join(tail)[-500:] or f"runner {args[0]} exited {proc.returncode}")
    try:
        return json.loads(out[-1]) if out else {}
    except ValueError:
        return {}


# ── pure helpers (tested) ──────────────────────────────────────────────────

def parse_translation(text: str, n: int) -> tuple[str, list[str]]:
    """``(title, lines)`` from the LLM answer; pads / trims to ``n`` lines."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise DubError("bản dịch không phải JSON")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise DubError(f"bản dịch JSON hỏng: {exc}") from exc
    lines = [re.sub(r"\s+", " ", str(x or "")).strip() for x in (data.get("lines") or [])]
    if not any(lines):
        raise DubError("bản dịch rỗng")
    lines = (lines + [""] * n)[:n]
    return str(data.get("title") or "").strip()[:80], lines


#: Vietnamese words a line may have per second of its window (Edge reads ~3.3 words/s at normal pace, measured
#: 28/10; this asks for ~1.27× — the voice can still be sped up to MAX_SPEEDUP)
WORDS_PER_SECOND = 4.2


def line_window(segs: list[Segment], i: int, total_s: float = 0.0) -> float:
    """Time line ``i`` may be spoken in: its own slot plus the pause before the next line."""
    seg = segs[i]
    nxt = segs[i + 1].start if i + 1 < len(segs) else (total_s or seg.end)
    return max(0.4, max(seg.end, nxt) - seg.start)


def word_budget(segs: list[Segment], i: int, total_s: float = 0.0) -> int:
    return max(2, int(line_window(segs, i, total_s) * WORDS_PER_SECOND))


def speedup_for(voice_s: float, slot_s: float) -> float:
    """atempo factor so a ``voice_s`` line fits ``slot_s``; 1.0 when it already does."""
    if slot_s <= 0 or voice_s <= slot_s:
        return 1.0
    return min(MAX_SPEEDUP, round(voice_s / slot_s, 3))


def split_cue(start: float, end: float, text: str, max_chars: int = SUB_MAX_CHARS) -> list[tuple[float, float, str]]:
    """One subtitle box per ≤ ``max_chars`` chunk, the slot split by chunk length."""
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            chunks.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        chunks.append(cur)
    total = sum(len(c) for c in chunks) or 1
    out: list[tuple[float, float, str]] = []
    t = start
    for i, c in enumerate(chunks):
        dur = (end - start) * (len(c) / total)
        e = end if i == len(chunks) - 1 else t + dur
        out.append((round(t, 3), round(e, 3), c))
        t = e
    return out


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


SUB_MARGIN_X_FRAC = 0.06
#: where the subtitle sits: (x, y) = the bottom-centre of the box as a fraction
#: of the frame (CapCut-style dragging in the UI edits these), scale = font multiplier.
DEFAULT_LAYOUT: dict[str, float] = {"x": 0.5, "y": 0.80, "scale": 1.0}


def _num(raw: dict, key: str, lo: float, hi: float, default: float) -> float:
    try:
        v = raw.get(key)
        return round(min(hi, max(lo, float(v))), 3) if v is not None else default
    except (TypeError, ValueError):
        return default


#: blur boxes per clip (the original video often has text in several places)
MAX_BLURS = 8
#: output formats ("Khung xuất"): width:height; "source" (None) keeps the video's own size
CANVAS_ASPECTS: dict[str, tuple[int, int]] = {"9:16": (9, 16), "16:9": (16, 9), "4:3": (4, 3), "3:4": (3, 4),
                                              "1:1": (1, 1), "4:5": (4, 5)}
#: how a video of another shape goes into the format: blurred copy behind it / black bars / cropped to fill
CANVAS_FITS = ("blur", "black", "crop")


def _norm_blur(b: Any) -> Optional[dict[str, float]]:
    if not isinstance(b, dict) or not b:
        return None
    x, y = _num(b, "x", 0.0, 0.95, 0.1), _num(b, "y", 0.0, 0.97, 0.6)
    return {"x": x, "y": y, "w": _num(b, "w", 0.05, round(1 - x, 3), min(0.8, 1 - x)),
            "h": _num(b, "h", 0.02, round(1 - y, 3), min(0.08, 1 - y)), "amount": _num(b, "amount", 1, 10, 5)}


def normalize_canvas(raw: Any) -> Optional[dict[str, Any]]:
    """``{aspect, fit, pos}`` — the output format; None = the source video's own size.
    ``pos`` (0–1) is where a "crop" fit cuts along the long axis (0.5 = centre)."""
    if not isinstance(raw, dict) or raw.get("aspect") not in CANVAS_ASPECTS:
        return None
    return {"aspect": raw["aspect"], "fit": raw.get("fit") if raw.get("fit") in CANVAS_FITS else "blur",
            "pos": _num(raw, "pos", 0.0, 1.0, 0.5)}


def normalize_layout(raw: Any) -> dict[str, Any]:
    """``{x, y, scale, blurs, canvas, …}`` — ``blurs`` are rectangles
    ``{x, y, w, h, amount}`` (top-left + size as frame fractions, amount
    1–10) softly blurred for the whole clip: the page's trick for hiding the
    original hard-coded text under the Vietnamese subtitles. A layout saved
    before 29/10 has one ``blur``; it reads as a one-item ``blurs`` and
    ``blur`` stays the first box for older readers. ``canvas`` = the output
    format (:func:`normalize_canvas`); every other position is a fraction of it."""
    out: dict[str, Any] = dict(DEFAULT_LAYOUT)
    out["blur"] = None
    out["blurs"] = []
    out["canvas"] = None
    out["frame"] = None   # services/dub_decor: shrink onto a blurred / coloured background
    out["mascot"] = None  # services/dub_decor: a bouncing sticker
    out["w"] = None       # subtitle box width (fraction of the frame); None = automatic
    if isinstance(raw, dict):
        out["x"] = _num(raw, "x", 0.05, 0.95, out["x"])
        out["y"] = _num(raw, "y", 0.08, 0.98, out["y"])
        out["scale"] = _num(raw, "scale", 0.5, 2.2, out["scale"])
        if raw.get("w") is not None:
            out["w"] = _num(raw, "w", W_MIN, W_MAX, 0.8)
        out["frame"] = dub_decor.normalize_frame(raw.get("frame"))
        out["mascot"] = dub_decor.normalize_mascot(raw.get("mascot"))
        out["canvas"] = normalize_canvas(raw.get("canvas"))
        boxes = raw["blurs"] if isinstance(raw.get("blurs"), list) else [raw.get("blur")]
        out["blurs"] = [b for b in (_norm_blur(x) for x in boxes) if b][:MAX_BLURS]
        out["blur"] = out["blurs"][0] if out["blurs"] else None
    return out


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def canvas_size(width: int, height: int, layout: Optional[dict]) -> tuple[int, int]:
    """The output picture size: the source's own, or its long side at the format's shape."""
    c = normalize_layout(layout)["canvas"]
    if not c or width <= 0 or height <= 0:
        return width, height
    aw, ah = CANVAS_ASPECTS[c["aspect"]]
    long = max(width, height)
    w, h = (long, long * ah / aw) if aw >= ah else (long * aw / ah, long)
    w, h = _even(w), _even(h)
    if abs(w / h - width / height) < 0.01:
        return width, height  # already that shape
    return w, h


def canvas_filter(canvas: Optional[dict], src_w: int, src_h: int, width: int, height: int,
                  src: str = "[0:v]", out: str = "[vc]") -> str:
    """The source picture into the ``width``×``height`` format: a blurred copy behind it, black bars, or cropped
    to fill (at ``pos`` along the cut axis). Empty when the format is the source's own size."""
    if not canvas or (width, height) == (src_w, src_h):
        return ""
    fit = canvas.get("fit", "blur")
    if fit == "crop":
        pos = canvas.get("pos", 0.5)
        return (f"{src}scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:(iw-{width})*{pos}:(ih-{height})*{pos},setsar=1{out}")
    fg = f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    if fit == "black":
        return f"{src}{fg},pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1{out}"
    bw, bh = _even(width / 4), _even(height / 4)  # blur a small copy: fast, and soft enough
    return (f"{src}split[cv_a][cv_b];[cv_a]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
            f"boxblur=10:2,scale={width}:{height},setsar=1[cv_bg];[cv_b]{fg},setsar=1[cv_fg];"
            f"[cv_bg][cv_fg]overlay=(W-w)/2:(H-h)/2{out}")


#: subtitle box width range (fraction of the frame width)
W_MIN, W_MAX = 0.2, 0.96
LOOK_KEYS = ("x", "y", "scale", "w")


def normalize_look(raw: Any) -> Optional[dict[str, float]]:
    """A line's own placement (timeline editor "chỉnh riêng câu này"): any of
    x / y / scale / w, overriding the clip-wide layout for that line only."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, float] = {}
    bounds = {"x": (0.05, 0.95), "y": (0.08, 0.98), "scale": (0.5, 2.2), "w": (W_MIN, W_MAX)}
    for k in LOOK_KEYS:
        if raw.get(k) is not None:
            lo, hi = bounds[k]
            out[k] = _num(raw, k, lo, hi, (lo + hi) / 2)
    return out or None


HL_Y_MIN, HL_Y_MAX = 0.1, 0.92
HL_MAX_POINTS = key_moments.MAX_POINTS


def normalize_highlights(raw: Any) -> dict[str, Any]:
    """"✨ Nhấn chữ quan trọng": off by default; ``points`` = [{at, words, line}] picked by the AI or
    typed in the editor; ``y`` = where the key word sits (bottom-centre fraction), None = above the subtitles."""
    d = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {
        "on": bool(d.get("on")), "words": d.get("words", True) is not False, "zoom": d.get("zoom", True) is not False,
        "sfx": d.get("sfx", True) is not False,
        "sfx_set": sfx.CAPCUT_SET if d.get("sfx_set") == sfx.CAPCUT_SET else sfx.BUILTIN_SET,
        "y": None, "points": [], "picked": str(d.get("picked") or ""),
    }
    try:
        if d.get("y") is not None:
            out["y"] = round(min(HL_Y_MAX, max(HL_Y_MIN, float(d["y"]))), 4)
    except (TypeError, ValueError):
        pass
    seen: list[float] = []
    for p in d.get("points") or []:
        if not isinstance(p, dict):
            continue
        try:
            at = round(max(0.0, float(p.get("at"))), 3)
        except (TypeError, ValueError):
            continue
        words = re.sub(r"\s+", " ", str(p.get("words") or "")).strip()[:40]
        if not words:
            continue
        try:
            line = int(p.get("line")) if p.get("line") is not None else None
        except (TypeError, ValueError):
            line = None
        out["points"].append({"at": at, "words": words, "line": line})
        seen.append(at)
    out["points"].sort(key=lambda p: p["at"])
    out["points"] = out["points"][:HL_MAX_POINTS]
    return out


def highlight_lines(job: "Job") -> list[key_moments.Line]:
    return [key_moments.Line(s.start, s.end, s.text.strip()) for s in job.segments if s.text.strip()]


def pick_highlights(job: "Job") -> tuple[list[dict[str, Any]], str]:
    """The AI's key moments for this job's lines → ``(points, how)``; ``how`` = "ai" | "fallback"."""
    lines = highlight_lines(job)
    if not lines:
        return [], ""
    total = job.duration_s or (lines[-1].end if lines else 0)
    try:
        return asyncio.run(key_moments.pick_points(lines, total)), "ai"
    except (LLMError, ValueError) as exc:
        logger.warning("dub: AI could not pick key moments (%s) — falling back to numbers / exclamations", exc)
        return key_moments.fallback_points(lines, total), "fallback"


def _ensure_points(job: "Job") -> dict[str, Any]:
    """The highlights with points: when on and none were picked yet, ask the AI now (once)."""
    hl = normalize_highlights(job.highlights)
    if hl["on"] and not hl["points"]:
        _set(job, "AI đang chọn chữ quan trọng", 88)
        pts, how = pick_highlights(job)
        hl["points"], hl["picked"] = pts, how
        job.highlights = hl
    return hl


def emphasis_y(layout: Optional[dict], hl: dict[str, Any]) -> float:
    """Where the key word sits: its own y, else well above the subtitles."""
    if hl.get("y") is not None:
        return float(hl["y"])
    lay = normalize_layout(layout)
    return round(min(HL_Y_MAX, max(HL_Y_MIN, lay["y"] - 0.2)), 4)


def emphasis_events(hl: dict[str, Any], layout: Optional[dict], total_s: float) -> list[tuple[float, float, str, float, float]]:
    """``[(start, end, TEXT, x, y)]`` of the key words to burn in."""
    if not (hl.get("on") and hl.get("words")):
        return []
    y = emphasis_y(layout, hl)
    out = []
    for p in hl["points"]:
        a = float(p["at"])
        b = min(total_s or a + key_moments.EMPHASIS_S, a + key_moments.EMPHASIS_S)
        if b - a >= 0.3:
            out.append((a, b, str(p["words"]).upper(), 0.5, y))
    return out


def zoom_filter(hl: dict[str, Any], width: int, height: int, fps: str) -> str:
    """ffmpeg ``zoompan`` that pushes in at every point (and back), or "" when off."""
    if not (hl.get("on") and hl.get("zoom") and hl["points"]):
        return ""
    z = key_moments.zoom_expr(hl["points"], "in_time")
    return (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps={fps}")


def probe_fps(path: Path) -> str:
    """The source frame rate as ffmpeg writes it ("30000/1001"), "30" when unknown."""
    probe = shutil.which("ffprobe")
    if probe is None:
        return "30"
    try:
        out = subprocess.run([probe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                              "-of", "csv=p=0", str(path)], capture_output=True, timeout=60, text=True,
                             **({"creationflags": 0x08000000} if os.name == "nt" else {}))
        rate = (out.stdout or "").strip().split("\n")[0].strip()
        num, _, den = rate.partition("/")
        if num.isdigit() and (not den or den.isdigit()) and int(num) > 0 and (not den or int(den) > 0):
            fps = int(num) / int(den or 1)
            if 5 <= fps <= 120:
                return rate
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return "30"


def effective_layout(layout: Optional[dict], look: Optional[dict]) -> dict[str, Any]:
    lay = normalize_layout(layout)
    if look:
        lay.update({k: v for k, v in look.items() if k in LOOK_KEYS})
    return lay


def blur_filter(blur: Optional[dict], width: int, height: int, src: str = "[0:v]", out: str = "[vb]", tag: str = "") -> str:
    """ffmpeg graph that blurs the ``blur`` rectangle of ``src`` into ``out``
    (crop → boxblur → overlay). Empty when there is nothing to blur. ``tag`` keeps
    the inner labels apart when several boxes are chained."""
    if not blur:
        return ""
    x, y = int(width * blur["x"]) // 2 * 2, int(height * blur["y"]) // 2 * 2
    w = max(16, min(width - x, int(width * blur["w"]) // 2 * 2))
    h = max(8, min(height - y, int(height * blur["h"]) // 2 * 2))
    # boxblur refuses a radius above half the plane; chroma planes are half the crop.
    radius = max(2, min(min(w, h) // 4 - 1, round(h * blur["amount"] / 60)))
    return (f"{src}split[vb{tag}_base][vb{tag}_t];[vb{tag}_t]crop={w}:{h}:{x}:{y},boxblur={radius}:2:{max(1, radius // 2)}:2[vb{tag}_b];"
            f"[vb{tag}_base][vb{tag}_b]overlay={x}:{y}{out}")


def video_filter(ass: Path, width: int, height: int, layout: Optional[dict],
                 mascot_index: Optional[int] = None, mascot_animated: bool = False,
                 frame_bg_index: Optional[int] = None, zoom: str = "",
                 source: Optional[tuple[int, int]] = None) -> str:
    """The whole ``-filter_complex`` video part → ``[v]``: zoom (key moments, on the source), the output
    format (``source`` size → ``width``×``height``, :func:`canvas_filter`), frame, blur boxes,
    mascot (input ``mascot_index``, prepared by ``dub_decor.prepare_mascot``),
    then subtitles. Each step is optional; everything after the format is in its pixels."""
    lay = normalize_layout(layout)
    parts: list[str] = []
    src = "[0:v]"
    if zoom:
        parts.append(f"{src}{zoom}[vz]")
        src = "[vz]"
    if source is not None:
        fit = canvas_filter(lay["canvas"], source[0], source[1], width, height, src, "[vc]")
        if fit:
            parts.append(fit)
            src = "[vc]"
    if lay.get("frame"):
        parts.append(dub_decor.frame_filter(lay["frame"], width, height, src, "[vf]", frame_bg_index))
        src = "[vf]"
    many = len(lay["blurs"]) > 1
    for i, box in enumerate(lay["blurs"]):
        out = f"[vb{i}]" if many else "[vb]"
        parts.append(blur_filter(box, width, height, src, out, str(i) if many else ""))
        src = out
    if lay.get("mascot") and mascot_index is not None:
        parts.append(dub_decor.mascot_filter(lay["mascot"], mascot_index, width, height, src, "[vm]", mascot_animated))
        src = "[vm]"
    parts.append(f"{src}ass='{_filter_path(ass)}'[v]")
    return ";".join(parts)


def sub_font_px(height: int, scale: float = 1.0) -> int:
    return max(20, round(height * 0.036 * scale))


def sub_max_chars(width: int, height: int, layout: Optional[dict] = None) -> int:
    """How many characters fit one subtitle line: Arial Bold averages ~0.56 em
    per character; the line may use the frame minus the side margins, and an
    off-centre box only the narrower side twice."""
    lay = normalize_layout(layout)
    font = sub_font_px(height, lay["scale"])
    if lay.get("w"):
        # a set box width: as many characters as fit inside it (minus the box padding)
        usable = width * min(lay["w"], 2 * min(lay["x"], 1 - lay["x"])) - font * 1.1
        return max(6, min(80, int(usable / (font * 0.5))))  # measured on burned frames: ~0.49 em per character
    usable = width * max(0.3, 2 * min(lay["x"], 1 - lay["x"]) - 2 * SUB_MARGIN_X_FRAC)
    return max(10, min(SUB_MAX_CHARS, int(usable / (font * 0.56))))


def write_sub_ass(cues: list[tuple[float, float, str]], path: Path, *, width: int, height: int, style: str = "box_yellow",
                  layout: Optional[dict] = None, emphasis: Optional[list[tuple[float, float, str, float, float]]] = None) -> Path:
    """Subtitles for libass. ``box_*``: BorderStyle 3 — an opaque box behind
    each line (yellow / white) with dark bold text, like the reference page;
    ``outline``: classic white text with a dark outline. Lines are cut to
    :func:`sub_max_chars` beforehand; WrapStyle 0 wraps anything longer.
    Every event is pinned with ``\\an2\\pos`` at the layout's anchor."""
    lay = normalize_layout(layout)
    font = sub_font_px(height, lay["scale"])
    margin_v = round(height * (1 - lay["y"]))
    margin_x = round(width * SUB_MARGIN_X_FRAC)
    pos = f"{{\\an2\\pos({round(width * lay['x'])},{round(height * lay['y'])})}}"
    if style == "outline":
        line = (f"Style: Sub,Arial,{font},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,"
                f"{max(2, font // 11)},1,2,{margin_x},{margin_x},{margin_v},1")
    else:
        back = "&H0014D8FF" if style == "box_yellow" else "&H00F4F4F4"  # ASS = &HAABBGGRR → yellow / near-white
        text_col = "&H00141414"
        # BorderStyle 3: Outline = box padding, Shadow 0. OutlineColour is the box colour.
        line = (f"Style: Sub,Arial,{font},{text_col},&H000000FF,{back},{back},-1,0,0,0,100,100,0,0,3,"
                f"{max(8, font // 4)},0,2,{margin_x},{margin_x},{margin_v},1")
    # the key word ("✨ Nhấn chữ quan trọng"): big yellow bold with a dark outline, popping in
    emph_font = round(font * 1.6)
    emph_line = (f"Style: Emph,Arial,{emph_font},&H0014D8FF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,"
                 f"{max(3, emph_font // 10)},{max(1, emph_font // 20)},5,{margin_x},{margin_x},0,1")
    header = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        line, emph_line, "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    events = []
    for cue in cues:
        s, e, t = cue[0], cue[1], cue[2]
        if not t.strip():
            continue
        tag = pos
        look = cue[3] if len(cue) > 3 else None
        if look:
            own = effective_layout(lay, look)
            own_font = sub_font_px(height, own["scale"])
            extra = "" if own_font == font else f"\\fs{own_font}" + ("" if style == "outline" else f"\\bord{max(8, own_font // 4)}")
            tag = f"{{\\an2\\pos({round(width * own['x'])},{round(height * own['y'])}){extra}}}"
        events.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Sub,,0,0,0,,{tag}{t.replace(chr(10), ' ')}")
    for a, b, text, ex, ey in emphasis or []:
        cx, cy = round(width * ex), round(height * (ey - 0.03))  # \an5: the anchor is the centre
        pop = "\\fscx70\\fscy70\\t(0,120,\\fscx100\\fscy100)"
        events.append(f"Dialogue: 1,{_ass_time(a)},{_ass_time(b)},Emph,,0,0,0,,{{\\an5\\pos({cx},{cy}){pop}}}{text}")
    path.write_text(header + "\n" + "\n".join(events) + "\n", encoding="utf-8")
    return path


def _filter_path(path: Path) -> str:
    p = str(path).replace("\\", "/")
    return p.replace(":", "\\:").replace("'", "\\'")


# ── jobs ───────────────────────────────────────────────────────────────────

@dataclass
class Segment:
    start: float
    end: float
    src: str
    text: str = ""
    #: this line's own placement (normalize_look), None = the clip-wide layout
    look: Optional[dict] = None

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {"start": self.start, "end": self.end, "src": self.src, "text": self.text}
        if self.look:
            out["look"] = dict(self.look)
        return out


@dataclass
class Job:
    id: str
    url: Optional[str]
    source_media_id: Optional[str]
    voice: str = tts.DEFAULT_VOICE
    keep_bgm: bool = False
    style: str = "box_yellow"
    #: subtitle engine: "ass" = ffmpeg/libass (the original path), "remotion" =
    #: services/dub_remotion (HTML/CSS subtitles, live <Player> preview)
    engine: str = "ass"
    layout: dict = field(default_factory=lambda: dict(DEFAULT_LAYOUT))
    #: "✨ Nhấn chữ quan trọng": {on, words, zoom, sfx, sfx_set, y, points: [{at, words, line}]} — normalize_highlights
    highlights: dict = field(default_factory=dict)
    width: int = 0
    height: int = 0
    #: voice + lines the current voice.wav was made from (re-renders that only
    #: move the subtitles reuse it)
    voice_key: str = ""
    channel_id: Optional[int] = None
    name: str = ""
    auto_render: bool = True
    #: several links dubbed together ("loạt"): the editor lists them side by side and can apply one look to all
    batch_id: str = ""
    #: every mp4 this job rendered: [{media_id, size, sha256, at}] — "📂 Mở lại video đã làm" finds the
    #: project from a downloaded file (the tag inside it first, these fingerprints second)
    outputs: list[dict] = field(default_factory=list)
    language: str = ""
    status: str = "queued"  # queued | running | review | rendering | done | error
    phase: str = "Đang chờ"
    progress: int = 0
    title: str = ""
    duration_s: float = 0.0
    segments: list[Segment] = field(default_factory=list)
    media_id: Optional[str] = None
    board_id: Optional[int] = None
    error: Optional[str] = None
    stop: bool = False
    started_at: float = field(default_factory=time.time)
    work: Optional[Path] = None
    src_path: Optional[Path] = None

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "job_id": self.id, "status": self.status, "phase": self.phase, "progress": self.progress,
            "started_at": self.started_at,
            "url": self.url, "source_media_id": self.source_media_id, "voice": self.voice, "keep_bgm": self.keep_bgm,
            "style": self.style, "engine": self.engine, "layout": dict(self.layout), "highlights": normalize_highlights(self.highlights),
            "channel_id": self.channel_id, "name": self.name, "language": self.language,
            "width": self.width, "height": self.height, "batch_id": self.batch_id,
            "title": self.title, "duration_s": round(self.duration_s, 1),
            "segments": [s.public() for s in self.segments],
        }
        if self.media_id:
            out["media_id"] = self.media_id
            out["media_url"] = f"/media/{self.media_id}"
        if self.work is not None and (self.work / "voice.wav").is_file():
            out["voice_url"] = f"/api/dub/jobs/{self.id}/voice"
            if self.keep_bgm and (self.work / "bgm.wav").is_file():
                out["bgm_url"] = f"/api/dub/jobs/{self.id}/bgm"
        if self.work is not None and (self.work / "nosub.mp4").is_file():
            # remotion: the dubbed video without subtitles, for the live preview
            out["nosub_url"] = f"/api/dub/jobs/{self.id}/nosub"
        if self.board_id:
            out["board_id"] = self.board_id
        if self.error:
            out["error"] = self.error
        return out


JOBS: dict[str, Job] = {}


def active_job() -> Optional[Job]:
    return next((j for j in JOBS.values() if j.status in ("queued", "running", "rendering")), None)


def _set(job: Job, phase: str, progress: int) -> None:
    job.phase, job.progress = phase, progress
    if job.stop:
        raise DubError("Đã dừng theo yêu cầu")


def _ffmpeg() -> str:
    f = shutil.which("ffmpeg")
    if f is None:
        raise DubError("ffmpeg không có trên PATH")
    return f


def _download(job: Job) -> Path:
    from flowboard.services.video_fetch import FetchError, extract_url, fetch_video

    media_id = uuid.uuid4().hex
    try:
        path, title = fetch_video(job.url or "", media_id, media_service.MEDIA_CACHE_DIR, max_duration_s=MAX_DURATION_S)
    except FetchError as exc:
        raise DubError(f"Không tải được video: {exc}") from exc
    job.url = extract_url(job.url or "") or job.url
    mime = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}.get(path.suffix.lower(), "video/mp4")
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(path), mime=mime))
        s.commit()
    job.source_media_id = media_id
    if title and not job.title:
        job.title = title[:80]
    return path


def _extract_wav(ffmpeg: str, src: Path, dst: Path, rate: int, mono: bool) -> None:
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src), "-vn", "-ar", str(rate), "-ac", "1" if mono else "2",
           "-c:a", "pcm_s16le", str(dst)]
    err = _run(cmd, 900)
    if err:
        raise DubError(f"không tách được tiếng: {err}")


def translation_batches(n: int, size: int = TRANSLATE_BATCH) -> list[tuple[int, int]]:
    """``[(start, end)]`` index ranges covering ``n`` lines, ``size`` at a time;
    a short tail (< a quarter batch) joins the batch before it."""
    if n <= 0:
        return []
    out = [(i, min(n, i + size)) for i in range(0, n, size)]
    if len(out) > 1 and out[-1][1] - out[-1][0] < max(1, size // 4):
        tail = out.pop()
        out[-1] = (out[-1][0], tail[1])
    return out


async def _translate(job: Job) -> None:
    """Translate in batches of :data:`TRANSLATE_BATCH` lines, in order; each
    batch sees the last few lines already translated so the voice and the
    terms stay the same across the whole video."""
    segs = job.segments
    batches = translation_batches(len(segs))
    title = ""
    for b, (start, end) in enumerate(batches):
        if len(batches) > 1:
            _set(job, f"Đang dịch sang tiếng Việt ({b + 1}/{len(batches)})", 52 + int(8 * b / len(batches)))
        lines = [f"[{i - start + 1}] ({segs[i].start:.1f}s-{segs[i].end:.1f}s, ≤ {word_budget(segs, i, job.duration_s)} từ) {segs[i].src}"
                 for i in range(start, end)]
        head = f"Source language: {job.language or 'unknown'}. Video title: {job.title or '-'}.\n"
        if len(batches) > 1:
            head += (f"This is part {b + 1} of {len(batches)} of one long video (lines {start + 1}-{end} of {len(segs)}). "
                     "Translate ONLY the lines below; keep the voice and terms of the earlier part.\n")
            prev = [s for s in segs[max(0, start - TRANSLATE_CONTEXT):start] if s.text.strip()]
            if prev:
                head += "ALREADY TRANSLATED (just before, for context - do not output these):\n" + "\n".join(
                    f"- {s.src} => {s.text}" for s in prev) + "\n"
        prompt = head + f"TRANSCRIPT ({len(lines)} lines):\n" + "\n".join(lines) + "\n\nTranslate now."
        try:
            text = await run_llm("auto_prompt", prompt, system_prompt=_TRANSLATE_SYSTEM, timeout=LLM_TIMEOUT_S)
        except LLMError as exc:
            where = f" (phần {b + 1}/{len(batches)})" if len(batches) > 1 else ""
            raise DubError(f"dịch thất bại{where}: {exc}") from exc
        part_title, vi = parse_translation(text, end - start)
        for seg, line in zip(segs[start:end], vi):
            seg.text = line
        if b == 0:
            title = part_title
    if title:
        job.title = title


def _prepare(job: Job) -> None:
    ffmpeg = _ffmpeg()
    job.status = "running"
    job.work = media_service.MEDIA_CACHE_DIR / "dub" / job.id
    job.work.mkdir(parents=True, exist_ok=True)
    if job.url and not job.source_media_id:
        _set(job, "Đang tải video về", 3)
        src = _download(job)
    else:
        p = media_service.cached_path(job.source_media_id or "")
        if p is None:
            raise DubError("Không thấy file video nguồn")
        src = Path(p)
    job.src_path = src
    info = probe_clip(src)
    if info is None or info.duration <= 0:
        raise DubError("Không đọc được video")
    if info.duration > MAX_DURATION_S:
        raise DubError(f"Video dài {info.duration / 60:.0f} phút — tối đa {MAX_DURATION_S // 60} phút")
    if not info.has_audio:
        raise DubError("Video không có tiếng để nhận dạng")
    job.duration_s = info.duration
    _set(job, "Đang tách tiếng khỏi video", 8)
    wav16 = job.work / "speech16.wav"
    _extract_wav(ffmpeg, src, wav16, 16000, True)
    _set(job, "Đang nhận dạng tiếng gốc (Whisper)", 10)
    out_json = job.work / "asr.json"
    _runner("transcribe", str(wav16), str(out_json), "auto",
            progress=lambda p: _set(job, "Đang nhận dạng tiếng gốc (Whisper)", 10 + p * 0.4), stop=lambda: job.stop)
    data = json.loads(out_json.read_text(encoding="utf-8"))
    job.language = str(data.get("language") or "")
    job.segments = [Segment(float(s["start"]), float(s["end"]), str(s["text"])) for s in data.get("segments") or []]
    if not job.segments:
        raise DubError("Whisper không nghe ra câu nào trong video")
    _set(job, "Đang dịch sang tiếng Việt", 52)
    asyncio.run(_translate(job))
    _set(job, "Đã dịch xong", 60)
    persist(job)  # the translation survives an agent restart from here on (see _job_from_dict)


#: a line Edge keeps refusing gets this many rounds (each = tts.ATTEMPTS tries), VOICE_ROUND_WAIT_S apart
VOICE_ROUNDS = 3
VOICE_ROUND_WAIT_S = 30
#: drop leading and trailing silence (Edge adds ~0.2 s at each end of a line)
TRIM_SILENCE = ("silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                "silenceremove=start_periods=1:start_threshold=-50dB,areverse")
#: Edge lines read at once (each is a network round trip); the ffmpeg fit-to-slot conversions too
EDGE_PARALLEL = 8  # measured 28/10: 1 at a time 21.6 s/line, 4 → 3.3–4.8 s, 8 → 1.5–3.1 s
CONVERT_PARALLEL = 4


def _prefetch_edge(job: Job, spoken: list[Segment]) -> None:
    """Read every Edge line EDGE_PARALLEL at a time into the TTS cache; the loop in _voice_pieces then
    only picks them up (and retries, round by round, whatever Edge refused here)."""
    total = len(spoken)
    done = 0

    async def run() -> None:
        nonlocal done
        sem = asyncio.Semaphore(EDGE_PARALLEL)

        async def one(seg: Segment) -> None:
            nonlocal done
            async with sem:
                if job.stop:
                    raise DubError("Đã dừng theo yêu cầu")
                try:
                    await tts.synthesize(seg.text, job.voice, 0)
                except tts.TTSError:
                    pass  # the loop below tries it again, with its rounds
            done += 1
            _set(job, f"Đang tạo giọng đọc ({done}/{total}, {EDGE_PARALLEL} câu một lúc)", 62 + int(16 * done / max(1, total)))

        await asyncio.gather(*(one(s) for s in spoken))

    asyncio.run(run())


def _voice_pieces(job: Job) -> list[tuple[float, Path, float]]:
    """TTS for every line, each converted to 48 kHz mono WAV and sped up to
    fit its slot. Returns ``[(start, wav, duration)]``."""
    ffmpeg = _ffmpeg()
    pieces: list[tuple[float, Path, float]] = []
    spoken = [s for s in job.segments if s.text.strip()]
    if tts.voice_kind(job.voice) == "vieneu" and spoken:
        # VieNeu loads its model once for every line still missing (then each line below is a cache hit)
        _set(job, f"Đang tạo giọng đọc VieNeu ({len(spoken)} câu, trên máy)", 62)
        try:
            asyncio.run(tts.synthesize_many([s.text for s in spoken], job.voice, 0))
        except tts.TTSError as exc:
            raise DubError(f"giọng đọc lỗi: {exc}") from exc
    if tts.voice_kind(job.voice) == "edge" and len(spoken) > 1:
        _prefetch_edge(job, spoken)
    narrations: list[Any] = []
    for i, seg in enumerate(spoken):
        _set(job, f"Đang tạo giọng đọc ({i + 1}/{len(spoken)})", 62 + int(18 * i / max(1, len(spoken))))
        narr = None
        for round_no in range(VOICE_ROUNDS):
            try:
                narr = asyncio.run(tts.synthesize(seg.text, job.voice, 0))
                break
            except tts.TTSError as exc:
                # Edge drops requests in streaks: one bad line should not end a long video — wait, then try it again
                if round_no == VOICE_ROUNDS - 1 or tts.voice_kind(job.voice) != "edge":
                    kept = f" {i} câu đầu đã đọc xong và được giữ lại — render lại sau chỉ đọc phần còn thiếu." if i else ""
                    hint = (" Dịch vụ giọng Edge đang chập chờn — thử lại sau ít phút, hoặc đổi sang giọng VieNeu (miễn phí, chạy trên máy)."
                            if tts.voice_kind(job.voice) == "edge" else "")
                    raise DubError(f"giọng đọc lỗi ở câu {i + 1}/{len(spoken)}: {exc}{kept}{hint}") from exc
                logger.warning("dub: job %s line %d: %s — waiting %ds before another round", job.id, i + 1, exc, VOICE_ROUND_WAIT_S)
                for left in range(VOICE_ROUND_WAIT_S, 0, -1):
                    _set(job, f"Giọng Edge đang chập chờn — chờ {left}s rồi đọc lại câu {i + 1}/{len(spoken)}",
                         62 + int(18 * i / max(1, len(spoken))))
                    time.sleep(1)
        assert narr is not None
        narrations.append(narr)

    def fit(i: int) -> tuple[float, Path, float]:
        seg, narr = spoken[i], narrations[i]
        # Edge pads every line with ~0.2 s of silence at both ends: off, so the words start on the line's mark
        trimmed = job.work / f"t{i:03d}.wav"
        err = _run([ffmpeg, "-y", "-v", "error", "-i", str(narr.path), "-af", TRIM_SILENCE + ",aresample=48000,"
                    "aformat=sample_fmts=s16:channel_layouts=mono", "-c:a", "pcm_s16le", str(trimmed)], 120)
        if err:
            raise DubError(f"không chuyển được giọng câu {i + 1}: {err}")
        natural = tts._probe_duration(trimmed) or narr.duration
        # the line may run into the pause before the next one before it has to be sped up
        factor = speedup_for(natural, line_window(spoken, i, job.duration_s))
        wav = job.work / f"v{i:03d}.wav"
        if factor > 1.0:
            err = _run([ffmpeg, "-y", "-v", "error", "-i", str(trimmed), "-af", f"atempo={factor}", "-c:a", "pcm_s16le", str(wav)], 120)
            if err:
                raise DubError(f"không chuyển được giọng câu {i + 1}: {err}")
            trimmed.unlink(missing_ok=True)
        else:
            os.replace(trimmed, wav)
        # ffprobe-measured when possible (probe_clip is video-only), else computed.
        return seg.start, wav, tts._probe_duration(wav) or (natural / factor)

    _set(job, f"Đang khớp độ dài {len(spoken)} câu giọng đọc", 80)
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=CONVERT_PARALLEL) as pool:
        pieces.extend(pool.map(fit, range(len(spoken))))
    return pieces


#: pieces per ffmpeg call when laying out the track: every piece is an ``-i <path>`` plus a filter chain, and
#: Windows caps a command line at 32 767 characters (29/10: a 332-line video failed with WinError 206)
TIMELINE_CHUNK = 48


def _timeline_wav(ffmpeg: str, pieces: list[tuple[float, Path, float]], total_s: float, out: Path) -> list[tuple[float, float]]:
    """The voice pieces at their start times on one silent track. A piece
    that overruns its slot pushes the next one later (never overlaps).
    Returns where each piece really landed: ``[(start, duration)]``.
    Long videos are laid out TIMELINE_CHUNK pieces at a time into part files, then the parts are joined."""
    if len(pieces) <= TIMELINE_CHUNK:
        return _timeline_part(ffmpeg, pieces, total_s, out)
    placed: list[tuple[float, float]] = []
    cursor = 0.0
    for start, _wav, dur in pieces:
        cursor = max(cursor, start) if start - cursor > 0.02 else cursor
        placed.append((round(cursor, 3), dur))
        cursor += dur
    groups = [list(range(i, min(i + TIMELINE_CHUNK, len(pieces)))) for i in range(0, len(pieces), TIMELINE_CHUNK)]
    parts: list[tuple[float, Path, float]] = []
    for g, idx in enumerate(groups):
        g_start = 0.0 if g == 0 else placed[idx[0]][0]
        g_end = placed[groups[g + 1][0]][0] if g + 1 < len(groups) else max(total_s, cursor)
        part = out.with_name(f"{out.stem}.part{g}.wav")
        # already resolved: each piece goes exactly where it landed, relative to the part's start
        _timeline_part(ffmpeg, [(placed[i][0] - g_start, pieces[i][1], pieces[i][2]) for i in idx], g_end - g_start, part)
        parts.append((g_start, part, g_end - g_start))
    try:
        _timeline_part(ffmpeg, parts, total_s, out)
    finally:
        for _s, part, _d in parts:
            part.unlink(missing_ok=True)
    return placed


def _timeline_part(ffmpeg: str, pieces: list[tuple[float, Path, float]], total_s: float, out: Path) -> list[tuple[float, float]]:
    placed: list[tuple[float, float]] = []
    inputs: list[str] = []
    chains: list[str] = []
    labels: list[str] = []
    cursor = 0.0
    n = 0
    for start, wav, dur in pieces:
        gap = start - cursor
        if gap > 0.02:
            chains.append(f"aevalsrc=0:d={gap:.3f}:s=48000:c=mono,aformat=sample_fmts=s16[g{n}]")
            labels.append(f"[g{n}]")
            cursor += gap
        inputs += ["-i", str(wav)]
        idx = len(inputs) // 2 - 1
        chains.append(f"[{idx}:a]aformat=sample_fmts=s16:channel_layouts=mono[a{n}]")
        labels.append(f"[a{n}]")
        placed.append((round(cursor, 3), dur))
        cursor += dur
        n += 1
    tail = total_s - cursor
    if tail > 0.02:
        chains.append(f"aevalsrc=0:d={tail:.3f}:s=48000:c=mono,aformat=sample_fmts=s16[gt]")
        labels.append("[gt]")
    chains.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]")
    cmd = [ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chains), "-map", "[out]",
           "-c:a", "pcm_s16le", str(out)]
    err = _run(cmd, 300)
    if err:
        raise DubError(f"không ghép được giọng: {err}")
    return placed


#: a subtitle stays this long after its line has been said (never into the next line)
SUB_TAIL_S = 0.25


def follow_voice(job: Job, placed: list[tuple[float, float]], total_s: float) -> None:
    """Subtitles follow the voice: every spoken line's start / end become where its voice really is on the track
    (a long line pushes the next ones later — the subtitles used to stay on the original timing and ran 1–6 s
    ahead of the voice, 28/10). Lines that are not spoken are kept between their neighbours."""
    spoken = [s for s in job.segments if s.text.strip()]
    for k, (seg, (start, dur)) in enumerate(zip(spoken, placed)):
        nxt = placed[k + 1][0] if k + 1 < len(placed) else (total_s or start + dur + SUB_TAIL_S)
        seg.start = round(start, 3)
        seg.end = round(max(start + MIN_SLOT_S, min(start + dur + SUB_TAIL_S, nxt)), 3)
    prev_end = 0.0
    for seg in job.segments:
        if seg.text.strip():
            prev_end = seg.end
        elif seg.start < prev_end:  # a line taken out: slide it after the previous spoken one
            span = max(0.0, seg.end - seg.start)
            seg.start, seg.end = round(prev_end, 3), round(prev_end + span, 3)


def filmstrip(job: Job) -> Path:
    """A strip of thumbnails across the source video (timeline "Video" track),
    made once per job. Key frames only, so it is quick even for 30 minutes."""
    if job.work is None or job.src_path is None or not Path(job.src_path).is_file():
        raise DubError("Chưa có video gốc")
    out = job.work / "filmstrip.jpg"
    if out.is_file() and out.stat().st_size > 0:
        return out
    dur = job.duration_s or 10.0
    n = int(min(60, max(6, round(dur / 1.5))))
    vf = ["-vf", f"fps={n}/{dur:.3f},scale=-2:72,tile={n}x1", "-frames:v", "1", "-q:v", "6", str(out)]
    # Long videos: key frames only (seconds, not minutes). Short ones decode every
    # frame — key frames can be 10 s apart, which left the last tiles black.
    fast = ["-skip_frame", "nokey"] if dur > 240 else []
    err = _run([_ffmpeg(), "-y", "-v", "error", *fast, "-i", str(job.src_path), *vf], 600)
    if fast and (err or not out.is_file()):
        err = _run([_ffmpeg(), "-y", "-v", "error", "-i", str(job.src_path), *vf], 900)
    if err or not out.is_file():
        raise DubError(f"không tạo được dải hình: {err}")
    return out


def waveform(job: Job) -> Path:
    """The Vietnamese voice track drawn as a waveform (timeline "Giọng" track);
    redrawn whenever voice.wav is newer."""
    if job.work is None:
        raise DubError("Chưa có giọng đọc")
    voice = job.work / "voice.wav"
    if not voice.is_file():
        raise DubError("Chưa có giọng đọc — render video trước")
    out = job.work / "wave.png"
    if out.is_file() and out.stat().st_mtime >= voice.stat().st_mtime:
        return out
    err = _run([_ffmpeg(), "-y", "-v", "error", "-i", str(voice), "-filter_complex",
                "aformat=channel_layouts=mono,showwavespic=s=2400x80:colors=#5eead4:scale=sqrt", "-frames:v", "1", str(out)], 180)
    if err or not out.is_file():
        raise DubError(f"không vẽ được sóng âm: {err}")
    return out


def voice_key(job: Job) -> str:
    """What voice.wav was made from: the voice, every line, and every line's
    slot (the timeline editor moves / stretches lines → the voice is placed
    again; the TTS itself comes from its cache)."""
    slots = ",".join(f"{s.start:.2f}-{s.end:.2f}" for s in job.segments)
    return job.voice + "|" + "\x1f".join(s.text for s in job.segments) + "|t:" + slots


def _legacy_voice_key(job: Job) -> str:
    return job.voice + "|" + "\x1f".join(s.text for s in job.segments)


def _upgrade_voice_key(job: Job) -> None:
    """Jobs saved before slots were part of the key: same voice + lines → still valid."""
    if job.voice_key and job.voice_key == _legacy_voice_key(job):
        job.voice_key = voice_key(job)


#: the shortest a line may be squeezed to on the timeline (seconds)
MIN_SLOT_S = 0.3


def apply_timings(job: Job, timings: list[list[float]]) -> None:
    """New [start, end] for every line (timeline editor). Kept in order, never
    overlapping, inside the video, at least MIN_SLOT_S long."""
    if len(timings) != len(job.segments):
        raise DubError("Số mốc thời gian không khớp số câu")
    total = job.duration_s or max((float(t[1]) for t in timings if len(t) == 2), default=0.0)
    prev_end = 0.0
    out: list[tuple[float, float]] = []
    for i, pair in enumerate(timings):
        if len(pair) != 2:
            raise DubError(f"Mốc thời gian câu {i + 1} không hợp lệ")
        start, end = float(pair[0]), float(pair[1])
        if not (start == start and end == end):  # NaN
            raise DubError(f"Mốc thời gian câu {i + 1} không hợp lệ")
        start = max(prev_end, start)
        if total:
            start = min(start, max(0.0, total - MIN_SLOT_S))
            end = min(end, total)
        end = max(end, start + MIN_SLOT_S)
        out.append((round(start, 3), round(end, 3)))
        prev_end = end
    for seg, (start, end) in zip(job.segments, out):
        seg.start, seg.end = start, end


def _separate_bgm(job: Job, ffmpeg: str, src: Path, bgm: Path, progress: Optional[Callable[[int], None]]) -> None:
    """The music under the original speech (spleeter) → ``bgm``."""
    full = job.work / "full44.wav"
    _extract_wav(ffmpeg, src, full, 44100, False)
    _runner("separate", str(full), str(job.work / "vocals.wav"), str(bgm), progress=progress, stop=lambda: job.stop)


def _render(job: Job) -> None:
    ffmpeg = _ffmpeg()
    job.status = "rendering"
    assert job.work is not None and job.src_path is not None
    src = job.src_path
    info = probe_clip(src)
    if info is None:
        raise DubError("Không đọc được video")
    job.width, job.height = info.width, info.height
    out_w, out_h = canvas_size(info.width, info.height, job.layout)  # "Khung xuất": the picture every overlay is placed on
    voice = job.work / "voice.wav"
    _upgrade_voice_key(job)
    key = voice_key(job)
    bgm_path = job.work / "bgm.wav"
    bgm_thread: Optional[Any] = None
    bgm_errors: list[BaseException] = []
    if (job.keep_bgm and status().get("separate") and not bgm_path.is_file()
            and not (voice.is_file() and job.voice_key == key)):
        # Separate the music while the voice is being read (that step waits on the network): saves its whole run.
        import threading

        def separate() -> None:
            try:
                _separate_bgm(job, ffmpeg, src, bgm_path, progress=None)
            except BaseException as exc:  # noqa: BLE001 — reported after the voice step
                bgm_errors.append(exc)

        bgm_thread = threading.Thread(target=separate, name=f"dub-bgm-{job.id}", daemon=True)
        bgm_thread.start()
    if voice.is_file() and job.voice_key == key:
        _set(job, "Dùng lại giọng đã đọc", 81)  # only the subtitles / layout changed
    else:
        pieces = _voice_pieces(job)
        _set(job, "Đang xếp giọng theo thời gian", 81)
        placed = _timeline_wav(ffmpeg, pieces, info.duration, voice)
        follow_voice(job, placed, info.duration)
        job.voice_key = voice_key(job)  # the lines now sit where their voice is: a layout-only re-render reuses it
    bgm: Optional[Path] = None
    if job.keep_bgm:
        if status().get("separate"):
            bgm = bgm_path
            if bgm_thread is not None:
                if bgm_thread.is_alive():
                    _set(job, "Đang tách nhạc nền khỏi tiếng gốc (sắp xong)", 84)
                bgm_thread.join()
                if bgm_errors:
                    err = bgm_errors[0]
                    raise err if isinstance(err, DubError) else DubError(f"tách nhạc nền lỗi: {err}")
            if not bgm.is_file():
                _set(job, "Đang tách nhạc nền khỏi tiếng gốc", 84)
                _separate_bgm(job, ffmpeg, src, bgm,
                              progress=lambda p: _set(job, "Đang tách nhạc nền khỏi tiếng gốc", 84 + p * 0.06))
        else:
            logger.warning("dub: keep_bgm asked but spleeter models are missing; original audio dropped")
    hl = _ensure_points(job)
    sfx_track: Optional[Path] = None
    sfx_pieces = sfx.pieces(hl["points"], hl["sfx_set"]) if hl["on"] and hl["sfx"] and hl["points"] else []
    if sfx_pieces:
        _set(job, "Đang xếp tiếng hiệu ứng", 90)
        sfx_track = job.work / "sfx.wav"
        _timeline_wav(ffmpeg, sfx_pieces, info.duration, sfx_track)
    _set(job, "Đang ghép video + phụ đề", 91)
    cues: list[tuple[float, float, str]] = []
    for s in job.segments:
        own = effective_layout(job.layout, s.look)
        for a, b, t in split_cue(s.start, s.end, s.text, sub_max_chars(out_w, out_h, own)):
            cues.append((a, b, t, s.look) if s.look else (a, b, t))
    if job.engine == "remotion":
        _render_remotion(job, ffmpeg, src, voice, bgm, info, cues, hl, sfx_pieces)
        return
    ass = write_sub_ass(cues, job.work / "subs.ass", width=out_w, height=out_h, style=job.style, layout=job.layout,
                        emphasis=emphasis_events(hl, job.layout, info.duration))
    media_id = uuid.uuid4().hex
    dst = media_service.MEDIA_CACHE_DIR / f"{media_id}.mp4"
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src), "-i", str(voice)]
    if bgm is not None:
        cmd += ["-i", str(bgm)]
    next_index = 3 if bgm is not None else 2
    sfx_index = None
    if sfx_track is not None:
        sfx_index = next_index
        next_index += 1
        cmd += ["-i", str(sfx_track)]
    frame_bg = dub_decor.frame_bg_path(normalize_layout(job.layout).get("frame"))
    frame_bg_index = None
    if frame_bg is not None:
        frame_bg_index = next_index
        next_index += 1
        cmd += ["-loop", "1", "-framerate", "30", "-i", str(frame_bg)]
    mascot = dub_decor.prepare_mascot(normalize_layout(job.layout).get("mascot"), out_h, job.work)
    mascot_index = None
    if mascot is not None:
        mascot_index = next_index
        cmd += dub_decor.mascot_input_args(*mascot)
    vgraph = video_filter(ass, out_w, out_h, job.layout, mascot_index, bool(mascot and mascot[1]), frame_bg_index,
                          zoom=zoom_filter(hl, info.width, info.height, probe_fps(src)), source=(info.width, info.height))
    agraph, amap = audio_mix(bgm is not None, sfx_index)
    if agraph:
        cmd += ["-filter_complex", f"{vgraph};{agraph}", "-map", "[v]", "-map", amap]
    else:
        cmd += ["-filter_complex", vgraph, "-map", "[v]", "-map", amap]
    cmd += [*_encode_args(ffmpeg), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest",
            "-metadata", f"comment={output_tag(job)}", "-movflags", "+faststart", str(dst)]
    err = _run(cmd, ENCODE_TIMEOUT_S)
    if err or not dst.is_file() or dst.stat().st_size == 0:
        raise DubError(f"ffmpeg ghép lỗi: {err or 'file rỗng'}")
    _record_output(job, dst, media_id)
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(dst), mime="video/mp4"))
        s.commit()
    job.media_id = media_id
    _set(job, "Đang lưu thành clip", 97)
    job.board_id = _save_board(job)
    job.phase, job.progress, job.status = "Xong", 100, "done"


def audio_mix(with_bgm: bool, sfx_index: Optional[int]) -> tuple[str, str]:
    """``(filter part, map)`` for the voice ([1:a]) + music ([2:a], BGM_VOLUME) + sound effects (input
    ``sfx_index``, SFX_VOLUME); the voice alone needs no filter."""
    parts, ins = [], ["[1:a]"]
    if with_bgm:
        parts.append(f"[2:a]volume={BGM_VOLUME}[b]")
        ins.append("[b]")
    if sfx_index is not None:
        parts.append(f"[{sfx_index}:a]volume={key_moments.SFX_VOLUME}[fx]")
        ins.append("[fx]")
    if len(ins) == 1:
        return "", "1:a:0"
    parts.append(f"{''.join(ins)}amix=inputs={len(ins)}:duration=first:normalize=0[a]")
    return ";".join(parts), "[a]"


def has_picture_layers(job: Job) -> bool:
    lay = normalize_layout(job.layout)
    return bool(lay.get("frame") or lay.get("blurs") or lay.get("mascot") or lay.get("canvas"))


def render_clean_video(job: Job, dst: Path) -> Path:
    """The picture as the editor shows it — frame, blur band, sticker — with
    no subtitles and no sound: Edit auto CapCut (``services/capcut_auto``)
    puts the voice, the music and the subtitles on their own CapCut tracks.
    A job without those layers needs no render: its source comes back."""
    src = job.src_path
    if src is None or not Path(src).is_file():
        p = media_service.cached_path(job.source_media_id or "")
        src = Path(p) if p else None
    if src is None or not Path(src).is_file():
        raise DubError("Không thấy file video nguồn")
    if not has_picture_layers(job):
        return Path(src)
    ffmpeg = _ffmpeg()
    info = probe_clip(src)
    if info is None:
        raise DubError("Không đọc được video")
    work = job.work if job.work is not None else dst.parent
    lay = normalize_layout(job.layout)
    out_w, out_h = canvas_size(info.width, info.height, job.layout)
    ass = write_sub_ass([], work / "capcut_nosub.ass", width=out_w, height=out_h, style=job.style, layout=job.layout)
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src)]
    next_index = 1
    frame_bg = dub_decor.frame_bg_path(lay.get("frame"))
    frame_bg_index = None
    if frame_bg is not None:
        frame_bg_index = next_index
        next_index += 1
        cmd += ["-loop", "1", "-framerate", "30", "-i", str(frame_bg)]
    mascot = dub_decor.prepare_mascot(lay.get("mascot"), out_h, work)
    mascot_index = None
    if mascot is not None:
        mascot_index = next_index
        cmd += dub_decor.mascot_input_args(*mascot)
    vgraph = video_filter(ass, out_w, out_h, job.layout, mascot_index, bool(mascot and mascot[1]), frame_bg_index,
                          source=(info.width, info.height))
    cmd += ["-filter_complex", vgraph, "-map", "[v]", "-an", "-t", f"{info.duration:.3f}", *_encode_args(ffmpeg),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
    err = _run(cmd, ENCODE_TIMEOUT_S)
    if err or not dst.is_file() or dst.stat().st_size == 0:
        raise DubError(f"ffmpeg dựng video nền lỗi: {err or 'file rỗng'}")
    return dst


def _render_remotion(job: Job, ffmpeg: str, src: Path, voice: Path, bgm: Optional[Path], info: Any,
                     cues: list[tuple[float, float, str]], hl: Optional[dict[str, Any]] = None,
                     sfx_pieces: Optional[list[tuple[float, Path, float]]] = None) -> None:
    """The second engine: ffmpeg only muxes the dubbed audio into the video
    (``nosub.mp4``, stream copy when possible), Remotion draws the subtitles
    and the blur band on top (``services/dub_remotion``)."""
    assert job.work is not None
    nosub = job.work / "nosub.mp4"
    _set(job, "Đang ghép tiếng vào video (chưa có phụ đề)", 91)

    def mux(copy_video: bool) -> Optional[str]:
        cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src), "-i", str(voice)]
        if bgm is not None:
            cmd += ["-i", str(bgm), "-filter_complex",
                    f"[2:a]volume={BGM_VOLUME}[b];[1:a][b]amix=inputs=2:duration=first:normalize=0[a]",
                    "-map", "0:v:0", "-map", "[a]"]
        else:
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        cmd += ["-c:v", "copy"] if copy_video else [*_encode_args(ffmpeg), "-pix_fmt", "yuv420p"]
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(nosub)]
        return _run(cmd, ENCODE_TIMEOUT_S)

    err = mux(True)
    if err or not nosub.is_file() or nosub.stat().st_size == 0:
        err = mux(False)  # odd source codec: re-encode instead of copying
    if err or not nosub.is_file() or nosub.stat().st_size == 0:
        raise DubError(f"ffmpeg ghép tiếng lỗi: {err or 'file rỗng'}")
    media_id = uuid.uuid4().hex
    dst = media_service.MEDIA_CACHE_DIR / f"{media_id}.mp4"
    hl = normalize_highlights(hl if hl is not None else job.highlights)
    out_w, out_h = canvas_size(info.width, info.height, job.layout)
    spec = dub_remotion.build_spec(src=nosub, out=dst, cues=cues, layout=normalize_layout(job.layout), style=job.style,
                                   width=out_w, height=out_h, duration_s=info.duration,
                                   highlights=({"words": hl["words"], "zoom": hl["zoom"], "y": emphasis_y(job.layout, hl),
                                                "points": [{"at": p["at"], "words": p["words"]} for p in hl["points"]]}
                                               if hl["on"] and hl["points"] else None),
                                   sfx=[(at, dur) for at, _p, dur in (sfx_pieces or [])])
    if sfx_pieces:
        spec["sfx_files"] = [str(p) for _a, p, _d in sfx_pieces]
    mascot = normalize_layout(job.layout).get("mascot")
    if mascot:
        try:
            mpath = media_service.cached_path(mascot["media_id"])
        except Exception:  # noqa: BLE001 — the sticker is optional
            mpath = None
        if mpath:
            spec["mascot_file"] = str(mpath)  # render.mjs serves it; the composition draws it
    bg_file = dub_decor.frame_bg_path(normalize_layout(job.layout).get("frame"))
    if bg_file is not None:
        spec["frame_bg_file"] = str(bg_file)
    labels = {"browser": "Remotion: chuẩn bị Chrome (lần đầu tải ~150 MB)", "bundle": "Remotion: đóng gói giao diện phụ đề (lần đầu)",
              "select": "Remotion: đọc video"}

    def prog(frac: float, phase: str) -> None:
        _set(job, labels.get(phase, "Remotion: đang vẽ phụ đề"), int(92 + frac * 5))

    try:
        dub_remotion.render(spec, progress=prog, stop=lambda: job.stop)
    except dub_remotion.RemotionError as exc:
        raise DubError(str(exc)) from exc
    _tag_file(ffmpeg, dst, output_tag(job))
    _record_output(job, dst, media_id)
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(dst), mime="video/mp4"))
        s.commit()
    job.media_id = media_id
    _set(job, "Đang lưu thành clip", 97)
    job.board_id = _save_board(job)
    job.phase, job.progress, job.status = "Xong", 100, "done"


def _style_for(engine: str, style: Optional[str]) -> str:
    """A style key valid for ``engine`` (its default when ``style`` is not)."""
    table = dub_remotion.STYLES if engine == "remotion" else STYLES
    if style and style in table:
        return style
    return dub_remotion.DEFAULT_STYLE if engine == "remotion" else "box_yellow"


def _check_engine(engine: Optional[str]) -> str:
    engine = "remotion" if engine == "remotion" else "ass"
    if engine == "remotion":
        ok, why = dub_remotion.available()
        if not ok:
            raise DubError(f"Remotion chưa dùng được: {why}")
    return engine


def _save_board(job: Job) -> int:
    """The dubbed video as a clip: a board with one video node (the
    Vietnamese lines as its narration) and an export node holding the final
    mp4, so the library, "Hôm nay", channels and step-5 posts all work."""
    name = (job.name or job.title or "Video lồng tiếng").strip()[:80]
    narration = " ".join(s.text for s in job.segments if s.text.strip())
    qt = {"template_id": "dub", "step": 5, "source_url": job.url, "channel_id": job.channel_id,
          "dub": {"job_id": job.id, "voice": job.voice, "style": job.style, "layout": dict(job.layout),
                  "keep_bgm": job.keep_bgm, "language": job.language, "source_media_id": job.source_media_id,
                  # the whole editable project, so it can be reopened even if <work>/job.json is gone
                  # (another machine, cleaned media folder) — see restore_from_board
                  "snapshot": snapshot(job)}}
    with get_session() as s:
        if job.board_id:
            board = s.get(Board, job.board_id)
        else:
            board = None
        if board is None:
            board = Board(name=name, data={"quicktool": qt})
            s.add(board)
            s.commit()
            s.refresh(board)
            video = Node(board_id=board.id, short_id=generate_unique_short_id(s, board.id), type="video", x=0, y=0,
                         data={"title": "Video lồng tiếng", "narration": narration, "mediaId": job.media_id,
                               "dubbed": True}, status="done")
            export = Node(board_id=board.id, short_id=generate_unique_short_id(s, board.id), type="export", x=320, y=0,
                          data={"title": "Xuất", "mediaId": job.media_id, "voice": job.voice}, status="done")
            s.add(video)
            s.add(export)
        else:
            board.data = {**(board.data or {}), "quicktool": {**((board.data or {}).get("quicktool") or {}), **qt}}
            s.add(board)
            for n in s.exec(select(Node).where(Node.board_id == board.id)).all():
                if n.type in ("video", "export"):
                    n.data = {**(n.data or {}), "mediaId": job.media_id, **({"narration": narration} if n.type == "video" else {})}
                    n.status = "done"
                    s.add(n)
        s.commit()
        return int(board.id)


def _run_job(job: Job, render: bool) -> None:
    try:
        if render and job.segments and job.src_path is not None:
            _render(job)
            return
        _prepare(job)
        if job.auto_render:
            _render(job)
        else:
            job.status, job.phase = "review", "Xem lại bản dịch rồi bấm Render"
    except DubError as exc:
        job.status, job.error = "error", str(exc)
        logger.warning("dub: job %s failed: %s", job.id, exc)
    except Exception as exc:  # noqa: BLE001 — a job must never die silently
        job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
        logger.exception("dub: job %s crashed", job.id)
    finally:
        job._render_only = False  # type: ignore[attr-defined]
        persist(job)
        _pump()


# ── jobs survive an agent restart ──────────────────────────────────────────
# ``<work>/job.json`` is the job's public dict; the work dir, source path and
# voice key are derived again on load, so a finished job can still have its
# subtitles moved after a restart.

def _jobs_root() -> Path:
    return media_service.MEDIA_CACHE_DIR / "dub"


def persist(job: Job) -> None:
    try:
        work = job.work or (_jobs_root() / job.id)
        work.mkdir(parents=True, exist_ok=True)
        data = job.public() | {"started_at": job.started_at, "auto_render": job.auto_render, "outputs": job.outputs[-30:]}
        (work / "job.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:  # noqa: BLE001 — persistence is best effort
        logger.warning("dub: could not persist job %s: %s", job.id, exc)


def load_jobs() -> None:
    """Pick up jobs saved by an earlier run of the agent (once per job id)."""
    root = _jobs_root()
    if not root.is_dir():
        return
    for meta in root.glob("*/job.json"):
        try:
            d = json.loads(meta.read_text(encoding="utf-8"))
            jid = str(d.get("job_id") or meta.parent.name)
            if jid in JOBS:
                continue
            JOBS[jid] = _job_from_dict(d, meta.parent, meta.stat().st_mtime)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("dub: skipped %s: %s", meta, exc)


def _job_from_dict(d: dict, work: Path, fallback_time: float) -> Job:
    """A job from its saved public dict (``job.json``, or the snapshot its clip keeps)."""
    job = Job(id=str(d.get("job_id") or work.name), url=d.get("url"), source_media_id=d.get("source_media_id"),
              voice=d.get("voice") or tts.DEFAULT_VOICE, keep_bgm=bool(d.get("keep_bgm")),
              style=d.get("style") or "box_yellow", layout=normalize_layout(d.get("layout")),
              highlights=normalize_highlights(d.get("highlights")),
              engine="remotion" if d.get("engine") == "remotion" else "ass",
              width=int(d.get("width") or 0), height=int(d.get("height") or 0),
              channel_id=d.get("channel_id"), name=str(d.get("name") or ""),
              auto_render=bool(d.get("auto_render", True)), batch_id=str(d.get("batch_id") or ""),
              language=str(d.get("language") or ""),
              status=str(d.get("status") or "error"), phase=str(d.get("phase") or ""),
              progress=int(d.get("progress") or 0), title=str(d.get("title") or ""),
              duration_s=float(d.get("duration_s") or 0), media_id=d.get("media_id"), board_id=d.get("board_id"),
              error=d.get("error"), started_at=float(d.get("started_at") or fallback_time), work=work,
              outputs=[o for o in d.get("outputs") or [] if isinstance(o, dict)])
    job.segments = [Segment(float(s["start"]), float(s["end"]), str(s.get("src") or ""), str(s.get("text") or ""),
                            normalize_look(s.get("look")))
                    for s in d.get("segments") or []]
    if job.status in ("queued", "running", "rendering"):
        job.status = "error"
        job.error = ("Agent khởi động lại giữa chừng — bản dịch vẫn còn, bấm \"Xuất lại video\" để làm tiếp "
                     "(câu đã đọc lấy lại từ bộ nhớ đệm)" if job.segments else
                     "Agent khởi động lại giữa chừng — làm lại từ link")
    src = media_service.cached_path(job.source_media_id or "") if job.source_media_id else None
    job.src_path = Path(src) if src else None
    if (work / "voice.wav").is_file():
        job.voice_key = voice_key(job)
    return job


#: "★ Mẫu chỉnh sửa" (DecorPreset kind "look"): the clip-independent look — layout (subtitle place / size / width,
#: blur boxes, output format, frame, sticker), style, engine, key-moment settings (never the points: each clip's own)
LOOK_PRESET_KEY = "dub_default_look"


def normalize_look_preset(raw: Any) -> dict[str, Any]:
    d = raw if isinstance(raw, dict) else {}
    engine = _check_engine(str(d.get("engine") or "ass"))
    hl = normalize_highlights(d.get("highlights"))
    hl["points"], hl["picked"] = [], ""
    return {"layout": normalize_layout(d.get("layout")), "style": _style_for(engine, str(d.get("style") or "box_yellow")),
            "engine": engine, "highlights": hl}


def start_job(*, url: Optional[str], source_media_id: Optional[str], voice: str, keep_bgm: bool, style: str,
              channel_id: Optional[int], name: str, auto_render: bool, engine: str = "ass", batch_id: str = "",
              layout: Optional[dict] = None, highlights: Optional[dict] = None) -> Job:
    st = status()
    if not st["available"]:
        raise DubError(st.get("reason", "Lồng tiếng chưa dùng được trên máy này"))
    if len(queued_jobs()) >= MAX_QUEUE:
        raise DubError(f"Hàng đợi đã có {MAX_QUEUE} video — đợi bớt rồi thêm tiếp.")
    if not url and not source_media_id:
        raise DubError("Cần link video hoặc file video")
    if voice not in tts.VOICES:
        raise DubError("Giọng đọc không hợp lệ")
    engine = _check_engine(engine)
    style = _style_for(engine, style)
    job = Job(id=uuid.uuid4().hex[:12], url=url or None, source_media_id=source_media_id or None, voice=voice,
              keep_bgm=keep_bgm, style=style, engine=engine, channel_id=channel_id, name=(name or "").strip(),
              auto_render=auto_render, batch_id=(batch_id or "").strip()[:40])
    if layout is not None:  # a look preset: the clip starts with that look (points are picked for this clip when on)
        job.layout = normalize_layout(layout)
    if highlights is not None:
        job.highlights = normalize_highlights(highlights)
        job.highlights["points"], job.highlights["picked"] = [], ""
    JOBS[job.id] = job
    cutoff = time.time() - 6 * 3600
    for jid in [j.id for j in JOBS.values() if j.status in ("done", "error") and j.started_at < cutoff]:
        JOBS.pop(jid, None)
    _pump()
    return job


# ── queue: one video at a time (Whisper / spleeter share the GPU), up to MAX_QUEUE waiting
MAX_QUEUE = 5
_LOOP: Optional[asyncio.AbstractEventLoop] = None
#: called when nobody waits in the queue (the link library's feeder, services/dub_links) — it may start a job
FEEDER: Optional[Callable[[], None]] = None


def queued_jobs() -> list[Job]:
    return sorted((j for j in JOBS.values() if j.status == "queued"), key=lambda j: j.started_at)


def running_job() -> Optional[Job]:
    return next((j for j in JOBS.values() if j.status in ("running", "rendering")), None)


def _pump() -> None:
    """Start the oldest queued job when nothing is running. Called from the
    event loop (start / render) and from the worker thread when a job ends."""
    global _LOOP
    try:
        _LOOP = asyncio.get_running_loop()
    except RuntimeError:
        pass  # worker thread: reuse the loop remembered from the request
    if FEEDER is not None and not queued_jobs():
        FEEDER()  # may start_job → _pump again (re-entrant: the queue is no longer empty, so no loop)
    waiting = queued_jobs()
    if running_job() is not None or not waiting:
        for i, j in enumerate(waiting):
            j.phase = "Chờ đến lượt" if i == 0 else f"Chờ đến lượt ({i} video trước)"
        return
    nxt, waiting = waiting[0], waiting[1:]
    for i, j in enumerate(waiting):
        j.phase = f"Chờ đến lượt ({i + 1} video trước)"
    render = bool(nxt.segments) and nxt.src_path is not None and getattr(nxt, "_render_only", False)
    # Claimed before the thread starts, so a second pump skips it. A re-render
    # keeps the phase render_job set ("Đang in lại phụ đề" / "Đang render").
    nxt.status = "rendering" if render else "running"
    if not render:
        nxt.phase = "Bắt đầu"
    persist(nxt)
    if _LOOP is not None and not _LOOP.is_closed():
        _LOOP.run_in_executor(None, _run_job, nxt, render)
    else:  # no live loop (tests, or the request loop is gone): a plain thread
        import threading

        threading.Thread(target=_run_job, args=(nxt, render), daemon=True).start()


_UNSET: Any = object()


def render_job(job: Job, *, lines: Optional[list[str]], voice: Optional[str], style: Optional[str],
               keep_bgm: Optional[bool], name: Optional[str], channel_id: Any = _UNSET,
               layout: Optional[dict] = None, engine: Optional[str] = None,
               timings: Optional[list[list[float]]] = None,
               looks: Optional[list[Optional[dict]]] = None,
               highlights: Optional[dict] = None) -> Job:
    """Render (again) with edited lines / options. Allowed from ``review``,
    ``done`` and ``error`` (after a render failure). ``timings`` = new
    [start, end] per line from the timeline editor."""
    if job.status in ("queued", "running", "rendering"):
        raise DubError("Video này đang chạy")
    if not job.segments or job.src_path is None or not Path(job.src_path).is_file():
        raise DubError("Chưa có bản dịch để render (agent đã khởi động lại?) — làm lại từ link.")
    _upgrade_voice_key(job)
    if timings is not None:
        apply_timings(job, timings)
    if looks is not None:
        if len(looks) != len(job.segments):
            raise DubError("Số kiểu riêng không khớp số câu")
        for seg, look in zip(job.segments, looks):
            seg.look = normalize_look(look)
    if lines is not None:
        if len(lines) != len(job.segments):
            raise DubError("Số câu không khớp")
        for seg, line in zip(job.segments, lines):
            seg.text = re.sub(r"\s+", " ", str(line or "")).strip()
    if voice:
        if voice not in tts.VOICES:
            raise DubError("Giọng đọc không hợp lệ")
        job.voice = voice
    if engine is not None:
        job.engine = _check_engine(engine)
    if style is not None or engine is not None:
        job.style = _style_for(job.engine, style or job.style)
    if layout is not None:
        job.layout = normalize_layout(layout)
    if highlights is not None:
        job.highlights = normalize_highlights(highlights)
    if keep_bgm is not None:
        job.keep_bgm = keep_bgm
    if name is not None:
        job.name = name.strip()
    if channel_id is not _UNSET:
        job.channel_id = channel_id
    job.error, job.stop = None, False
    quick = bool(job.work) and (job.work / "voice.wav").is_file() and job.voice_key == voice_key(job)
    job._render_only = True  # type: ignore[attr-defined]
    job.started_at = time.time()  # queue order: behind whatever waits already
    job.status, job.phase, job.progress = "queued", "Đang in lại phụ đề" if quick else "Đang render", 61
    persist(job)
    _pump()
    return job


# ── reopen a finished video later ("📂 Mở lại video đã làm") ───────────────
# Every mp4 the dubbing tool makes carries ``comment=flowboard-dub:<job id>``
# and its fingerprint is kept in ``job.outputs``; the board keeps a snapshot
# of the project. Dropping a downloaded video back into the page finds the
# project again — the next day, after a restart, or on the other machine.

TAG_PREFIX = "flowboard-dub:"
SNAPSHOT_KEYS = ("url", "source_media_id", "voice", "keep_bgm", "style", "engine", "layout", "highlights", "width", "height",
                 "channel_id", "name", "language", "title", "duration_s", "segments", "media_id", "batch_id")


def output_tag(job: Job) -> str:
    return f"{TAG_PREFIX}{job.id}"


def _tag_file(ffmpeg: str, path: Path, tag: str) -> None:
    """Write the tag into an already rendered mp4 (stream copy; best effort)."""
    tmp = path.with_name(path.stem + ".tag.mp4")
    err = _run([ffmpeg, "-y", "-v", "error", "-i", str(path), "-map", "0", "-c", "copy",
                "-metadata", f"comment={tag}", "-movflags", "+faststart", str(tmp)], 600)
    if err or not tmp.is_file() or tmp.stat().st_size == 0:
        logger.warning("dub: could not tag %s: %s", path.name, err)
        tmp.unlink(missing_ok=True)
        return
    os.replace(tmp, path)


def file_sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _record_output(job: Job, path: Path, media_id: str) -> None:
    try:
        job.outputs.append({"media_id": media_id, "size": path.stat().st_size, "sha256": file_sha256(path), "at": time.time()})
        job.outputs = job.outputs[-30:]
    except OSError as exc:  # noqa: BLE001 — a fingerprint is a convenience
        logger.warning("dub: could not fingerprint %s: %s", path, exc)


def snapshot(job: Job) -> dict[str, Any]:
    d = job.public()
    snap = {k: d.get(k) for k in SNAPSHOT_KEYS}
    snap.update(job_id=job.id, started_at=job.started_at, auto_render=True, status="done", outputs=job.outputs[-10:])
    return snap


def read_tag(path: Path) -> Optional[str]:
    """The job id written into a video by this tool, if any."""
    probe = shutil.which("ffprobe")
    if probe is None:
        return None
    try:
        out = subprocess.run([probe, "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
                             capture_output=True, timeout=60, **({"creationflags": 0x08000000} if os.name == "nt" else {}))
        tags = (json.loads(out.stdout or b"{}").get("format") or {}).get("tags") or {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    for value in tags.values():
        text = str(value or "")
        if text.startswith(TAG_PREFIX):
            jid = text[len(TAG_PREFIX):].strip()
            if re.fullmatch(r"[0-9a-f]{6,40}", jid):
                return jid
    return None


def restore_from_board(job_id: str) -> Optional[Job]:
    """Rebuild a job from the snapshot its clip keeps (Neon) when ``job.json`` is gone."""
    with get_session() as s:
        boards = s.exec(select(Board)).all()
    for b in boards:
        dub = (((b.data or {}).get("quicktool") or {}).get("dub") or {})
        snap = dub.get("snapshot")
        if dub.get("job_id") != job_id or not isinstance(snap, dict) or not snap.get("segments"):
            continue
        job = _job_from_dict({**snap, "job_id": job_id, "board_id": b.id, "status": "done", "error": None,
                              "phase": "Mở lại từ clip đã lưu", "progress": 100}, _jobs_root() / job_id, time.time())
        JOBS[job_id] = job
        persist(job)
        logger.info("dub: restored job %s from board %s", job_id, b.id)
        return job
    return None


def delete_jobs(ids: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    """Remove jobs from the list ("🗑 Xoá khỏi danh sách"): the job and its work folder (job.json, the
    voice / music tracks, temp files). The exported video, the source video and the clip are NOT touched —
    they are Assets / a board of their own; dropping the video back in still reopens the project from the
    snapshot its clip keeps (the voice is read again on the next export, from the TTS cache when it has the lines)."""
    load_jobs()
    root = _jobs_root().resolve()
    deleted: list[str] = []
    skipped: list[dict[str, str]] = []
    for jid in dict.fromkeys(ids):
        job = JOBS.get(jid)
        if job is None:
            skipped.append({"job_id": jid, "reason": "không có trong danh sách"})
            continue
        if job.status in ("queued", "running", "rendering"):
            skipped.append({"job_id": jid, "reason": "đang chạy — dừng trước rồi xoá"})
            continue
        work = (job.work or (root / jid)).resolve()
        if work.parent != root:  # never outside media/dub/<id>
            skipped.append({"job_id": jid, "reason": "thư mục làm việc lạ"})
            continue
        shutil.rmtree(work, ignore_errors=True)
        meta = work / "job.json"
        if meta.exists():  # a file still open (Windows): at least take it off the list
            try:
                meta.unlink()
            except OSError as exc:
                skipped.append({"job_id": jid, "reason": f"không xoá được: {exc}"})
                continue
        JOBS.pop(jid, None)
        deleted.append(jid)
    return deleted, skipped


_SNAPSHOT_CHECKED: set[str] = set()


def backfill_snapshots() -> int:
    """Clips made before snapshots existed get one (once per job per run), so they can be reopened anywhere."""
    done = 0
    for job in list(JOBS.values()):
        if job.id in _SNAPSHOT_CHECKED or not job.board_id or not job.segments or job.status != "done":
            continue
        _SNAPSHOT_CHECKED.add(job.id)
        try:
            with get_session() as s:
                board = s.get(Board, job.board_id)
                qt = dict(((board.data or {}).get("quicktool") or {})) if board is not None else {}
                d = dict(qt.get("dub") or {})
                if board is None or d.get("job_id") != job.id or d.get("snapshot"):
                    continue
                d["snapshot"] = snapshot(job)
                board.data = {**(board.data or {}), "quicktool": {**qt, "dub": d}}
                s.add(board)
                s.commit()
                done += 1
        except Exception as exc:  # noqa: BLE001 — never break the job list over this
            logger.warning("dub: snapshot backfill for %s failed: %s", job.id, exc)
    return done


def find_job(job_id: str) -> Optional[Job]:
    load_jobs()
    return JOBS.get(job_id) or restore_from_board(job_id)


def _dub_job_of_board(board: Board) -> Optional[str]:
    qt = (board.data or {}).get("quicktool") or {}
    return ((qt.get("dub") or {}).get("job_id") or None) if qt.get("template_id") == "dub" else None


def identify(path: Path, *, sha256: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Which project made this video? ``{"kind": "dub", "job": Job, "via": "tag"|"fingerprint"}`` for a dubbed
    video, ``{"kind": "clip", "board_id", "name"}`` for a clip made in the wizard, None when the tool did not
    make it (or another app re-encoded it — TikTok / CapCut / Zalo all do)."""
    jid = read_tag(path)
    if jid:
        job = find_job(jid)
        if job is not None:
            return {"kind": "dub", "job": job, "via": "tag"}
    size = path.stat().st_size
    digest = sha256 or file_sha256(path)
    load_jobs()
    for job in JOBS.values():
        if any(o.get("sha256") == digest for o in job.outputs):
            return {"kind": "dub", "job": job, "via": "fingerprint"}
    # older files (made before tags): the final video of every clip, same size first, then the bytes
    with get_session() as s:
        exports = s.exec(select(Node.board_id, Node.data).where(Node.type.in_(["export", "merge"]))).all()
        by_media: dict[str, int] = {}
        for board_id, data in exports:
            mid = (data or {}).get("mediaId") if isinstance(data, dict) else None
            if mid:
                by_media[str(mid)] = int(board_id)
        rows = s.exec(select(Asset).where(Asset.uuid_media_id.in_(list(by_media)))).all() if by_media else []
        candidates = [(by_media[r.uuid_media_id], Path(r.local_path)) for r in rows if r.local_path]
    for board_id, local in candidates:
        try:
            if not local.is_file() or local.stat().st_size != size or file_sha256(local) != digest:
                continue
        except OSError:
            continue
        with get_session() as s:
            board = s.get(Board, board_id)
        if board is None:
            continue
        djid = _dub_job_of_board(board)
        job = find_job(djid) if djid else None
        if job is not None:
            return {"kind": "dub", "job": job, "via": "fingerprint"}
        return {"kind": "clip", "board_id": board_id, "name": board.name}
    return None
