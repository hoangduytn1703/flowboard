"""Proper names in a dubbed video's Vietnamese lines (7/11).

The free Google translation (the default since 30/10) gets names wrong in two ways, both seen on the
"thoát khỏi thiên hà" series: Whisper mishears a Chinese transliteration (安音斯坦 for 爱因斯坦) and Google
romanises the characters ("Anyinstein", "Losey" for 洛希极限, "Ultra Cloud" for 奥尔特云, "Billing Star"
for 比邻星), or leaves English where Vietnamese has its own name ("Mercury" for Sao Thủy). The Vietnamese
voice then reads them wrongly.

Three fixes:

* :func:`asr_hint` — the video's title (+ hashtags) becomes Whisper's ``hotwords``, so the names in it are
  heard right in the first place;
* :func:`check` — one Gemini pass per ~200 lines (the free key pool, no Claude quota) returns the lines whose
  names are wrong, corrected (``fixes``), and a glossary of the names a Vietnamese voice would misread
  (``names`` = ``[{write, say}]``, e.g. Einstein → "Anh xtanh");
* :func:`spoken` — the TTS reads ``say`` wherever the subtitle shows ``write`` (the subtitle keeps ``write``).
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: Lines per Gemini call, and calls at once.
BATCH_LINES = 200
PARALLEL = 3
MODEL = "gemini-3.5-flash"
MAX_NAMES = 80
#: A "fix" may replace at most this many of the line's words (or a third of a long line); more is a rewrite,
#: not a name fix, and is dropped.
MAX_WORDS_CHANGED = 3

_SYSTEM = (
    "You check the PROPER NAMES in the Vietnamese subtitles of a dubbed video. The source lines come from speech "
    "recognition, which mishears names (e.g. 安音斯坦 for 爱因斯坦 = Einstein, 洛西极限 for 洛希极限 = Roche limit), "
    "and the Vietnamese lines come from Google Translate, which then turns such names into nonsense romanisations "
    "('Anyinstein', 'Losey', 'Ultra Cloud', 'Billing Star') or leaves an English word where Vietnamese has its own "
    "name ('Mercury'). Use the video title and the whole context to work out the real name.\n"
    "Return:\n"
    "1. fixes: only the lines whose person / place / planet / star / organisation / brand / work / scientific term "
    "name is wrong or not the form Vietnamese viewers know. text = the whole Vietnamese line with ONLY that name "
    "corrected (and the few words around it if the garbled name broke the grammar) — everything else word for word. "
    "Vietnamese forms: planets and well-known bodies in Vietnamese (Sao Thủy, Sao Kim, Trái Đất, Sao Hỏa, Sao Mộc, "
    "Sao Thổ, Sao Thiên Vương, Sao Hải Vương, Mặt Trăng, Mặt Trời, Dải Ngân Hà); other foreign people, places, moons, "
    "stars and terms in their usual international Latin spelling as Vietnamese media writes them (Einstein, Newton, "
    "Titan, Triton, đám mây Oort, giới hạn Roche, Proxima Centauri); Chinese people and places in their usual "
    "Vietnamese form (Hán-Việt where that is what Vietnamese media uses, e.g. Tập Cận Bình, Bắc Kinh). Lines that "
    "are already right are NOT listed.\n"
    "2. names: every foreign-spelled name that will be in the corrected Vietnamese lines and that a Vietnamese "
    "text-to-speech voice would read wrongly, with say = how to read it in Vietnamese syllables separated by spaces, "
    "no hyphens (Einstein → Anh xtanh, Newton → Niu tơn, Roche → Rốt sơ, Oort → Ót, Proxima Centauri → Prốc xi ma "
    "Xen tau ri, Titan → Ti tan). Skip names that are already Vietnamese words.\n"
    "Output ONLY the JSON object."
)

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "fixes": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "line": {"type": "INTEGER"}, "text": {"type": "STRING"}}, "required": ["line", "text"]}},
        "names": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "write": {"type": "STRING"}, "say": {"type": "STRING"}}, "required": ["write", "say"]}},
    },
    "required": ["fixes", "names"],
}


class NamesError(RuntimeError):
    pass


def asr_hint(title: str, limit: int = 160) -> str:
    """Whisper ``hotwords`` from a downloaded title: its words and hashtags (names often sit in the hashtags),
    without the #/@ marks, duplicates or links."""
    text = re.sub(r"https?://\S+", " ", title or "")
    seen: list[str] = []
    for tok in re.split(r"[\s#@，,。.!！?？|/\\]+", text):
        tok = tok.strip(" -_:;\"'“”()[]")
        if tok and tok not in seen:
            seen.append(tok)
    return " ".join(seen)[:limit].strip()


def normalize_names(raw: Any) -> list[dict[str, str]]:
    """``[{write, say}]``: trimmed, no empty / duplicate ``write``, at most :data:`MAX_NAMES`."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        write = re.sub(r"\s+", " ", str(item.get("write") or "")).strip()[:60]
        say = re.sub(r"\s+", " ", str(item.get("say") or "").replace("-", " ")).strip()[:80]
        if not write or write.lower() in seen:
            continue
        seen.add(write.lower())
        out.append({"write": write, "say": say or write})
        if len(out) >= MAX_NAMES:
            break
    return out


def _pattern(word: str) -> re.Pattern:
    return re.compile(r"(?<![\w])" + re.escape(word) + r"(?![\w])")


def spoken(text: str, names: list[dict[str, str]]) -> str:
    """``text`` as the voice should read it: each glossary ``write`` replaced by its ``say`` (longest first)."""
    out = text or ""
    for n in sorted(names or [], key=lambda n: -len(n.get("write") or "")):
        write, say = n.get("write") or "", n.get("say") or ""
        if write and say and say != write:
            out = _pattern(write).sub(say, out)
    return out


def is_name_fix(old: str, new: str) -> bool:
    """``new`` keeps the words of ``old`` except a few (the name and the words around it)."""
    a, b = old.lower().split(), new.lower().split()
    kept = sum(m.size for m in difflib.SequenceMatcher(None, a, b).get_matching_blocks())
    return len(a) - kept <= max(MAX_WORDS_CHANGED, len(a) // 3)


def _parse(raw: Any, start: int, lines: list[str]) -> tuple[dict[int, str], list[dict[str, str]]]:
    if not isinstance(raw, dict):
        raise NamesError("answer is not an object")
    fixes: dict[int, str] = {}
    for f in raw.get("fixes") or []:
        try:
            i = int(f.get("line")) - 1
        except (TypeError, ValueError, AttributeError):
            continue
        text = re.sub(r"\s+", " ", str(f.get("text") or "")).strip()
        if not (start <= i < start + BATCH_LINES) or i >= len(lines) or not text or text == lines[i]:
            continue
        if not is_name_fix(lines[i], text):
            logger.info("dub_names: line %d rewritten too much, kept: %r → %r", i + 1, lines[i], text)
            continue
        fixes[i] = text
    return fixes, normalize_names(raw.get("names"))


async def check(src: list[str], lines: list[str], *, title: str = "", language: str = "",
                progress: Optional[Callable[[int, int], None]] = None) -> tuple[dict[int, str], list[dict[str, str]]]:
    """``(fixes {line index: corrected text}, names [{write, say}])`` for the Vietnamese ``lines`` translated
    from ``src``. Raises :class:`NamesError` when Gemini is not set up or every call failed."""
    from flowboard.services.llm import gemini_api

    if not gemini_api.configured():
        raise NamesError("chưa có Gemini API key (Cài đặt → Gemini key)")
    if len(src) != len(lines):
        raise NamesError("số câu không khớp")
    starts = list(range(0, len(lines), BATCH_LINES))
    sem = asyncio.Semaphore(PARALLEL)
    done = 0
    fixes: dict[int, str] = {}
    names: list[dict[str, str]] = []
    errors: list[str] = []

    async def one(start: int) -> None:
        nonlocal done
        rows = [f"{i + 1}. {src[i]} => {lines[i]}" for i in range(start, min(len(lines), start + BATCH_LINES))]
        prompt = (f"Video title: {title or '-'}\nSource language: {language or 'unknown'}\n"
                  f"LINES (number. source => Vietnamese), {len(rows)} of {len(lines)}:\n" + "\n".join(rows))
        async with sem:
            try:
                text = await gemini_api.generate_text(prompt, system=_SYSTEM, model=MODEL, response_schema=_SCHEMA,
                                                      timeout=180.0)
                f, n = _parse(gemini_api.parse_json(text), start, lines)
                fixes.update(f)
                names.extend(n)
            except (gemini_api.GeminiAPIError, NamesError, ValueError) as exc:
                logger.warning("dub_names: lines %d+ failed: %s", start + 1, exc)
                errors.append(str(exc)[:160])
        done += 1
        if progress:
            progress(done, len(starts))

    await asyncio.gather(*(one(s) for s in starts))
    if errors and len(errors) == len(starts):
        raise NamesError(errors[0])
    return fixes, normalize_names(names)
