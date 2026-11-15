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
from typing import Callable, Optional

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

#: VieNeu-TTS v3 Turbo (pnnbao97, Apache-2.0) — what VieDub uses: 25 Vietnamese
#: voices of the three regions, free, run on this machine (ONNX, CPU) through
#: pyvideotrans' venv (``services/dub_runner.py vieneu``). Ids ``vieneu:<Name>``;
#: the names are the model's presets. Order: the featured ones first.
VIENEU_VOICES: dict[str, str] = {
    "vieneu:Ngọc Huyền": "Ngọc Huyền (nữ, Bắc, tự nhiên)",
    "vieneu:Hải Đăng": "Hải Đăng (nam, Bắc, tự nhiên)",
    "vieneu:Trúc Ly": "Trúc Ly (nữ, Bắc, tự nhiên)",
    "vieneu:Mai Anh": "Mai Anh (nữ, Bắc, tin tức)",
    "vieneu:Thiện Minh": "Thiện Minh (nam, Bắc, kể chuyện)",
    "vieneu:Thùy Dung": "Thùy Dung (nữ, Nam, tin tức)",
    "vieneu:Thiền Tâm Đức": "Thiền Tâm Đức (nam, Bắc, kể chuyện)",
    "vieneu:Quang Sơn": "Quang Sơn (nam, Trung, tự nhiên)",
    "vieneu:Ngọc Trân": "Ngọc Trân (nữ, Trung, tự nhiên)",
    "vieneu:Adam bựa": "Adam bựa (nam, Bắc, tự nhiên, tếu)",
    "vieneu:Minh Đức": "Minh Đức (nam, Bắc, tin tức)",
    "vieneu:Phạm Tuyên": "Phạm Tuyên (nam, Bắc, tự nhiên)",
    "vieneu:Thái Sơn": "Thái Sơn (nam, Nam, kể chuyện)",
    "vieneu:Xuân Vĩnh": "Xuân Vĩnh (nam, Bắc, tự nhiên)",
    "vieneu:Thanh Bình": "Thanh Bình (nam, Bắc, kể chuyện)",
    "vieneu:Ngọc Linh": "Ngọc Linh (nữ, Bắc, kể chuyện)",
    "vieneu:Đoan Trang": "Đoan Trang (nữ, Bắc, tự nhiên)",
    "vieneu:Thục Đoan": "Thục Đoan (nữ, Nam, kể chuyện)",
    "vieneu:Minh Triết": "Minh Triết (nam, Nam, tin tức)",
    "vieneu:Mỹ Duyên": "Mỹ Duyên (nữ, Nam, đọc truyện)",
    "vieneu:Quỳnh Anh": "Quỳnh Anh (nữ, Bắc, đọc truyện)",
    "vieneu:Đức Trí": "Đức Trí (nam, Nam, đọc truyện)",
    "vieneu:Kim Thanh": "Kim Thanh (nữ, Nam, đọc truyện)",
    "vieneu:Adam": "Adam (nam, Nam, tự nhiên)",
    "vieneu:Quốc Tuấn": "Quốc Tuấn (nam, Bắc, tự nhiên)",
}
VOICES.update({k: f"{v} · VieNeu" for k, v in VIENEU_VOICES.items()})

#: FPT.AI TTS v5 — the "review phim" voices (Ban Mai…); needs the seller's own
#: key (console.fpt.ai, 100 000 characters a month free), kept as
#: ``secrets.apiKeys.fpt``. Ids ``fpt:<code>``.
FPT_VOICES: dict[str, str] = {
    "fpt:banmai": "Ban Mai (nữ, Bắc, giọng review phim)",
    "fpt:leminh": "Lê Minh (nam, Bắc)",
    "fpt:thuminh": "Thu Minh (nữ, Bắc)",
    "fpt:myan": "Mỹ An (nữ, Trung)",
    "fpt:giahuy": "Gia Huy (nam, Trung)",
    "fpt:lannhi": "Lan Nhi (nữ, Nam)",
    "fpt:linhsan": "Linh San (nữ, Nam)",
}
VOICES.update({k: f"{v} · FPT.AI" for k, v in FPT_VOICES.items()})
FPT_URL = "https://api.fpt.ai/hmi/tts/v5"
#: FPT answers with a link first; the file appears a few seconds later.
FPT_POLL_TIMEOUT_S = 120.0


def is_gemini_voice(voice: str) -> bool:
    return voice.startswith("gemini:")


def voice_kind(voice: str) -> str:
    """``edge`` | ``gemini`` | ``vieneu`` | ``fpt`` (a cloned voice ``vieneu:clone:<uid>`` is a VieNeu voice)."""
    for kind in ("gemini", "vieneu", "fpt"):
        if voice.startswith(kind + ":"):
            return kind
    return "edge"


def is_voice(voice: object) -> bool:
    """A voice this tool can read with: a preset, or one of the account's cloned voices ("🧬 Giọng nhân bản")."""
    from flowboard.services import voice_clone

    if not isinstance(voice, str):
        return False
    return voice in VOICES or (voice_clone.is_clone(voice) and voice_clone.exists(voice))


def vieneu_available() -> tuple[bool, str]:
    """VieNeu runs in the dubbing runtime (VieDub's venv or the "gói lồng tiếng" add-on — both have ``vieneu``)."""
    from flowboard.services import dub_addon

    if dub_addon.runtime() is None:
        return False, "cần gói lồng tiếng — bấm “Cài gói lồng tiếng” ở trang 🎙 Lồng tiếng video"
    return True, ""


def fpt_available() -> tuple[bool, str]:
    from flowboard.services.llm import secrets

    return (True, "") if secrets.get_api_key("fpt") else (False, "chưa có key FPT.AI (Cài đặt → Gemini key → FPT.AI)")


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
    from flowboard.services import voice_clone
    from flowboard.services.llm import gemini_api

    vn_ok, vn_why = vieneu_available()
    fpt_ok, fpt_why = fpt_available()
    clones = voice_clone.list_clones()
    mine = [{"id": "clone", "label": "🧬 Giọng nhân bản của bạn — VieNeu, chạy trên máy", "available": vn_ok,
             "reason": vn_why, "voices": [{"id": c["voice"], "label": c["label"]} for c in clones]}] if clones else []
    return mine + [
        {"id": "edge", "label": "Microsoft Edge — miễn phí, nhanh", "available": True,
         "voices": [{"id": k, "label": v} for k, v in VOICES.items() if voice_kind(k) == "edge"]},
        {"id": "vieneu", "label": "VieNeu — miễn phí, chạy trên máy, 25 giọng Việt 3 miền (chậm hơn Edge)",
         "available": vn_ok, "reason": vn_why,
         "voices": [{"id": k, "label": v} for k, v in VIENEU_VOICES.items()]},
        {"id": "gemini", "label": "Gemini — nhiều giọng, chỉnh được phong cách (10 câu/ngày/key miễn phí)",
         "available": gemini_api.configured(), "reason": "" if gemini_api.configured() else "chưa có Gemini API key",
         "voices": [{"id": k, "label": v} for k, v in VOICES.items() if is_gemini_voice(k)]},
        {"id": "fpt", "label": "FPT.AI — giọng review phim, cần key (100k ký tự/tháng miễn phí)",
         "available": fpt_ok, "reason": fpt_why,
         "voices": [{"id": k, "label": v} for k, v in FPT_VOICES.items()]},
    ]

TTS_DIR = config.STORAGE_DIR / "media" / "tts"

#: Longest subtitle line, in characters, before the words wrap to a new cue.
SUBTITLE_MAX_CHARS = 34
#: Tries per line before giving up on the service.
#: Edge refuses 30–60 % of requests at times, at random (measured 28/10: same refusal rate with 0.5 s or growing
#: waits, 1 or 8 requests at once) — so retry quickly first, longer later
ATTEMPTS = 10


def edge_attempt_timeout(text: str) -> float:
    """How long one Edge call may take before it counts as hung: a normal line streams in 1–3 s."""
    return min(60.0, 20.0 + len(text) / 20)


class TTSError(RuntimeError):
    pass


class UnspeakableError(TTSError):
    """The voice ran fine but gave nothing for this text (VieNeu given Chinese, only symbols…): asking again will not
    help — a dub keeps that line silent instead of failing the whole video."""


#: cache keys of lines VieNeu gave no audio for (this run): asked again they fail at once, no 20 s model load
_UNSPEAKABLE: set[str] = set()


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


#: Gemini TTS now and then reads the prompt's instructions aloud ("Read the
#: transcript below… Director's notes… Giọng đọc tự nhiên") before the line —
#: seen 26/10 in a dub: a 6-word line came back 11.8 s long. A clip that long
#: for its words is that leak; it is re-spoken (the last try sends the bare
#: line, nothing it could read out).
GEMINI_ATTEMPTS = 3


def max_speech_seconds(text: str) -> float:
    """The longest a normal reading of ``text`` can take: Vietnamese words are
    syllables, read at 4–6 a second; this allows a slow 2.5/s plus a pause."""
    words = len(re.findall(r"\w+", text or ""))
    return words / 2.5 + 1.5


def gemini_leaked(text: str, duration: float) -> bool:
    """True when the audio is far too long for ``text`` (instructions read aloud)."""
    return duration > max_speech_seconds(text)


async def _synth_gemini(text: str, voice: str, rate: int, style: Optional[str], out: Path,
                        plain: bool = False) -> None:
    """Gemini TTS: the style instruction is spoken language, so the rate
    becomes a hint too. Writes a WAV (24 kHz PCM) to ``out``. ``plain`` sends
    the line alone (no notes) — the fallback when the notes were read aloud."""
    from flowboard.services.llm import gemini_api

    prompt = text.strip() if plain else gemini_tts_prompt(text, style, rate)
    try:
        wav = await gemini_api.speak(prompt, voice.split(":", 1)[1])
    except gemini_api.GeminiAPIError as exc:
        raise TTSError(f"Gemini TTS: {exc}") from exc
    out.write_bytes(wav)


async def _synth_vieneu_many(items: list[tuple[str, Path]], voice: str,
                             progress: Optional[Callable[[int, int], None]] = None,
                             stop: Optional[Callable[[], bool]] = None, run_lines: Optional[int] = None) -> None:
    """VieNeu for several lines with one model load: the resident server (services/voice_server, the model stays
    loaded between calls) or, when it is busy / off, a one-shot runner. ``items`` = ``[(text, out.wav)]``;
    ``progress(k, n)`` after each line (server only), ``stop()`` ends it between two lines."""
    import json as _json
    import tempfile

    from flowboard.services import dub  # the runner helper lives there (lazy: dub imports this module)
    from flowboard.services import voice_clone

    ok, why = vieneu_available()
    if not ok:
        raise TTSError(f"VieNeu: {why}")
    if voice_clone.is_clone(voice):
        try:
            name = "@" + str(voice_clone.voice_file(voice))  # a cloned voice: the runner reads its embedding file
        except voice_clone.CloneError as exc:
            raise TTSError(str(exc)) from exc
    elif voice in VIENEU_VOICES:
        name = voice.split(":", 1)[1]
    else:
        raise TTSError(f"VieNeu không có giọng {voice.split(':', 1)[1]!r}")
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    from flowboard.services import voice_server

    res: Optional[dict] = None
    if voice_server.enabled():
        try:
            res = await asyncio.to_thread(voice_server.speak, name, [{"text": t, "out": str(p)} for t, p in items],
                                          progress=progress, stop=stop, run_lines=run_lines)
        except voice_server.Stopped as exc:
            raise TTSError("Đã dừng theo yêu cầu") from exc
        except voice_server.Busy:
            res = None  # another dub / preview is being read: this one goes the old way, in parallel
        except voice_server.VoiceServerError as exc:
            logger.warning("tts: VieNeu server failed (%s) — reading with a one-shot runner", exc)
            res = None
    if res is None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="vieneu-", dir=str(TTS_DIR), delete=False, encoding="utf-8") as fh:
            _json.dump([{"text": t, "out": str(p)} for t, p in items], fh, ensure_ascii=False)
            lines_json = Path(fh.name)
        try:
            res = await asyncio.to_thread(dub._runner, "vieneu", name, str(lines_json), timeout=max(600, 30 * len(items)),
                                          stop=stop)
        except dub.DubError as exc:
            raise TTSError(f"VieNeu: {exc}") from exc
        finally:
            lines_json.unlink(missing_ok=True)
    unread = {int(n) - 1 for n in (res or {}).get("missing") or [] if str(n).isdigit()}
    for k, (text, p) in enumerate(items):
        if k in unread:
            _UNSPEAKABLE.add(p.stem)
            if len(items) == 1:
                raise UnspeakableError(f"VieNeu không đọc được câu “{text[:50]}”")
        elif not p.is_file() or p.stat().st_size < 200:
            raise TTSError("VieNeu không trả file giọng")


async def _synth_fpt(text: str, voice: str, out: Path) -> None:
    """FPT.AI TTS v5: POST the text, then fetch the file the answer points to."""
    import httpx

    from flowboard.services.llm import secrets

    key = secrets.get_api_key("fpt")
    if not key:
        raise TTSError("chưa có key FPT.AI — dán ở Cài đặt → Gemini key → FPT.AI")
    code = voice.split(":", 1)[1]
    body = text if len(text.strip()) >= 3 else text.strip() + " ..."  # FPT wants at least 3 characters
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(FPT_URL, content=body.encode("utf-8"),
                                  headers={"api-key": key, "voice": code, "speed": "", "format": "mp3"})
            try:
                j = r.json()
            except ValueError:
                j = {}
            if r.status_code in (401, 403) or str(j.get("error")) == "401":
                raise TTSError("key FPT.AI không đúng hoặc đã hết hạn")
            if r.status_code == 429:
                raise TTSError("FPT.AI báo gọi quá nhanh / hết hạn mức (429)")
            if r.status_code != 200 or j.get("error") not in (0, "0", None) or not j.get("async"):
                raise TTSError(f"FPT.AI trả lỗi: {j.get('message') or r.text[:200]}")
            deadline = asyncio.get_event_loop().time() + FPT_POLL_TIMEOUT_S
            while asyncio.get_event_loop().time() < deadline:
                g = await client.get(str(j["async"]))
                if g.status_code == 200 and len(g.content) > 512 and "text" not in g.headers.get("content-type", ""):
                    out.write_bytes(g.content)
                    return
                await asyncio.sleep(1.5)
    except httpx.HTTPError as exc:
        raise TTSError(f"không gọi được FPT.AI ({exc})") from exc
    raise TTSError(f"FPT.AI chưa trả file giọng sau {FPT_POLL_TIMEOUT_S:.0f} giây")


def _audio_name(voice: str, key: str) -> str:
    kind = voice_kind(voice)
    return f"{key}.wav" if kind in ("gemini", "vieneu") else f"{key}.mp3"


def _cached(text: str, voice: str, key: str) -> Optional[Narration]:
    audio = TTS_DIR / _audio_name(voice, key)
    meta = TTS_DIR / f"{key}.json"
    if not (audio.is_file() and meta.is_file()):
        return None
    try:
        saved = json.loads(meta.read_text(encoding="utf-8"))
        cached = Narration(audio, float(saved["duration"]), [Word(**w) for w in saved["words"]])
    except (OSError, ValueError, KeyError, TypeError):
        return None  # a damaged cache entry is simply regenerated
    if is_gemini_voice(voice) and gemini_leaked(text, cached.duration):
        logger.warning("tts: cached Gemini line %s is %.1fs for %d chars — instructions read aloud, re-speaking",
                       key, cached.duration, len(text))
        return None
    return cached


def _finish(audio: Path, key: str, words: Optional[list[Word]] = None) -> Narration:
    """Measure the file, write the sidecar, hand the narration back."""
    duration = _probe_duration(audio) or 0.0
    words = words or []
    narration = Narration(audio, duration, words)
    (TTS_DIR / f"{key}.json").write_text(json.dumps({"duration": duration, "words": [w.__dict__ for w in words]},
                                                     ensure_ascii=False), encoding="utf-8")
    return narration


async def synthesize_many(lines: list[str], voice: str = DEFAULT_VOICE, rate: int = 0,
                          style: Optional[str] = None, progress: Optional[Callable[[int, int], None]] = None,
                          stop: Optional[Callable[[], bool]] = None, run_lines: Optional[int] = None) -> list[Narration]:
    """Every line spoken, in order. Local voices (VieNeu) do all the uncached
    lines in one model load; the others go line by line. Lines are cached
    one by one, so a later :func:`synthesize` of any of them is a cache hit."""
    texts = [re.sub(r"\s+", " ", t or "").strip() for t in lines]
    if voice_kind(voice) == "vieneu":
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        todo: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for t in texts:
            key = _cache_key(t, voice, rate, "")
            if t and key not in seen and _cached(t, voice, key) is None:
                seen.add(key)
                todo.append((t, TTS_DIR / _audio_name(voice, key)))
        if todo:
            await _synth_vieneu_many(todo, voice, progress=progress, stop=stop, run_lines=run_lines)
            for t, p in todo:
                if p.is_file():  # a line VieNeu could not read has none: synthesize() below says which
                    _finish(p, _cache_key(t, voice, rate, ""))
    return [await synthesize(t, voice, rate, style) for t in texts]


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
    if not is_voice(voice):
        raise TTSError(f"unknown voice {voice!r}; choose one of {list(VOICES)}")
    gemini = is_gemini_voice(voice)
    kind = voice_kind(voice)
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(text, voice, rate, style or "" if gemini else "")
    mp3 = TTS_DIR / _audio_name(voice, key)
    meta = TTS_DIR / f"{key}.json"
    cached = _cached(text, voice, key)
    if cached is not None:
        return cached

    if kind == "vieneu":
        if key in _UNSPEAKABLE:
            raise UnspeakableError(f"VieNeu không đọc được câu “{text[:50]}”")
        # one line through the runner (a whole video goes through synthesize_many, one model load)
        await _synth_vieneu_many([(text, mp3)], voice)
        return _finish(mp3, key)
    if kind == "fpt":
        await _synth_fpt(text, voice, mp3)
        return _finish(mp3, key)

    if gemini:
        duration = 0.0
        for attempt in range(GEMINI_ATTEMPTS):
            plain = attempt == GEMINI_ATTEMPTS - 1
            await _synth_gemini(text, voice, rate, style, mp3, plain=plain)
            duration = _probe_duration(mp3) or 0.0
            if not gemini_leaked(text, duration):
                break
            logger.warning("tts: Gemini read more than the line (%.1fs for %r, try %d/%d)%s",
                           duration, text[:60], attempt + 1, GEMINI_ATTEMPTS,
                           "" if plain else " — retrying")
        else:
            raise TTSError(f"Gemini đọc thừa (đọc cả câu hướng dẫn) ở câu \"{text[:50]}\" sau {GEMINI_ATTEMPTS} lần — "
                           "thử lại hoặc đổi sang giọng Edge (Hoài My / Nam Minh)")
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
        async def read() -> None:
            communicate = edge_tts.Communicate(text, voice, rate=_rate_arg(rate), boundary="WordBoundary")
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 1e7
                    words.append(Word(start, start + chunk["duration"] / 1e7, chunk["text"]))

        try:
            # A dropped connection can leave the stream waiting forever (seen 29/10: 8 lines hung for good
            # at 71 % of a dub job) — each attempt gets a deadline and counts as a failed try past it.
            await asyncio.wait_for(read(), timeout=edge_attempt_timeout(text))
            if audio:
                break
            last_error = TTSError("edge-tts returned no audio")
        except asyncio.TimeoutError:
            last_error = TTSError(f"edge-tts không trả lời sau {edge_attempt_timeout(text):.0f} s")
        except Exception as exc:  # noqa: BLE001 — network / service errors, reported as one kind
            last_error = exc
        logger.info("tts: attempt %d/%d failed (%s); retrying", attempt + 1, ATTEMPTS, last_error)
        if attempt < ATTEMPTS - 1:
            await asyncio.sleep(0.5 if attempt < 4 else min(5.0, attempt - 2.0))  # ~21 s in all
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
    plan = [(speakers.get(tag) if tag and is_voice(speakers.get(tag)) else default_voice, seg)
            for tag, seg in segments]
    for voice, _ in plan:
        if not is_voice(voice):
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


#: the clip's subtitle looks on the ffmpeg path ("outline" = the original white text with a dark outline)
SUB_STYLES: dict[str, str] = {
    "outline": "Chữ trắng viền đen",
    "box_yellow": "Hộp vàng chữ đen",
    "box_white": "Hộp trắng chữ đen",
}


#: "Hiện chữ": "" the whole line at once, "grow" filling in word by word as it is said, "word" one word at a time
SUB_REVEALS = ("", "grow", "word")


def reveal_lines(start: float, end: float, line: str, reveal: str) -> list[tuple[float, float, str]]:
    """The ASS events of one subtitle line shown word by word: its slot shared out by word length. "grow" lays the
    whole line out with the words still to come invisible (nothing shifts as it fills in); "word" shows one word."""
    words = line.split()
    if reveal not in ("grow", "word") or len(words) < 2:
        return [(start, end, line)]
    total = sum(len(w) for w in words) or 1
    out: list[tuple[float, float, str]] = []
    t = start
    for i, w in enumerate(words):
        e = end if i == len(words) - 1 else t + (end - start) * len(w) / total
        if reveal == "word":
            body = w
        else:
            rest = " ".join(words[i + 1:])
            body = " ".join(words[:i + 1]) + (f"{{\\alpha&HFF&}} {rest}" if rest else "")
        if _ass_time(t) != _ass_time(e):
            out.append((t, e, body))
        t = e
    return out


def write_ass(cues: list[tuple[float, float, str]], path: Path, *, width: int, height: int,
              headline: Optional[str] = None, total_s: float = 0.0, style: str = "outline", reveal: str = "") -> Path:
    """An ASS file for libass: bold white text with a dark outline near the
    bottom of a 9:16 frame, sized relative to the video — or a yellow / white
    box behind dark text (``style``, :data:`SUB_STYLES`). ``headline`` (a
    drama beat's on-screen title) sits near the top for the whole clip."""
    font_size = max(28, round(height * 0.042))
    margin_v = round(height * 0.16)
    head_size = max(32, round(height * 0.05))
    if style in ("box_yellow", "box_white"):
        back = "&H0014D8FF" if style == "box_yellow" else "&H00F4F4F4"  # ASS = &HAABBGGRR
        # BorderStyle 3: an opaque box (OutlineColour) padded by Outline, dark bold text
        sub_line = (f"Style: Default,Arial,{font_size},&H00141414,&H000000FF,{back},{back},"
                    f"-1,0,0,0,100,100,0,0,3,{max(8, font_size // 4)},0,2,40,40,{margin_v},1")
    else:
        sub_line = (f"Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
                    f"-1,0,0,0,100,100,0,0,1,{max(2, font_size // 12)},1,2,40,40,{margin_v},1")
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
        sub_line,
        # Top-centre (alignment 8), warm yellow, heavier outline so it reads
        # over any still.
        f"Style: Headline,Arial,{head_size},&H0040E0FF,&H000000FF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{max(3, head_size // 10)},1,8,40,40,{round(height * 0.12)},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    events = [
        f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Default,,0,0,0,,{body}"
        for s, e, line in cues
        for a, b, body in reveal_lines(s, e, line.replace(chr(10), " "), reveal)
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
