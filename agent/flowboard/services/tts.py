"""Vietnamese voice-over for the "Xuất video" node, through Microsoft Edge's
neural voices (``edge-tts``: free, no key, ~2-4 s per sentence).

One call turns a narration line into an MP3 plus the word timings the
service streams alongside the audio; the export pipeline lays the audio
under the clip and turns the timings into subtitle cues. Results are cached
by (text, voice, rate) under ``storage/media/tts/`` so re-exporting a board
does not re-synthesise lines that did not change.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from flowboard import config

logger = logging.getLogger(__name__)

#: What the export node offers. Edge ships exactly two Vietnamese voices.
VOICES: dict[str, str] = {
    "vi-VN-HoaiMyNeural": "Hoài My (nữ)",
    "vi-VN-NamMinhNeural": "Nam Minh (nam)",
}
DEFAULT_VOICE = "vi-VN-HoaiMyNeural"

TTS_DIR = config.STORAGE_DIR / "media" / "tts"

#: Longest subtitle line, in characters, before the words wrap to a new cue.
SUBTITLE_MAX_CHARS = 34
#: Tries per line before giving up on the service.
ATTEMPTS = 4


class TTSError(RuntimeError):
    pass


@dataclass
class Word:
    start: float  # seconds from the start of the audio
    end: float
    text: str


@dataclass
class Narration:
    path: Path
    duration: float
    words: list[Word] = field(default_factory=list)


def _cache_key(text: str, voice: str, rate: int) -> str:
    return hashlib.sha1(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:20]


def _rate_arg(rate: int) -> str:
    rate = max(-50, min(100, int(rate)))
    return f"{rate:+d}%"


async def synthesize(text: str, voice: str = DEFAULT_VOICE, rate: int = 0) -> Narration:
    """``text`` as spoken MP3 with word timings. Cached on disk."""
    import edge_tts

    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        raise TTSError("empty narration")
    if voice not in VOICES:
        raise TTSError(f"unknown voice {voice!r}; choose one of {list(VOICES)}")
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(text, voice, rate)
    mp3 = TTS_DIR / f"{key}.mp3"
    meta = TTS_DIR / f"{key}.json"
    if mp3.is_file() and meta.is_file():
        try:
            saved = json.loads(meta.read_text(encoding="utf-8"))
            return Narration(mp3, float(saved["duration"]),
                             [Word(**w) for w in saved["words"]])
        except (OSError, ValueError, KeyError, TypeError):
            pass  # a damaged cache entry is simply regenerated

    audio = bytearray()
    words: list[Word] = []
    # The service drops a request now and then ("No audio was received")
    # with nothing wrong in it; the same call succeeds a moment later.
    last_error: Optional[Exception] = None
    for attempt in range(ATTEMPTS):
        audio.clear()
        words.clear()
        try:
            communicate = edge_tts.Communicate(text, voice, rate=_rate_arg(rate), boundary="WordBoundary")
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 1e7
                    words.append(Word(start, start + chunk["duration"] / 1e7, chunk["text"]))
            if audio:
                break
            last_error = TTSError("edge-tts returned no audio")
        except Exception as exc:  # noqa: BLE001 — network / service errors, reported as one kind
            last_error = exc
        logger.info("tts: attempt %d/%d failed (%s); retrying", attempt + 1, ATTEMPTS, last_error)
        await asyncio.sleep(1.0 + attempt)
    if not audio:
        raise TTSError(f"edge-tts failed: {last_error}") from last_error
    mp3.write_bytes(bytes(audio))

    duration = _probe_duration(mp3)
    if duration is None:
        # The last word boundary is a close lower bound.
        duration = (words[-1].end + 0.2) if words else 0.0
    narration = Narration(mp3, duration, words)
    meta.write_text(json.dumps({"duration": duration, "words": [w.__dict__ for w in words]},
                               ensure_ascii=False), encoding="utf-8")
    return narration


def _probe_duration(path: Path) -> Optional[float]:
    import shutil
    import subprocess

    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, timeout=30, check=False,
        ).stdout.decode("utf-8", "replace").strip()
        return float(out) if out else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def subtitle_cues(narration: Narration, text: str, max_chars: int = SUBTITLE_MAX_CHARS) -> list[tuple[float, float, str]]:
    """``[(start, end, line)]`` covering ``text``, each line at most
    ``max_chars`` wide, timed by the word boundaries — or spread evenly over
    the audio when the service sent none."""
    tokens = text.split()
    if not tokens:
        return []
    # Group words into lines first; timing is attached afterwards so the
    # grouping does not depend on whether boundaries arrived.
    lines: list[list[int]] = [[]]
    width = 0
    for i, tok in enumerate(tokens):
        if lines[-1] and width + 1 + len(tok) > max_chars:
            lines.append([])
            width = 0
        lines[-1].append(i)
        width += (1 if width else 0) + len(tok)

    words = narration.words
    aligned = len(words) == len(tokens)
    total = max(narration.duration, 0.1)
    cues: list[tuple[float, float, str]] = []
    for idx, line in enumerate(lines):
        if aligned:
            start = words[line[0]].start
            end = words[line[-1]].end
        else:
            # Proportional to character count when timings are missing or
            # the service tokenised differently from a plain split.
            chars_before = sum(len(tokens[i]) + 1 for group in lines[:idx] for i in group)
            chars_here = sum(len(tokens[i]) + 1 for i in line)
            chars_all = sum(len(t) + 1 for t in tokens)
            start = total * chars_before / chars_all
            end = total * (chars_before + chars_here) / chars_all
        if cues:
            start = max(start, cues[-1][1])
        # Let the last cue hang until the audio ends so it does not blink out.
        if idx == len(lines) - 1:
            end = max(end, total)
        end = max(end, start + 0.3)
        cues.append((start, end, " ".join(tokens[i] for i in line)))
    return cues


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_ass(cues: list[tuple[float, float, str]], path: Path, *, width: int, height: int) -> Path:
    """An ASS file for libass: bold white text with a dark outline near the
    bottom of a 9:16 frame, sized relative to the video."""
    font_size = max(28, round(height * 0.042))
    margin_v = round(height * 0.16)
    header = "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{max(2, font_size // 12)},1,2,40,40,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    events = [
        f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Default,,0,0,0,,{line.replace(chr(10), ' ')}"
        for s, e, line in cues
    ]
    path.write_text(header + "\n" + "\n".join(events) + "\n", encoding="utf-8")
    return path
