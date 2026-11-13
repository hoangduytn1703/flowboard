"""The "Xuất video" node: join clips in order, lay a Vietnamese voice-over
and subtitles on them, optionally smooth to 60 fps.

Plain join is ``video_concat.concat_video_assets``. With narration the
clips go through ffmpeg one by one first (``_voice_clip``): the line is
synthesised with :mod:`tts`, the clip is held on its last frame when the
speech runs longer than the footage, Veo's own soundtrack is ducked under
the voice (or muted / kept), and the subtitle cues are burned in with
libass. The voiced clips share one encode so the join is a stream copy.

Smoothing is frame interpolation: Veo renders 24 fps and has no other
rate, so 60 fps can only come from synthesising the in-between frames.
ffmpeg's ``minterpolate`` (motion-compensated) does that on the CPU at
roughly 14 s of work per second of 720p footage and on ONE core — so on the
per-clip path every source clip is smoothed in its own ffmpeg, side by side
(:func:`smooth_sources`, cached per clip: a re-export reuses them), before
the voice and subtitles go on; 4 clips of 8 s took 156 s instead of ~9 min
for the joined clip (measured 7/11 on a Ryzen 7 5800H). The encode goes
through NVENC when the build has it. A RIFE path (GPU, better edges) can
slot in here later — BUGLOG FB-017.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from flowboard import config
from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.services import tts, video_concat

logger = logging.getLogger(__name__)

# 24 s of footage ≈ 6 min on a laptop CPU; leave headroom for longer joins.
_SMOOTH_TIMEOUT_S = 1800
_MINTERPOLATE = "minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
_CLIP_TIMEOUT_S = 600
#: Clips smoothed at once: minterpolate keeps one core busy, leave the rest of the machine some room.
SMOOTH_PARALLEL = max(1, min(6, (os.cpu_count() or 4) // 2))

#: Veo's own audio under the voice-over, as a volume factor.
ORIGINAL_AUDIO_LEVELS = {"duck": 0.2, "keep": 1.0, "mute": 0.0}
#: Fastest the voice is pushed to fit a clip before the footage is extended.
MAX_AUTO_RATE = 35
#: Room left after the last word so the clip does not cut on it.
_TAIL_S = 0.3
#: Background music under the whole clip: sensible loudness range and the
#: fade before the end so the track does not stop dead.
BGM_DEFAULT_VOLUME = 0.15
BGM_MIN_VOLUME, BGM_MAX_VOLUME = 0.02, 0.6
_BGM_FADE_S = 1.5
#: The cover image (TikTok's 9:16 thumbnail).
COVER_SIZE = (1080, 1920)


@dataclass
class NarrationOptions:
    """Voice-over settings for one export; ``lines`` is aligned with the
    clips (``""`` = this clip stays silent)."""
    lines: list[str]
    voice: str = tts.DEFAULT_VOICE
    rate: int = 0
    subtitles: bool = True
    original_audio: str = "duck"  # duck | keep | mute
    # Spoken-language style for Gemini voices ("giọng kể chuyện kịch tính").
    style: Optional[str] = None
    # Dialogue: ``[A] … [B] …`` tags in a line map to these voices (tag →
    # voice id, up to ``tts.MAX_SPEAKERS``); an unmapped tag speaks with
    # ``voice``.
    speakers: dict[str, str] = field(default_factory=dict)
    # Per-clip voice override aligned with ``lines`` (None = ``voice``).
    line_voices: list[Optional[str]] = field(default_factory=list)
    # Subtitles: "ass" = burned per clip by ffmpeg in ``sub_style`` (tts.SUB_STYLES); "remotion" = drawn on the
    # joined clip by services/dub_remotion in one of its styles (rm_box…) — see :func:`subtitle_choice`.
    sub_engine: str = "ass"
    sub_style: str = "outline"
    # ffmpeg subtitles shown word by word: "" | "grow" | "word" (tts.SUB_REVEALS)
    sub_reveal: str = ""

    def any_line(self) -> bool:
        return any(line.strip() for line in self.lines)

    def voice_for(self, index: int) -> str:
        """The voice clip ``index`` is read with."""
        if index < len(self.line_voices) and self.line_voices[index] in tts.VOICES:
            return self.line_voices[index]  # type: ignore[return-value]
        return self.voice


@dataclass
class ExportItem:
    """One entry of the export order: a rendered clip or a still (drama
    beats), with its own voice line and headline."""
    asset_id: int
    kind: str = "video"  # video | image
    narration: str = ""
    caption: str = ""
    # None = the export's setting; inserted footage usually says "keep".
    original_audio: Optional[str] = None


#: A still with nothing to say stays on screen this long.
STILL_SILENT_S = 4.0
#: Output frame every still is rendered to (9:16 portrait).
STILL_SIZE = (720, 1280)


@dataclass
class ClipReport:
    duration: float
    narration_s: float = 0.0
    extended_s: float = 0.0
    rate: int = 0
    error: Optional[str] = None
    # the clip's subtitle cues (clip time) kept for the Remotion pass on the joined clip; not reported
    cues: list = field(default_factory=list, repr=False)


@dataclass
class ExportReport:
    clips: list[ClipReport] = field(default_factory=list)
    voiced: bool = False
    smooth60: bool = False
    smooth60_error: Optional[str] = None
    bgm: bool = False
    bgm_error: Optional[str] = None
    overlays: int = 0
    overlays_error: Optional[str] = None
    # Flow's ✦ stamp taken out of this many clips (services/video_watermark)
    stamps_cleaned: int = 0
    # subtitles drawn with: "ass" | "remotion" (and why Remotion fell back to ffmpeg)
    subtitles_engine: str = ""
    subtitles_error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "voiced": self.voiced,
            "smooth60": self.smooth60,
            "smooth60_error": self.smooth60_error,
            "bgm": self.bgm,
            "bgm_error": self.bgm_error,
            "overlays": self.overlays,
            "overlays_error": self.overlays_error,
            "stamps_cleaned": self.stamps_cleaned,
            "subtitles_engine": self.subtitles_engine,
            "subtitles_error": self.subtitles_error,
            "clips": [{k: v for k, v in c.__dict__.items() if k != "cues"} for c in self.clips],
        }


@lru_cache(maxsize=1)
def _nvenc_available(ffmpeg: str) -> bool:
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                             timeout=20, check=False).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return False
    if "h264_nvenc" not in out:
        return False
    # Listed is not usable: a build can ship NVENC on a machine with no
    # NVIDIA driver, and then every encode dies opening the encoder. Prove it
    # with one tiny frame.
    try:
        probe = subprocess.run(
            [ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def _encode_args(ffmpeg: str) -> list[str]:
    if _nvenc_available(ffmpeg):
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]


def _low_priority_kwargs() -> dict[str, Any]:
    """subprocess options that run a background ffmpeg below normal priority (Windows class / POSIX nice)."""
    import sys

    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)}
    return {"preexec_fn": lambda: os.nice(10)}  # noqa: PLW1509 — only sets the child's niceness


def _run(cmd: list[str], timeout: int, low_priority: bool = False) -> Optional[str]:
    """Run ffmpeg; None on success, else the stderr tail. ``low_priority`` = work nobody is waiting on (the 60 fps
    warm-up) yields the CPU to everything else."""
    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              timeout=timeout, check=False, **(_low_priority_kwargs() if low_priority else {}))
    except subprocess.TimeoutExpired:
        return f"timed out after {timeout}s"
    except OSError as exc:
        return f"could not launch ffmpeg: {exc}"
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip()
        return tail[-500:] if tail else f"exit code {proc.returncode}"
    return None


def smooth_to_60fps(src: Path, dst: Path, low_priority: bool = False) -> Optional[str]:
    """Interpolate ``src`` to 60 fps into ``dst``. None on success, else why."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return "ffmpeg_not_found"
    cmd = [ffmpeg, "-y", "-i", str(src), "-vf", _MINTERPOLATE,
           *_encode_args(ffmpeg), "-pix_fmt", "yuv420p",
           "-c:a", "copy", "-movflags", "+faststart", str(dst)]
    err = _run(cmd, _SMOOTH_TIMEOUT_S, low_priority=low_priority)
    if err is None and not dst.is_file():
        return "no output file"
    return err


_smooth_locks: dict[str, threading.Lock] = {}
_smooth_locks_guard = threading.Lock()


def smoothed_path(src: Path, cache_dir: Path) -> Path:
    """Where :func:`smoothed_copy` keeps the 60 fps copy of ``src`` (named by the source file + its size)."""
    return cache_dir / f"{src.stem}.{src.stat().st_size}.60.mp4"


def smoothed_copy(src: Path, cache_dir: Path, low_priority: bool = False) -> tuple[Path, Optional[str]]:
    """``src`` at 60 fps, made once into ``cache_dir`` (named by the source file + size, written through a temp file);
    (the copy, None) or (``src``, why) when the smoothing failed. Two exports of the same clip wait for one run."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dst = smoothed_path(src, cache_dir)
    with _smooth_locks_guard:
        lock = _smooth_locks.setdefault(str(dst), threading.Lock())
    with lock:
        if dst.is_file() and dst.stat().st_size > 0:
            return dst, None
        part = dst.with_name(dst.stem + ".part.mp4")
        err = smooth_to_60fps(src, part, low_priority=low_priority)
        if err is None and part.is_file() and part.stat().st_size > 0:
            os.replace(part, dst)
            return dst, None
        part.unlink(missing_ok=True)
        return src, err or "no output file"


def smooth_sources(paths: list[Path]) -> tuple[list[Path], Optional[str]]:
    """Every clip at 60 fps, :data:`SMOOTH_PARALLEL` ffmpegs side by side (minterpolate runs on one core); a clip
    that fails keeps its own frames (the clip encode repeats them up to 60 fps) and the first reason comes back."""
    from concurrent.futures import ThreadPoolExecutor

    from flowboard.services import media as media_service

    cache = media_service.MEDIA_CACHE_DIR / "smooth60"
    with ThreadPoolExecutor(max_workers=max(1, min(SMOOTH_PARALLEL, len(paths)))) as pool:
        done = list(pool.map(lambda p: smoothed_copy(p, cache), paths))
    errors = [err for _p, err in done if err]
    return [p for p, _err in done], (errors[0][:200] if errors else None)


# ── probing ────────────────────────────────────────────────────────────────

@dataclass
class ClipInfo:
    duration: float
    width: int
    height: int
    has_audio: bool


def probe_clip(path: Path) -> Optional[ClipInfo]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, timeout=60, check=False,
        ).stdout.decode("utf-8", "replace")
        info = json.loads(out or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        return None
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    try:
        duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return ClipInfo(duration, int(video.get("width") or 0), int(video.get("height") or 0), has_audio)


# ── one clip with its voice line ───────────────────────────────────────────

def _filter_path(path: Path) -> str:
    """A path the ``subtitles`` filter accepts on Windows: forward slashes,
    the drive colon escaped, single-quoted."""
    text = str(path).replace("\\", "/").replace(":", "\\:").replace("'", r"\'")
    return f"'{text}'"


def _synth_line(text: str, opts: NarrationOptions, rate: int, voice: Optional[str] = None) -> tts.Narration:
    """``text`` spoken by ``voice`` (default: the export's voice). A line
    with ``[A] … [B] …`` tags goes through the multi-voice path; a plain
    line takes exactly the single-voice path it always did (same cache)."""
    voice = voice if voice in tts.VOICES else opts.voice
    if tts.has_speaker_tags(text):
        return asyncio.run(tts.synthesize_dialogue(text, voice, rate, opts.style, opts.speakers))
    return asyncio.run(tts.synthesize(text, voice, rate, opts.style))


def _prefetch_voices(lines: list[str], opts: NarrationOptions) -> None:
    """Every plain line read into the TTS cache before the clips are cut, so the clip loop only hits the cache: a
    VieNeu voice does all its lines in one model load (it loaded the model again for every clip, ~20 s each), Edge
    lines go side by side. Gemini (per-minute quota) and dialogue lines are left to the loop, and so is any failure —
    the loop reports it per clip."""
    groups: dict[str, list[str]] = {}
    for i, line in enumerate(lines):
        text = line.strip()
        if text and not tts.has_speaker_tags(text):
            groups.setdefault(opts.voice_for(i), []).append(text)

    async def read_all() -> None:
        jobs = []
        for voice, texts in groups.items():
            kind = tts.voice_kind(voice)
            if kind == "vieneu":
                jobs.append(tts.synthesize_many(texts, voice, opts.rate, opts.style))
            elif kind == "edge":
                jobs += [tts.synthesize(t, voice, opts.rate, opts.style) for t in texts]
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    try:
        asyncio.run(read_all())
    except Exception as exc:  # noqa: BLE001 — a head start only; the loop reads (and reports) whatever is missing
        logger.warning("video_export: reading the voices ahead failed: %s", str(exc)[:200])


def _synth_to_fit(text: str, opts: NarrationOptions, clip_s: float,
                  voice: Optional[str] = None) -> tuple[tts.Narration, int]:
    """Synthesise ``text``; when it runs well past the clip, speak faster
    (up to ``MAX_AUTO_RATE`` on top of the user's rate) before the footage
    is extended to cover the rest."""
    narration = _synth_line(text, opts, opts.rate, voice)
    rate = opts.rate
    room = clip_s - _TAIL_S
    # VieNeu / FPT.AI ignore the rate: asking again only reloads the model (~20 s) for the same audio
    rate_works = tts.voice_kind(voice if voice in tts.VOICES else opts.voice) not in ("vieneu", "fpt")
    if rate_works and room > 1.0 and narration.duration > room + 0.75:
        needed = math.ceil((narration.duration / room - 1.0) * 100)
        rate = opts.rate + min(MAX_AUTO_RATE, needed)
        narration = _synth_line(text, opts, rate, voice)
    return narration, rate


def _image_clip(ffmpeg: str, src: Path, text: str, opts: NarrationOptions,
                dst: Path, work: Path, caption: str = "", voice: Optional[str] = None,
                size: Optional[tuple[int, int]] = None) -> ClipReport:
    """A still rendered into a portrait clip that lasts as long as its
    voice line: slow push-in (Ken Burns), fade in/out, the headline at the
    top and the subtitles at the bottom."""
    text = text.strip()
    narration: Optional[tts.Narration] = None
    report = ClipReport(0.0)
    if text:
        try:
            narration = _synth_line(text, opts, opts.rate, voice)
            report.narration_s = narration.duration
        except tts.TTSError as exc:
            report.error = str(exc)
            logger.warning("video_export: narration skipped for still %s: %s", src.name, exc)
    length = (narration.duration + _TAIL_S + 0.4) if narration else STILL_SILENT_S
    report.duration = round(length, 2)
    # ``size``: the frame the clips it is joined with share (see common_size).
    w, h = size or STILL_SIZE
    frames = int(length * 24) + 1
    vf = [
        f"scale={w}:{h}:force_original_aspect_ratio=increase",
        f"crop={w}:{h}",
        # One output frame per input frame; zoom creeps up to ~12 %.
        f"zoompan=z='min(zoom+0.0009,1.12)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps=24",
        "fade=t=in:st=0:d=0.4",
        f"fade=t=out:st={max(0.0, length - 0.45):.2f}:d=0.45",
    ]
    if opts.subtitles and (narration is not None or caption):
        cues = tts.subtitle_cues(narration, tts.strip_speaker_tags(text)) if narration is not None else []
        if opts.sub_engine == "remotion":  # the lines go on the joined clip; the headline stays burned here
            report.cues, cues = cues, []
        if cues or caption:
            ass = work / f"{dst.stem}.ass"
            tts.write_ass(cues, ass, width=w, height=h, headline=caption, total_s=length, style=opts.sub_style, reveal=opts.sub_reveal)
            vf.append(f"subtitles={_filter_path(ass)}")
    inputs = ["-loop", "1", "-framerate", "24", "-t", f"{length:.3f}", "-i", str(src)]
    chains = ["[0:v]" + ",".join(vf) + "[v]"]
    if narration is not None:
        inputs += ["-i", str(narration.path)]
        chains.append("[1:a]aresample=48000,apad[a]")
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        chains.append("[1:a]apad[a]")
    cmd = [ffmpeg, "-y", *inputs, "-filter_complex", ";".join(chains),
           "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}", "-frames:v", str(frames),
           *_encode_args(ffmpeg), "-pix_fmt", "yuv420p", "-r", "24",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", str(dst)]
    err = _run(cmd, _CLIP_TIMEOUT_S)
    if err is not None or not dst.is_file() or dst.stat().st_size == 0:
        report.error = (report.error + "; " if report.error else "") + f"ffmpeg: {err or 'no output'}"
    return report


#: A trimmed clip keeps at least this much.
MIN_CLIP_S = 0.5


def clip_window(full: float, trim: Optional[tuple[float, Optional[float]]]) -> tuple[float, float]:
    """``(seek, duration)`` for a clip of ``full`` seconds cut to ``trim``
    (start, end or None = to the end); out-of-range values are clamped."""
    if not trim:
        return 0.0, full
    start = min(max(0.0, float(trim[0] or 0)), max(0.0, full - MIN_CLIP_S))
    end = full if trim[1] is None else min(max(float(trim[1]), start + MIN_CLIP_S), full)
    return start, max(MIN_CLIP_S, end - start)


#: Within this aspect-ratio difference a clip is cropped to fill the frame;
#: past it (a landscape clip in a portrait video) it is letterboxed instead,
#: so nothing important is cut away.
_FILL_ASPECT_TOLERANCE = 0.08


def common_size(sizes: list[tuple[int, int]]) -> Optional[tuple[int, int]]:
    """The frame every clip is fitted to when the clips are not all the same
    size (a Muse / own clip next to Flow's 720×1280): the most common size,
    the first one on a tie. None when they already agree — the join can
    stream-copy then and nothing needs re-sizing."""
    known = [(w, h) for w, h in sizes if w > 0 and h > 0]
    if len(set(known)) <= 1:
        return None
    counts: dict[tuple[int, int], int] = {}
    for size in known:
        counts[size] = counts.get(size, 0) + 1
    best = max(counts.values())
    return next(size for size in known if counts[size] == best)


def fit_filter(src_w: int, src_h: int, size: tuple[int, int]) -> Optional[str]:
    """ffmpeg filters that bring a ``src_w``×``src_h`` clip to ``size``:
    crop-to-fill for a near aspect, letterbox (black bars) for a far one.
    None when the clip already has that size."""
    w, h = size
    if (src_w, src_h) == (w, h) or src_w <= 0 or src_h <= 0:
        return None
    src_aspect, aspect = src_w / src_h, w / h
    if abs(src_aspect - aspect) / aspect <= _FILL_ASPECT_TOLERANCE:
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")


def _voice_clip(ffmpeg: str, src: Path, text: str, opts: NarrationOptions,
                dst: Path, work: Path, caption: str = "", original_audio: Optional[str] = None,
                voice: Optional[str] = None, trim: Optional[tuple[float, Optional[float]]] = None,
                size: Optional[tuple[int, int]] = None, fps: int = 24) -> ClipReport:
    """``src`` re-encoded into ``dst`` with the voice line, ducked original
    sound and burned subtitles. The clip is held on its last frame when the
    speech outlasts it. ``voice`` overrides the export's voice for this
    clip; ``[A] … [B] …`` tags in ``text`` switch voices mid-line.
    ``size`` fits the clip to that frame first (see :func:`common_size`):
    the join stream-copies, so every clip has to come out the same size —
    and the same ``fps`` (60 when the sources were smoothed first)."""
    info = probe_clip(src)
    if info is None:
        return ClipReport(0.0, error="unreadable clip")
    # ``trim`` = (start, end) in seconds of this clip ("Cắt cảnh" in step 5).
    seek, duration = clip_window(info.duration, trim)
    report = ClipReport(duration)
    text = text.strip()
    audio_mode = original_audio or opts.original_audio

    narration: Optional[tts.Narration] = None
    if text:
        try:
            narration, report.rate = _synth_to_fit(text, opts, duration, voice)
        except tts.TTSError as exc:
            report.error = str(exc)
            logger.warning("video_export: narration skipped for %s: %s", src.name, exc)
    length = duration
    if narration is not None:
        report.narration_s = narration.duration
        length = max(duration, narration.duration + _TAIL_S)
        report.extended_s = round(length - duration, 2)

    inputs = ["-ss", f"{seek:.3f}", "-t", f"{duration:.3f}", "-i", str(src)] if trim else ["-i", str(src)]
    vf = ["[0:v]"]
    out_w, out_h = info.width, info.height
    fit = fit_filter(info.width, info.height, size) if size else None
    if fit:
        vf.append(fit)
        out_w, out_h = size
    if report.extended_s > 0:
        vf.append(f"tpad=stop_mode=clone:stop_duration={report.extended_s:.3f}")
    if opts.subtitles and (narration is not None or caption):
        cues = tts.subtitle_cues(narration, tts.strip_speaker_tags(text)) if narration is not None else []
        if opts.sub_engine == "remotion":  # the lines go on the joined clip; a headline stays burned here
            report.cues, cues = cues, []
        if cues or caption:
            ass = work / f"{dst.stem}.ass"
            tts.write_ass(cues, ass, width=out_w, height=out_h, headline=caption, total_s=length, style=opts.sub_style, reveal=opts.sub_reveal)
            vf.append(f"subtitles={_filter_path(ass)}")
    video_chain = (vf[0] + ",".join(vf[1:]) if len(vf) > 1 else vf[0] + "null") + "[v]"

    level = ORIGINAL_AUDIO_LEVELS.get(audio_mode, 0.2) if narration is not None else 1.0
    chains = [video_chain]
    audio_sources: list[str] = []
    if info.has_audio and level > 0:
        chains.append(f"[0:a]volume={level},aresample=48000,apad[org]")
        audio_sources.append("[org]")
    if narration is not None:
        inputs += ["-i", str(narration.path)]
        chains.append("[1:a]aresample=48000,apad[nar]")
        audio_sources.append("[nar]")
    if not audio_sources:
        # No usable sound at all: a silent track keeps every clip's layout
        # identical so the join can stream-copy.
        # Its input index is the count of inputs before it — counting tokens
        # (`len(inputs) // 2`) broke on the 4-token lavfi input and on a
        # trimmed source (`-ss … -t … -i`): "Error binding filtergraph".
        silent_index = inputs.count("-i")
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        chains.append(f"[{silent_index}:a]apad[a]")
    elif len(audio_sources) == 1:
        chains.append(f"{audio_sources[0]}anull[a]")
    else:
        chains.append(f"{''.join(audio_sources)}amix=inputs=2:duration=longest:normalize=0[a]")

    cmd = [ffmpeg, "-y", *inputs, "-filter_complex", ";".join(chains),
           "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}",
           *_encode_args(ffmpeg), "-pix_fmt", "yuv420p", "-r", str(fps),
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", str(dst)]
    err = _run(cmd, _CLIP_TIMEOUT_S)
    if err is not None or not dst.is_file():
        report.error = (report.error + "; " if report.error else "") + f"ffmpeg: {err or 'no output'}"
    return report


def mix_background_music(src: Path, music: Path, dst: Path, volume: float = BGM_DEFAULT_VOLUME) -> Optional[str]:
    """``src`` with ``music`` looped underneath at ``volume``, fading out
    over the last 1.5 s; the video stream is copied. None on success,
    else why."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return "ffmpeg_not_found"
    info = probe_clip(src)
    if info is None or info.duration <= 0:
        return "unreadable clip"
    volume = max(BGM_MIN_VOLUME, min(BGM_MAX_VOLUME, float(volume)))
    length = info.duration
    fade_start = max(0.0, length - _BGM_FADE_S)
    bg = (f"[1:a]aresample=48000,atrim=0:{length:.3f},volume={volume:.3f},"
          f"afade=t=out:st={fade_start:.3f}:d={_BGM_FADE_S}[bg]")
    if info.has_audio:
        chains = [bg, "[0:a]aresample=48000[org]",
                  "[org][bg]amix=inputs=2:duration=first:normalize=0[a]"]
    else:
        chains = [bg, "[bg]anull[a]"]
    cmd = [ffmpeg, "-y", "-i", str(src), "-stream_loop", "-1", "-i", str(music),
           "-filter_complex", ";".join(chains),
           "-map", "0:v", "-map", "[a]", "-t", f"{length:.3f}",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", str(dst)]
    err = _run(cmd, _CLIP_TIMEOUT_S)
    if err is None and (not dst.is_file() or dst.stat().st_size == 0):
        return "no output file"
    return err


def render_cover(src: Path, dst: Path, title: str, *, subtitle: Optional[str] = None,
                 style: str = "yellow") -> Optional[str]:
    """A 1080×1920 PNG cover from a scene image: the picture scaled and
    cropped to fill, a dark gradient band over the bottom third, the title
    (and subtitle) burned in through libass. None on success, else why."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return "ffmpeg_not_found"
    if not title or not title.strip():
        return "empty title"
    w, h = COVER_SIZE
    dst.parent.mkdir(parents=True, exist_ok=True)
    ass = dst.with_suffix(".ass")
    tts.write_cover_ass(title, ass, width=w, height=h, subtitle=subtitle, style=style)
    band_top = round(h * 0.57)
    chains = [
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},format=rgba[b]",
        # A black layer whose alpha ramps 0 → 0.9 from `band_top` to the bottom
        # (the `gradients` filter mishandles alpha and came out upside down).
        f"color=c=black:s={w}x{h}:d=0.1,format=gbrap,"
        f"geq=r=0:g=0:b=0:a='if(lt(Y,{band_top}),0,229*(Y-{band_top})/({h}-{band_top}))',format=rgba[g]",
        f"[b][g]overlay=format=auto,format=rgb24,subtitles={_filter_path(ass)}[v]",
    ]
    cmd = [ffmpeg, "-y", "-loop", "1", "-framerate", "24", "-t", "0.1", "-i", str(src),
           "-filter_complex", ";".join(chains), "-map", "[v]",
           "-frames:v", "1", "-update", "1", str(dst)]
    try:
        err = _run(cmd, 120)
    finally:
        try:
            ass.unlink()
        except OSError:
            pass
    if err is None and (not dst.is_file() or dst.stat().st_size == 0):
        return "no output file"
    return err


def _mixed_frame_size(asset_ids: list[int], items: Optional[list["ExportItem"]]) -> Optional[tuple[int, int]]:
    """:func:`common_size` over the clips about to be joined (stills count as
    :data:`STILL_SIZE`); None when they agree or cannot be read."""
    paths, err = _asset_paths([it.asset_id for it in items] if items else asset_ids)
    if err:
        return None
    sizes: list[tuple[int, int]] = []
    for i, path in enumerate(paths):
        if items and items[i].kind == "image":
            sizes.append(STILL_SIZE)
            continue
        info = probe_clip(path)
        if info is not None:
            sizes.append((info.width, info.height))
    return common_size(sizes)


def _asset_paths(asset_ids: list[int]) -> tuple[list[Path], Optional[str]]:
    paths: list[Path] = []
    with get_session() as s:
        for aid in asset_ids:
            row = s.get(Asset, aid)
            if row is None or not row.local_path:
                return [], f"asset_not_found: {aid}"
            p = Path(row.local_path)
            if not p.is_file():
                return [], f"missing_file: Asset {aid} local file is gone"
            paths.append(p)
    return paths, None


def _register(path: Path) -> str:
    with get_session() as s:
        row = Asset(kind="video", node_id=None, uuid_media_id=uuid.uuid4().hex,
                    local_path=str(path), mime="video/mp4")
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.uuid_media_id


def _join_voiced(ffmpeg: str, clips: list[Path], out_path: Path) -> Optional[str]:
    """Stream-copy join of clips that share ``_voice_clip``'s encode."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        list_file = Path(tf.name)
        for p in clips:
            tf.write(f"file '{str(p).replace(chr(39), chr(39) + chr(92) + chr(39))}'\n")
    try:
        err = video_concat._run_concat(ffmpeg, list_file, out_path, reencode=False)
        if err is not None:
            err = video_concat._run_concat(ffmpeg, list_file, out_path, reencode=True)
        return err
    finally:
        try:
            list_file.unlink()
        except OSError:
            pass


REMOTION_TO_ASS = {"rm_box": "box_yellow", "rm_karaoke": "box_yellow", "rm_outline": "outline"}


def subtitle_choice(engine: Any, style: Any) -> tuple[str, str]:
    """``(engine, style)`` as asked when possible: "remotion" with one of its styles when Remotion runs on this
    machine, else the nearest ffmpeg look; "ass" with one of tts.SUB_STYLES."""
    if engine == "remotion":
        from flowboard.services import dub_remotion

        ok, _reason = dub_remotion.available()
        if ok:
            return "remotion", style if style in dub_remotion.STYLES else dub_remotion.DEFAULT_STYLE
        style = REMOTION_TO_ASS.get(style, "box_yellow")
    return "ass", style if style in tts.SUB_STYLES else "outline"


def _timeline_cues(clips: list[ClipReport], voiced: list[Path]) -> list[tuple[float, float, str]]:
    """Every clip's subtitle cues moved onto the joined clip's timeline (each clip's real length, probed)."""
    out: list[tuple[float, float, str]] = []
    t = 0.0
    for clip, path in zip(clips, voiced):
        out += [(round(s + t, 3), round(e + t, 3), line) for s, e, line in clip.cues if line.strip()]
        info = probe_clip(path)
        t += info.duration if info else clip.duration + clip.extended_s
    return out


def _remotion_subtitles(joined: Path, cues: list[tuple[float, float, str]], style: str, out_dir: Path,
                        fps: Optional[int] = None) -> Path:
    """The joined clip with its subtitles drawn by Remotion (the dubbing tool's composition, sound kept);
    ``fps`` = render rate when not Remotion's default (60 for a smoothed clip, so the smoothing is kept)."""
    from flowboard.services import dub_remotion

    info = probe_clip(joined)
    if info is None:
        raise RuntimeError("không đọc được clip đã ghép")
    out = out_dir / f"subs_{uuid.uuid4().hex}.mp4"
    # where the ffmpeg subtitles sit (16 % above the bottom), so both engines look alike
    spec = dub_remotion.build_spec(src=joined, out=out, cues=cues, layout={"x": 0.5, "y": 0.84, "scale": 1.0},
                                   style=style, width=info.width, height=info.height, duration_s=info.duration,
                                   fps=fps or dub_remotion.FPS)
    try:
        return dub_remotion.render(spec)
    finally:
        out.with_suffix(".remotion.json").unlink(missing_ok=True)  # the spec render() leaves next to the output


def _burn_cues(ffmpeg: str, joined: Path, cues: list[tuple[float, float, str]], style: str, out_dir: Path,
               reveal: str = "") -> Optional[Path]:
    """The ffmpeg fallback when Remotion fails: the same cues burned onto the joined clip."""
    info = probe_clip(joined)
    if info is None:
        return None
    out = out_dir / f"subs_{uuid.uuid4().hex}.mp4"
    ass = out.with_suffix(".ass")
    tts.write_ass(cues, ass, width=info.width, height=info.height, style=style, reveal=reveal)
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(joined), "-vf", f"subtitles={_filter_path(ass)}",
           *_encode_args(ffmpeg), "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out)]
    proc = subprocess.run(cmd, capture_output=True, timeout=_SMOOTH_TIMEOUT_S, check=False)
    ass.unlink(missing_ok=True)
    return out if proc.returncode == 0 and out.is_file() and out.stat().st_size > 0 else None


def _stamp_free_paths(asset_ids: list[int], items: Optional[list["ExportItem"]]) -> dict[int, Path]:
    """Flow's ✦ stamp taken out of the clips (services/video_watermark): {clip index: the stamp-free copy}. The
    copies are usually ready — made in the background when the clips landed — else made now, three at a time;
    a clip without the stamp (the seller's own, Muse…) is not in the result."""
    from concurrent.futures import ThreadPoolExecutor

    from flowboard.services import media as media_service, video_watermark

    if not video_watermark.turned_on():
        return {}
    paths, err = _asset_paths(asset_ids)
    if err:
        return {}
    todo = [(i, p) for i, p in enumerate(paths)
            if not (items and i < len(items) and items[i].kind == "image")
            and p.suffix.lower() in (".mp4", ".mov", ".m4v", ".webm")]
    if not todo:
        return {}
    cache = media_service.MEDIA_CACHE_DIR / "clean"
    with ThreadPoolExecutor(max_workers=3) as pool:
        done = list(pool.map(lambda ip: video_watermark.cleaned_copy(ip[1], cache), todo))
    return {i: c for (i, p), c in zip(todo, done) if c != p}


def export_video(
    asset_ids: list[int],
    *,
    smooth60: bool,
    narration: Optional[NarrationOptions] = None,
    items: Optional[list[ExportItem]] = None,
    bgm_asset_id: Optional[int] = None,
    bgm_volume: float = BGM_DEFAULT_VOLUME,
    trims: Optional[list[Optional[tuple[float, Optional[float]]]]] = None,
    overlays: Optional[list[Any]] = None,
) -> tuple[Optional[str], Optional[str], dict[str, Any]]:
    """Join ``asset_ids`` in order, with voice-over when ``narration`` has
    any line, then background music (``bgm_asset_id``: an audio Asset
    looped under the whole clip at ``bgm_volume``), then optional 60 fps.
    Returns (media_id, error, report). A failed music mix or smoothing
    hands back the plain join with the reason in the report.

    ``items`` (drama clips) is the explicit order with stills and clips
    mixed; it replaces ``asset_ids`` + ``narration.lines`` and always goes
    through the per-item renderer, since stills have to become clips.

    ``trims`` (aligned with the clips) cuts each clip to (start, end) and
    forces the per-clip renderer; ``overlays`` (video_overlays.Overlay) are
    burned onto the joined clip before the music."""
    report = ExportReport(smooth60=smooth60)
    out_dir = config.STORAGE_DIR / "media"
    out_dir.mkdir(parents=True, exist_ok=True)
    # frame rate of the clip encode; 60 + smoothed_first when the sources were smoothed before the voice went on
    fps, smoothed_first = 24, False

    if items:
        asset_ids = [it.asset_id for it in items]
        narration = narration or NarrationOptions(lines=[])
        narration.lines = [it.narration for it in items]

    trims = list(trims or [])
    # Clips of different sizes (a Muse clip, the seller's own, stills next to
    # clips) cannot be stream-copied together — the join comes out garbled —
    # so they all go through the per-clip encode, fitted to one frame.
    fit_size = _mixed_frame_size(asset_ids, items)
    # Flow's ✦ stamp out of every clip — the stamp-free copies have to be re-encoded, so the per-clip path
    stamp_free = _stamp_free_paths(asset_ids, items)
    report.stamps_cleaned = len(stamp_free)
    if (any(trims) or fit_size or stamp_free) and narration is None:
        narration = NarrationOptions(lines=[])
    if items or any(trims) or fit_size or stamp_free or (narration is not None and narration.any_line()):
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            return None, "ffmpeg_not_found", report.as_dict()
        paths, err = _asset_paths(asset_ids)
        if err:
            return None, err, report.as_dict()
        paths = [stamp_free.get(i, p) for i, p in enumerate(paths)]
        lines = list(narration.lines) + [""] * (len(paths) - len(narration.lines))
        # The voices are read while the clips are smoothed: both take long and neither needs the other.
        reader = threading.Thread(target=_prefetch_voices, args=(lines, narration), name="export-voices", daemon=True)
        reader.start()
        # 60 fps: every source clip smoothed side by side (cached) before the voice and subtitles go on. Drama
        # stills are animated at 24 fps by _image_clip — those still smooth the joined clip at the end.
        if smooth60 and not items:
            smoothed, smooth_err = smooth_sources(paths)
            report.smooth60_error = smooth_err
            if any(s != p for s, p in zip(smoothed, paths)):
                paths, fps, smoothed_first = smoothed, 60, True
            else:  # nothing came out: the 24 fps join, as the old path did on a failed smoothing
                report.smooth60 = False
        reader.join()
        work = out_dir / "tts" / f"export_{uuid.uuid4().hex}"
        work.mkdir(parents=True, exist_ok=True)
        voiced: list[Path] = []
        for i, (src, line) in enumerate(zip(paths, lines)):
            dst = work / f"clip{i:02d}.mp4"
            item = items[i] if items else None
            line_voice = narration.voice_for(i)
            if item is not None and item.kind == "image":
                clip = _image_clip(ffmpeg, src, line, narration, dst, work, caption=item.caption,
                                   voice=line_voice, size=fit_size)
            else:
                clip = _voice_clip(ffmpeg, src, line, narration, dst, work,
                                   caption=item.caption if item else "",
                                   original_audio=item.original_audio if item else None,
                                   voice=line_voice, trim=trims[i] if i < len(trims) else None,
                                   size=fit_size, fps=fps)
            report.clips.append(clip)
            # ffmpeg leaves a 0-byte file behind when an encode fails, so
            # "exists" is not "worked".
            if clip.error and (not dst.is_file() or dst.stat().st_size == 0):
                return None, f"clip {i + 1}: {clip.error}", report.as_dict()
            voiced.append(dst)
        joined_path = out_dir / f"export_{uuid.uuid4().hex}.mp4"
        err = _join_voiced(ffmpeg, voiced, joined_path)
        if err is not None or not joined_path.is_file():
            return None, f"ffmpeg_failed: {(err or 'no output')[:300]}", report.as_dict()
        report.voiced = True
        joined_media = _register(joined_path)
        report.subtitles_engine = narration.sub_engine if narration.subtitles else ""
        cues = _timeline_cues(report.clips, voiced) if narration.subtitles and narration.sub_engine == "remotion" else []
        if cues:
            try:
                drawn = _remotion_subtitles(joined_path, cues, narration.sub_style, out_dir, fps=fps if smoothed_first else None)
            except Exception as exc:  # noqa: BLE001 — Remotion missing / failed: the same lines burned by ffmpeg
                logger.warning("video_export: Remotion subtitles failed (%s); burning them with ffmpeg", str(exc)[:200])
                report.subtitles_error = str(exc)[:200]
                report.subtitles_engine = "ass"
                drawn = _burn_cues(ffmpeg, joined_path, cues, REMOTION_TO_ASS.get(narration.sub_style, "box_yellow"), out_dir,
                                   narration.sub_reveal)
            if drawn is not None:
                joined_path = drawn
                joined_media = _register(drawn)
    else:
        joined_id, err = video_concat.concat_video_assets(asset_ids)
        if err or joined_id is None:
            return None, err or "concat_failed", report.as_dict()
        with get_session() as s:
            joined = s.get(Asset, joined_id)
            joined_media, joined_path = joined.uuid_media_id, Path(joined.local_path)

    if overlays:
        from flowboard.services.video_overlays import burn_overlays

        text_path = out_dir / f"text_{uuid.uuid4().hex}.mp4"
        err = burn_overlays(joined_path, text_path, overlays)
        if err:
            logger.warning("video_export: text overlays failed (%s); keeping the join", err[:160])
            report.overlays_error = err[:200]
        else:
            report.overlays = len(overlays)
            joined_path = text_path
            joined_media = _register(text_path)

    if bgm_asset_id is not None:
        music, err = _asset_paths([bgm_asset_id])
        if err:
            report.bgm_error = err
        else:
            bgm_path = out_dir / f"bgm_{uuid.uuid4().hex}.mp4"
            err = mix_background_music(joined_path, music[0], bgm_path, bgm_volume)
            if err:
                logger.warning("video_export: background music failed (%s); keeping the join", err[:160])
                report.bgm_error = err[:200]
            else:
                report.bgm = True
                joined_path = bgm_path
                joined_media = _register(bgm_path)

    if not smooth60 or smoothed_first or (report.smooth60_error and not report.smooth60):
        return joined_media, None, report.as_dict()

    out_path = out_dir / f"smooth60_{uuid.uuid4().hex}.mp4"
    err = smooth_to_60fps(joined_path, out_path)
    if err:
        # The join itself is fine; hand it back rather than lose the work.
        logger.warning("video_export: 60 fps smoothing failed (%s); returning the 24 fps join", err[:160])
        report.smooth60 = False
        report.smooth60_error = err[:200]
        return joined_media, None, report.as_dict()
    return _register(out_path), None, report.as_dict()
