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
from flowboard.services import dub_remotion, tts
from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError
from flowboard.services.video_clean import erase_python, erase_root
from flowboard.services.video_export import _encode_args, _run, probe_clip
from flowboard.short_id import generate_unique_short_id

logger = logging.getLogger(__name__)

RUNNER_PATH = Path(__file__).with_name("dub_runner.py")
MAX_DURATION_S = 10 * 60
#: how much faster than natural a Vietnamese line may be spoken to fit its slot
MAX_SPEEDUP = 1.45
#: one subtitle line (as in the reference page: one short yellow box)
SUB_MAX_CHARS = 34
BGM_VOLUME = 0.6
LLM_TIMEOUT_S = 180
STEP_TIMEOUT_S = 900

STYLES: dict[str, str] = {
    "box_yellow": "Hộp vàng, chữ đen (như page mẫu)",
    "box_white": "Hộp trắng, chữ đen",
    "outline": "Chữ trắng viền đen",
}

_TRANSLATE_SYSTEM = (
    "You translate the timed transcript of a short social video into natural spoken Vietnamese for a Vietnamese "
    "voice-over and subtitles. Rules: keep the SAME number of lines, same order, one Vietnamese line per source line; "
    "casual spoken Vietnamese (xưng 'mình', gọi 'các mẹ' / 'mọi người' / 'bạn' as fits the topic); each line must be "
    "speakable in its time slot, so stay about as long as the original or shorter — drop filler, never add facts; "
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


def normalize_layout(raw: Any) -> dict[str, Any]:
    """``{x, y, scale, blur}`` — ``blur`` is an optional rectangle
    ``{x, y, w, h, amount}`` (top-left + size as frame fractions, amount
    1–10) that gets softly blurred for the whole clip: the page's trick for
    hiding the original hard-coded subtitles under the Vietnamese ones."""
    out: dict[str, Any] = dict(DEFAULT_LAYOUT)
    out["blur"] = None
    if isinstance(raw, dict):
        out["x"] = _num(raw, "x", 0.05, 0.95, out["x"])
        out["y"] = _num(raw, "y", 0.08, 0.98, out["y"])
        out["scale"] = _num(raw, "scale", 0.5, 2.2, out["scale"])
        b = raw.get("blur")
        if isinstance(b, dict) and b:
            x, y = _num(b, "x", 0.0, 0.95, 0.1), _num(b, "y", 0.0, 0.97, 0.6)
            out["blur"] = {"x": x, "y": y, "w": _num(b, "w", 0.05, round(1 - x, 3), min(0.8, 1 - x)),
                           "h": _num(b, "h", 0.02, round(1 - y, 3), min(0.08, 1 - y)), "amount": _num(b, "amount", 1, 10, 5)}
    return out


def blur_filter(blur: Optional[dict], width: int, height: int, src: str = "[0:v]", out: str = "[vb]") -> str:
    """ffmpeg graph that blurs the ``blur`` rectangle of ``src`` into ``out``
    (crop → boxblur → overlay). Empty when there is nothing to blur."""
    if not blur:
        return ""
    x, y = int(width * blur["x"]) // 2 * 2, int(height * blur["y"]) // 2 * 2
    w = max(16, min(width - x, int(width * blur["w"]) // 2 * 2))
    h = max(8, min(height - y, int(height * blur["h"]) // 2 * 2))
    # boxblur refuses a radius above half the plane; chroma planes are half the crop.
    radius = max(2, min(min(w, h) // 4 - 1, round(h * blur["amount"] / 60)))
    return (f"{src}split[vb_base][vb_t];[vb_t]crop={w}:{h}:{x}:{y},boxblur={radius}:2:{max(1, radius // 2)}:2[vb_b];"
            f"[vb_base][vb_b]overlay={x}:{y}{out}")


def video_filter(ass: Path, width: int, height: int, layout: Optional[dict]) -> str:
    """The whole ``-filter_complex`` video part: optional blur, then subtitles → ``[v]``."""
    lay = normalize_layout(layout)
    blur = blur_filter(lay["blur"], width, height)
    src = "[vb]" if blur else "[0:v]"
    return (blur + ";" if blur else "") + f"{src}ass='{_filter_path(ass)}'[v]"


def sub_font_px(height: int, scale: float = 1.0) -> int:
    return max(20, round(height * 0.036 * scale))


def sub_max_chars(width: int, height: int, layout: Optional[dict] = None) -> int:
    """How many characters fit one subtitle line: Arial Bold averages ~0.56 em
    per character; the line may use the frame minus the side margins, and an
    off-centre box only the narrower side twice."""
    lay = normalize_layout(layout)
    usable = width * max(0.3, 2 * min(lay["x"], 1 - lay["x"]) - 2 * SUB_MARGIN_X_FRAC)
    return max(10, min(SUB_MAX_CHARS, int(usable / (sub_font_px(height, lay["scale"]) * 0.56))))


def write_sub_ass(cues: list[tuple[float, float, str]], path: Path, *, width: int, height: int, style: str = "box_yellow",
                  layout: Optional[dict] = None) -> Path:
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
    header = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        line, "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    events = [f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Sub,,0,0,0,,{pos}{t.replace(chr(10), ' ')}" for s, e, t in cues if t.strip()]
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

    def public(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "src": self.src, "text": self.text}


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
    width: int = 0
    height: int = 0
    #: voice + lines the current voice.wav was made from (re-renders that only
    #: move the subtitles reuse it)
    voice_key: str = ""
    channel_id: Optional[int] = None
    name: str = ""
    auto_render: bool = True
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
            "url": self.url, "source_media_id": self.source_media_id, "voice": self.voice, "keep_bgm": self.keep_bgm,
            "style": self.style, "engine": self.engine, "layout": dict(self.layout), "channel_id": self.channel_id, "name": self.name, "language": self.language,
            "width": self.width, "height": self.height,
            "title": self.title, "duration_s": round(self.duration_s, 1),
            "segments": [s.public() for s in self.segments],
        }
        if self.media_id:
            out["media_id"] = self.media_id
            out["media_url"] = f"/media/{self.media_id}"
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
    err = _run(cmd, 300)
    if err:
        raise DubError(f"không tách được tiếng: {err}")


async def _translate(job: Job) -> None:
    lines = [f"[{i + 1}] ({s.start:.1f}s–{s.end:.1f}s) {s.src}" for i, s in enumerate(job.segments)]
    prompt = (f"Source language: {job.language or 'unknown'}. Video title: {job.title or '-'}.\n"
              f"TRANSCRIPT ({len(lines)} lines):\n" + "\n".join(lines) + "\n\nTranslate now.")
    try:
        text = await run_llm("auto_prompt", prompt, system_prompt=_TRANSLATE_SYSTEM, timeout=LLM_TIMEOUT_S)
    except LLMError as exc:
        raise DubError(f"dịch thất bại: {exc}") from exc
    title, vi = parse_translation(text, len(job.segments))
    for seg, line in zip(job.segments, vi):
        seg.text = line
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


def _voice_pieces(job: Job) -> list[tuple[float, Path, float]]:
    """TTS for every line, each converted to 48 kHz mono WAV and sped up to
    fit its slot. Returns ``[(start, wav, duration)]``."""
    ffmpeg = _ffmpeg()
    pieces: list[tuple[float, Path, float]] = []
    spoken = [s for s in job.segments if s.text.strip()]
    for i, seg in enumerate(spoken):
        _set(job, f"Đang tạo giọng đọc ({i + 1}/{len(spoken)})", 62 + int(18 * i / max(1, len(spoken))))
        try:
            narr = asyncio.run(tts.synthesize(seg.text, job.voice, 0))
        except tts.TTSError as exc:
            raise DubError(f"giọng đọc lỗi ở câu {i + 1}: {exc}") from exc
        slot = max(0.4, seg.end - seg.start)
        factor = speedup_for(narr.duration, slot)
        wav = job.work / f"v{i:03d}.wav"
        af = ["aresample=48000", "aformat=sample_fmts=s16:channel_layouts=mono"]
        if factor > 1.0:
            af.insert(0, f"atempo={factor}")
        err = _run([ffmpeg, "-y", "-v", "error", "-i", str(narr.path), "-af", ",".join(af), "-c:a", "pcm_s16le", str(wav)], 120)
        if err:
            raise DubError(f"không chuyển được giọng câu {i + 1}: {err}")
        # ffprobe-measured when possible (probe_clip is video-only), else computed.
        dur = tts._probe_duration(wav) or (narr.duration / factor)
        pieces.append((seg.start, wav, dur))
    return pieces


def _timeline_wav(ffmpeg: str, pieces: list[tuple[float, Path, float]], total_s: float, out: Path) -> None:
    """The voice pieces at their start times on one silent track. A piece
    that overruns its slot pushes the next one later (never overlaps)."""
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


def voice_key(job: Job) -> str:
    return job.voice + "|" + "\x1f".join(s.text for s in job.segments)


def _render(job: Job) -> None:
    ffmpeg = _ffmpeg()
    job.status = "rendering"
    assert job.work is not None and job.src_path is not None
    src = job.src_path
    info = probe_clip(src)
    if info is None:
        raise DubError("Không đọc được video")
    job.width, job.height = info.width, info.height
    voice = job.work / "voice.wav"
    key = voice_key(job)
    if voice.is_file() and job.voice_key == key:
        _set(job, "Dùng lại giọng đã đọc", 81)  # only the subtitles / layout changed
    else:
        pieces = _voice_pieces(job)
        _set(job, "Đang xếp giọng theo thời gian", 81)
        _timeline_wav(ffmpeg, pieces, info.duration, voice)
        job.voice_key = key
    bgm: Optional[Path] = None
    if job.keep_bgm:
        if status().get("separate"):
            bgm = job.work / "bgm.wav"
            if not bgm.is_file():
                _set(job, "Đang tách nhạc nền khỏi tiếng gốc", 84)
                full = job.work / "full44.wav"
                _extract_wav(ffmpeg, src, full, 44100, False)
                _runner("separate", str(full), str(job.work / "vocals.wav"), str(bgm),
                        progress=lambda p: _set(job, "Đang tách nhạc nền khỏi tiếng gốc", 84 + p * 0.06), stop=lambda: job.stop)
        else:
            logger.warning("dub: keep_bgm asked but spleeter models are missing; original audio dropped")
    _set(job, "Đang ghép video + phụ đề", 91)
    cues: list[tuple[float, float, str]] = []
    max_chars = sub_max_chars(info.width, info.height, job.layout)
    for s in job.segments:
        cues += split_cue(s.start, s.end, s.text, max_chars)
    if job.engine == "remotion":
        _render_remotion(job, ffmpeg, src, voice, bgm, info, cues)
        return
    ass = write_sub_ass(cues, job.work / "subs.ass", width=info.width, height=info.height, style=job.style, layout=job.layout)
    media_id = uuid.uuid4().hex
    dst = media_service.MEDIA_CACHE_DIR / f"{media_id}.mp4"
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src), "-i", str(voice)]
    vgraph = video_filter(ass, info.width, info.height, job.layout)
    if bgm is not None:
        cmd += ["-i", str(bgm), "-filter_complex",
                f"{vgraph};[2:a]volume={BGM_VOLUME}[b];[1:a][b]amix=inputs=2:duration=first:normalize=0[a]",
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-filter_complex", vgraph, "-map", "[v]", "-map", "1:a:0"]
    cmd += [*_encode_args(ffmpeg), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest",
            "-movflags", "+faststart", str(dst)]
    err = _run(cmd, 1200)
    if err or not dst.is_file() or dst.stat().st_size == 0:
        raise DubError(f"ffmpeg ghép lỗi: {err or 'file rỗng'}")
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(dst), mime="video/mp4"))
        s.commit()
    job.media_id = media_id
    _set(job, "Đang lưu thành clip", 97)
    job.board_id = _save_board(job)
    job.phase, job.progress, job.status = "Xong", 100, "done"


def _render_remotion(job: Job, ffmpeg: str, src: Path, voice: Path, bgm: Optional[Path], info: Any,
                     cues: list[tuple[float, float, str]]) -> None:
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
        return _run(cmd, 1200)

    err = mux(True)
    if err or not nosub.is_file() or nosub.stat().st_size == 0:
        err = mux(False)  # odd source codec: re-encode instead of copying
    if err or not nosub.is_file() or nosub.stat().st_size == 0:
        raise DubError(f"ffmpeg ghép tiếng lỗi: {err or 'file rỗng'}")
    media_id = uuid.uuid4().hex
    dst = media_service.MEDIA_CACHE_DIR / f"{media_id}.mp4"
    spec = dub_remotion.build_spec(src=nosub, out=dst, cues=cues, layout=job.layout, style=job.style,
                                   width=info.width, height=info.height, duration_s=info.duration)
    labels = {"browser": "Remotion: chuẩn bị Chrome (lần đầu tải ~150 MB)", "bundle": "Remotion: đóng gói giao diện phụ đề (lần đầu)",
              "select": "Remotion: đọc video"}

    def prog(frac: float, phase: str) -> None:
        _set(job, labels.get(phase, "Remotion: đang vẽ phụ đề"), int(92 + frac * 5))

    try:
        dub_remotion.render(spec, progress=prog, stop=lambda: job.stop)
    except dub_remotion.RemotionError as exc:
        raise DubError(str(exc)) from exc
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
                  "keep_bgm": job.keep_bgm, "language": job.language, "source_media_id": job.source_media_id}}
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
        data = job.public() | {"started_at": job.started_at, "auto_render": job.auto_render}
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
            job = Job(id=jid, url=d.get("url"), source_media_id=d.get("source_media_id"),
                      voice=d.get("voice") or tts.DEFAULT_VOICE, keep_bgm=bool(d.get("keep_bgm")),
                      style=d.get("style") or "box_yellow", layout=normalize_layout(d.get("layout")),
                      engine="remotion" if d.get("engine") == "remotion" else "ass",
                      width=int(d.get("width") or 0), height=int(d.get("height") or 0),
                      channel_id=d.get("channel_id"), name=str(d.get("name") or ""),
                      auto_render=bool(d.get("auto_render", True)), language=str(d.get("language") or ""),
                      status=str(d.get("status") or "error"), phase=str(d.get("phase") or ""),
                      progress=int(d.get("progress") or 0), title=str(d.get("title") or ""),
                      duration_s=float(d.get("duration_s") or 0), media_id=d.get("media_id"), board_id=d.get("board_id"),
                      error=d.get("error"), started_at=float(d.get("started_at") or meta.stat().st_mtime), work=meta.parent)
            job.segments = [Segment(float(s["start"]), float(s["end"]), str(s.get("src") or ""), str(s.get("text") or ""))
                            for s in d.get("segments") or []]
            if job.status in ("queued", "running", "rendering"):
                job.status, job.error = "error", "Agent khởi động lại giữa chừng — làm lại từ link"
            src = media_service.cached_path(job.source_media_id or "") if job.source_media_id else None
            job.src_path = Path(src) if src else None
            if (meta.parent / "voice.wav").is_file():
                job.voice_key = voice_key(job)
            JOBS[jid] = job
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("dub: skipped %s: %s", meta, exc)


def start_job(*, url: Optional[str], source_media_id: Optional[str], voice: str, keep_bgm: bool, style: str,
              channel_id: Optional[int], name: str, auto_render: bool, engine: str = "ass") -> Job:
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
              auto_render=auto_render)
    JOBS[job.id] = job
    cutoff = time.time() - 6 * 3600
    for jid in [j.id for j in JOBS.values() if j.status in ("done", "error") and j.started_at < cutoff]:
        JOBS.pop(jid, None)
    _pump()
    return job


# ── queue: one video at a time (Whisper / spleeter share the GPU), up to MAX_QUEUE waiting
MAX_QUEUE = 5
_LOOP: Optional[asyncio.AbstractEventLoop] = None


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
               layout: Optional[dict] = None, engine: Optional[str] = None) -> Job:
    """Render (again) with edited lines / options. Allowed from ``review``,
    ``done`` and ``error`` (after a render failure)."""
    if job.status in ("queued", "running", "rendering"):
        raise DubError("Video này đang chạy")
    if not job.segments or job.src_path is None or not Path(job.src_path).is_file():
        raise DubError("Chưa có bản dịch để render (agent đã khởi động lại?) — làm lại từ link.")
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
