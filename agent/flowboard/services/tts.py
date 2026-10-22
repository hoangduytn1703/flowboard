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
    "vi-VN-HoaiMyNeural": "Hoài My (nữ) · Edge",
    "vi-VN-NamMinhNeural": "Nam Minh (nam) · Edge",
}
DEFAULT_VOICE = "vi-VN-HoaiMyNeural"

#: Gemini TTS prebuilt voices (multilingual, speak Vietnamese well; the
#: style is steered by a natural-language instruction). Ids are
#: ``gemini:<Name>``; the pool of Gemini API keys serves them, so there are
#: no extra accounts to set up. Labels: gender + character, in Vietnamese.
GEMINI_VOICES: dict[str, str] = {
    "gemini:Kore": "Kore (nữ, chắc giọng)",
    "gemini:Aoede": "Aoede (nữ, nhẹ nhàng)",
    "gemini:Leda": "Leda (nữ, trẻ trung)",
    "gemini:Sulafat": "Sulafat (nữ, ấm áp)",
    "gemini:Gacrux": "Gacrux (nữ, chững chạc)",
    "gemini:Despina": "Despina (nữ, mượt)",
    "gemini:Laomedeia": "Laomedeia (nữ, sôi nổi)",
    "gemini:Puck": "Puck (nam, vui tươi)",
    "gemini:Charon": "Charon (nam, kể chuyện)",
    "gemini:Fenrir": "Fenrir (nam, hào hứng)",
    "gemini:Orus": "Orus (nam, chắc giọng)",
    "gemini:Achird": "Achird (nam, thân thiện)",
    "gemini:Algenib": "Algenib (nam, khàn)",
    "gemini:Sadaltager": "Sadaltager (nam, hiểu biết)",
}
VOICES.update({k: f"{v} · Gemini" for k, v in GEMINI_VOICES.items()})


def is_gemini_voice(voice: str) -> bool:
    return voice.startswith("gemini:")


#: One sentence every voice reads for the "Nghe thử" button; cached like
#: any other line, so a voice is only synthesised once per style.
PREVIEW_TEXT = ("Xin chào, đây là giọng đọc mẫu cho clip bán hàng của bạn. "
                "Sản phẩm này đang giảm giá hôm nay, đặt ngay kẻo hết nhé!")


async def preview(voice: str, style: Optional[str] = None, text: Optional[str] = None) -> Path:
    """The sample sentence (or ``text``, e.g. a saved model's own line)
    spoken by ``voice`` (``style`` matters for Gemini voices only); the file
    lives under ``TTS_DIR``, cached by text + voice + style like any line."""
    narration = await synthesize((text or "").strip() or PREVIEW_TEXT, voice, 0, style)
    return narration.path


def voice_groups() -> list[dict]:
    """For the voice pickers: Edge (free, instant) and Gemini (many voices,
    needs an API key in the pool)."""
    from flowboard.services.llm import gemini_api

    return [
        {"id": "edge", "label": "Microsoft Edge — miễn phí, nhanh",
         "voices": [{"id": k, "label": v} for k, v in VOICES.items() if not is_gemini_voice(k)]},
        {"id": "gemini", "label": "Gemini — nhiều giọng, chỉnh được phong cách",
         "available": gemini_api.configured(),
         "voices": [{"id": k, "label": v} for k, v in VOICES.items() if is_gemini_voice(k)]},
    ]

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


#: Bumped when the Gemini prompt changes, so cached lines are re-spoken
#: (v2: style no longer read aloud).
GEMINI_PROMPT_VERSION = "v2"


def _cache_key(text: str, voice: str, rate: int, style: str = "") -> str:
    if is_gemini_voice(voice):
        voice = f"{voice}|{GEMINI_PROMPT_VERSION}"
    return hashlib.sha1(f"{voice}|{rate}|{style}|{text}".encode("utf-8")).hexdigest()[:20]


def gemini_tts_prompt(text: str, style: Optional[str], rate: int = 0) -> str:
    """The prompt Gemini TTS reads from: director's notes, then the transcript.

    It used to be ``"<style>: <text>"``; with a bare style such as "GIỌNG HÀO
    HỨNG" Gemini read the style aloud at the start of every clip (2026-10-22).
    The notes are now a separate, labelled block that says not to voice it,
    and only the transcript block is meant to be spoken."""
    notes = [style.strip()] if style and style.strip() else ["tự nhiên, rõ ràng"]
    if rate >= 15:
        notes.append("nói nhanh hơn bình thường")
    elif rate <= -15:
        notes.append("nói chậm rãi")
    return (
        "Read the TRANSCRIPT below aloud in Vietnamese, exactly as written, nothing before or after it.\n"
        "The DIRECTOR'S NOTES only describe how to sound — never say them.\n\n"
        f"### DIRECTOR'S NOTES\nGiọng đọc: {', '.join(notes)}\n\n"
        f"### TRANSCRIPT\n{text.strip()}"
    )


async def _synth_gemini(text: str, voice: str, rate: int, style: Optional[str], out: Path) -> None:
    """Gemini TTS: the style instruction is spoken language, so the rate
    becomes a hint too. Writes a WAV (24 kHz PCM) to ``out``."""
    from flowboard.services.llm import gemini_api

    prompt = gemini_tts_prompt(text, style, rate)
    try:
        wav = await gemini_api.speak(prompt, voice.split(":", 1)[1])
    except gemini_api.GeminiAPIError as exc:
        raise TTSError(f"Gemini TTS: {exc}") from exc
    out.write_bytes(wav)


def _rate_arg(rate: int) -> str:
    rate = max(-50, min(100, int(rate)))
    return f"{rate:+d}%"


async def synthesize(text: str, voice: str = DEFAULT_VOICE, rate: int = 0,
                     style: Optional[str] = None) -> Narration:
    """``text`` as spoken audio (MP3 from Edge, WAV from Gemini) with word
    timings where the service gives them. Cached on disk. ``style`` is a
    spoken-language instruction for Gemini voices ("giọng kể chuyện kịch
    tính"); Edge voices ignore it."""
    import edge_tts

    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        raise TTSError("empty narration")
    if voice not in VOICES:
        raise TTSError(f"unknown voice {voice!r}; choose one of {list(VOICES)}")
    gemini = is_gemini_voice(voice)
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(text, voice, rate, style or "" if gemini else "")
    mp3 = TTS_DIR / (f"{key}.wav" if gemini else f"{key}.mp3")
    meta = TTS_DIR / f"{key}.json"
    if mp3.is_file() and meta.is_file():
        try:
            saved = json.loads(meta.read_text(encoding="utf-8"))
            return Narration(mp3, float(saved["duration"]),
                             [Word(**w) for w in saved["words"]])
        except (OSError, ValueError, KeyError, TypeError):
            pass  # a damaged cache entry is simply regenerated

    if gemini:
        await _synth_gemini(text, voice, rate, style, mp3)
        duration = _probe_duration(mp3) or 0.0
        # No word timings from Gemini: the cues spread over the audio.
        narration = Narration(mp3, duration, [])
        meta.write_text(json.dumps({"duration": duration, "words": []}), encoding="utf-8")
        return narration

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


# ── dialogue: several voices in one line ───────────────────────────────────

#: ``[A]`` / ``[b2]`` in a narration line marks who speaks what follows.
SPEAKER_TAG = re.compile(r"\[([A-Za-z0-9]{1,8})\]")
#: Silence between two speakers' turns.
DIALOGUE_GAP_S = 0.3
#: Export nodes may name this many speakers.
MAX_SPEAKERS = 4


def parse_speakers(text: str) -> list[tuple[Optional[str], str]]:
    """``[(tag, segment)]`` of a narration line: ``"[A] Ủa áo này? [b] Mát
    lắm."`` → ``[("A", "Ủa áo này?"), ("B", "Mát lắm.")]``. Tags are
    upper-cased; text before the first tag has tag None; empty segments
    are dropped."""
    text = text or ""
    out: list[tuple[Optional[str], str]] = []
    pos = 0
    tag: Optional[str] = None
    for m in SPEAKER_TAG.finditer(text):
        seg = text[pos:m.start()].strip()
        if seg:
            out.append((tag, seg))
        tag = m.group(1).upper()
        pos = m.end()
    seg = text[pos:].strip()
    if seg:
        out.append((tag, seg))
    return out


def has_speaker_tags(text: str) -> bool:
    return bool(text) and SPEAKER_TAG.search(text) is not None


def strip_speaker_tags(text: str) -> str:
    """The line as it should read on screen: tags gone, one space between
    turns. Text without tags is returned untouched."""
    if not has_speaker_tags(text):
        return text
    return " ".join(seg for _, seg in parse_speakers(text))


def _spread_words(text: str, start: float, duration: float) -> list[Word]:
    """Word timings for a segment the service gave none for: proportional
    to character count, so the cues line up with the spoken text roughly."""
    tokens = text.split()
    if not tokens:
        return []
    chars_all = sum(len(t) + 1 for t in tokens)
    words: list[Word] = []
    before = 0
    for tok in tokens:
        s = start + duration * before / chars_all
        before += len(tok) + 1
        words.append(Word(s, start + duration * before / chars_all, tok))
    return words


def _concat_audio(parts: list[Path], out: Path, gap_s: float) -> None:
    """``parts`` back to back with ``gap_s`` of silence between them, as a
    48 kHz mono WAV, through one ffmpeg ``concat`` filter."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TTSError("ffmpeg not found (needed to join the dialogue)")
    inputs: list[str] = []
    chains: list[str] = []
    labels: list[str] = []
    for i, p in enumerate(parts):
        inputs += ["-i", str(p)]
        chains.append(f"[{i}:a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=mono[a{i}]")
        if i > 0:
            chains.append(f"aevalsrc=0:d={gap_s:.3f}:s=48000:c=mono,aformat=sample_fmts=s16[g{i}]")
            labels.append(f"[g{i}]")
        labels.append(f"[a{i}]")
    chains.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]")
    cmd = [ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chains),
           "-map", "[out]", "-c:a", "pcm_s16le", str(out)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TTSError(f"ffmpeg join failed: {exc}") from exc
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
        raise TTSError(f"ffmpeg join failed: {tail or proc.returncode}")


async def synthesize_dialogue(text: str, default_voice: str = DEFAULT_VOICE, rate: int = 0,
                              style: Optional[str] = None,
                              speakers: Optional[dict[str, str]] = None) -> Narration:
    """A line with ``[A] … [B] …`` turns spoken by the voices in
    ``speakers`` (tag → voice id; unknown or missing tag → ``default_voice``),
    joined with :data:`DIALOGUE_GAP_S` of silence between turns. Word
    timings are shifted to the joined audio (turns without timings get
    evenly spread words), so :func:`subtitle_cues` over the tag-free text
    still lines up. Cached like :func:`synthesize`."""
    segments = parse_speakers(text)
    if not segments:
        raise TTSError("empty narration")
    speakers = {str(k).upper(): v for k, v in (speakers or {}).items()}
    plan = [(speakers.get(tag) if tag and speakers.get(tag) in VOICES else default_voice, seg)
            for tag, seg in segments]
    for voice, _ in plan:
        if voice not in VOICES:
            raise TTSError(f"unknown voice {voice!r}; choose one of {list(VOICES)}")

    TTS_DIR.mkdir(parents=True, exist_ok=True)
    recipe = json.dumps([[v, re.sub(r"\s+", " ", s)] for v, s in plan], ensure_ascii=False)
    key = _cache_key(recipe, "dialogue", rate, style or "")
    wav = TTS_DIR / f"{key}.wav"
    meta = TTS_DIR / f"{key}.json"
    if wav.is_file() and meta.is_file():
        try:
            saved = json.loads(meta.read_text(encoding="utf-8"))
            return Narration(wav, float(saved["duration"]), [Word(**w) for w in saved["words"]])
        except (OSError, ValueError, KeyError, TypeError):
            pass

    parts: list[Narration] = []
    for voice, seg in plan:
        parts.append(await synthesize(seg, voice, rate, style if is_gemini_voice(voice) else None))
    _concat_audio([p.path for p in parts], wav, DIALOGUE_GAP_S)

    words: list[Word] = []
    offset = 0.0
    for (_, seg), part in zip(plan, parts):
        if part.words:
            words.extend(Word(w.start + offset, w.end + offset, w.text) for w in part.words)
        else:
            words.extend(_spread_words(seg, offset, part.duration))
        offset += part.duration + DIALOGUE_GAP_S
    duration = _probe_duration(wav)
    if duration is None:
        duration = max(0.0, offset - DIALOGUE_GAP_S)
    narration = Narration(wav, duration, words)
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


def write_ass(cues: list[tuple[float, float, str]], path: Path, *, width: int, height: int,
              headline: Optional[str] = None, total_s: float = 0.0) -> Path:
    """An ASS file for libass: bold white text with a dark outline near the
    bottom of a 9:16 frame, sized relative to the video. ``headline`` (a
    drama beat's on-screen title) sits near the top for the whole clip."""
    font_size = max(28, round(height * 0.042))
    margin_v = round(height * 0.16)
    head_size = max(32, round(height * 0.05))
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
        # Top-centre (alignment 8), warm yellow, heavier outline so it reads
        # over any still.
        f"Style: Headline,Arial,{head_size},&H0040E0FF,&H000000FF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{max(3, head_size // 10)},1,8,40,40,{round(height * 0.12)},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    events = [
        f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Default,,0,0,0,,{line.replace(chr(10), ' ')}"
        for s, e, line in cues
    ]
    if headline and headline.strip():
        end = max(total_s, max((e for _, e, _ in cues), default=0.0), 0.5)
        events.insert(0, f"Dialogue: 1,{_ass_time(0)},{_ass_time(end)},Headline,,0,0,0,,{headline.strip().replace(chr(10), ' ')}")
    path.write_text(header + "\n" + "\n".join(events) + "\n", encoding="utf-8")
    return path


#: Title colours for the cover image, as ASS ``&HAABBGGRR``.
COVER_STYLES: dict[str, str] = {
    "yellow": "&H0040E0FF",
    "white": "&H00FFFFFF",
    "red": "&H003030FF",
}


def write_cover_ass(title: str, path: Path, *, width: int, height: int,
                    subtitle: Optional[str] = None, style: str = "yellow") -> Path:
    """An ASS file for a single cover frame: the title in large bold text
    (~110 px on a 1920-high frame) sitting on the bottom band, wrapped by
    libass to the margins, and the optional subtitle smaller and white
    underneath. Shown for the first second so one rendered frame carries it."""
    colour = COVER_STYLES.get(style or "yellow", COVER_STYLES["yellow"])
    title_size = max(48, round(height * 0.057))
    sub_size = max(28, round(height * 0.029))
    margin_x = round(width * 0.055)
    sub_margin = round(height * 0.083)
    # The title sits above the subtitle when there is one, otherwise lower.
    title_margin = round(height * 0.156) if subtitle and subtitle.strip() else round(height * 0.1)
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
        f"Style: Cover,Arial,{title_size},{colour},&H000000FF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{max(4, title_size // 18)},2,2,{margin_x},{margin_x},{title_margin},1",
        f"Style: CoverSub,Arial,{sub_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{max(2, sub_size // 18)},1,2,{margin_x},{margin_x},{sub_margin},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    clean = lambda t: re.sub(r"\s+", " ", t).strip()  # noqa: E731
    events = [f"Dialogue: 0,0:00:00.00,0:00:01.00,Cover,,0,0,0,,{clean(title)}"]
    if subtitle and subtitle.strip():
        events.append(f"Dialogue: 0,0:00:00.00,0:00:01.00,CoverSub,,0,0,0,,{clean(subtitle)}")
    path.write_text(header + "\n" + "\n".join(events) + "\n", encoding="utf-8")
    return path
