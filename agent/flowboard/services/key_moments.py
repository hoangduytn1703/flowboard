"""The key moments of a spoken video — the words a viewer must not miss (a
price, a number, a benefit, a turn), one about every 12 s — picked by the AI
from the timed lines. Shared by "✂️ Edit auto CapCut" (``capcut_auto``: a key
word in CapCut, a zoom keyframe, a sound) and the dubbing tool (``dub``:
burned-in key word, zoompan, sound effect — "✨ Nhấn chữ quan trọng").

A ``Line`` is a spoken line with its time; word times come from Whisper when
heard, else are spread over the line by word length.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from flowboard.services.llm import run_llm

SECONDS_PER_POINT = 12.0  # about one key moment every 12 s (≈ 4–5 a minute)
MIN_POINT_GAP_S = 5.0
MAX_POINTS = 40
EMPHASIS_S = 1.2          # how long the key word stays on screen
ZOOM_LEVELS = (1.12, 1.18)
ZOOM_RISE_S, ZOOM_HOLD_S, ZOOM_FALL_S = 0.3, 1.0, 0.4
SFX_VOLUME = 0.3
LLM_TIMEOUT_S = 120.0


class KeyMomentsError(ValueError):
    pass


@dataclass
class Line:
    start: float
    end: float
    text: str
    words: list[tuple[float, float, str]] = field(default_factory=list)  # Whisper's, when heard
    anchor: Optional[tuple[float, float]] = None                          # CapCut (x, y) of a dub line's subtitle


def split_words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def timed_words(line: Line) -> list[tuple[float, float, str]]:
    """Each word with its time: Whisper's when it heard them (and they match the text), else spread by length."""
    if line.words and len(line.words) == len(split_words(line.text)):
        return line.words
    words = split_words(line.text)
    if not words:
        return []
    span = max(0.2, line.end - line.start)
    weights = [len(w) + 1 for w in words]
    total = sum(weights)
    out, t = [], line.start
    for w, k in zip(words, weights):
        d = span * k / total
        out.append((round(t, 3), round(t + d, 3), w))
        t += d
    return out


_POINTS_SYSTEM = """You edit short Vietnamese social videos (TikTok / Reels).
From the numbered subtitle lines (with their seconds), pick the KEY MOMENTS worth a highlight:
the key words appear big on screen, the picture zooms in quickly and a small sound effect plays.

Pick the words a viewer must not miss: numbers, prices, product names, a concrete benefit, a surprise,
a strong verb, a turning point. Never filler words, never greetings. At most ONE point per line;
points at least 5 seconds apart; spread them over the whole video; at most the number asked.

"words" = 1 to 3 words copied EXACTLY (same spelling and accents) from that line.

Return ONLY JSON, no prose: {"points": [{"line": <line number>, "words": "<exact words>"}]}"""


def point_budget(duration_s: float) -> int:
    return max(1, min(MAX_POINTS, int(duration_s / SECONDS_PER_POINT) or 1))


def _norm(s: str) -> str:
    return re.sub(r"[^\w\s]", "", s.lower(), flags=re.UNICODE).strip()


def time_of(line: Line, words: str) -> Optional[tuple[float, str]]:
    """When ``words`` are said in ``line`` (their first word's time) + the words as written in the line."""
    target = split_words(_norm(words))
    if not target:
        return None
    tw = timed_words(line)
    norm = [_norm(w[2]) for w in tw]
    for i in range(len(norm) - len(target) + 1):
        if norm[i:i + len(target)] == target:
            return tw[i][0], " ".join(w[2] for w in tw[i:i + len(target)])
    return None


def parse_points(text: str) -> list[dict]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise KeyMomentsError("AI không trả về JSON")
    data = json.loads(m.group(0))
    pts = data.get("points") if isinstance(data, dict) else None
    if not isinstance(pts, list):
        raise KeyMomentsError("AI trả về sai dạng")
    return [p for p in pts if isinstance(p, dict)]


def place_points(lines: list[Line], raw: list[dict], duration_s: float) -> list[dict[str, Any]]:
    """AI picks → ``[{at, words, line}]``: words found in their line, in time order, ≥ 5 s apart, within the budget."""
    found = []
    for p in raw:
        try:
            li = int(p.get("line")) - 1
        except (TypeError, ValueError):
            continue
        if not (0 <= li < len(lines)):
            continue
        hit = time_of(lines[li], str(p.get("words") or ""))
        if hit is None:
            continue
        at, words = hit
        found.append({"at": round(at, 3), "words": re.sub(r"[.,;:!?…]+$", "", words), "line": li})
    found.sort(key=lambda p: p["at"])
    out: list[dict[str, Any]] = []
    for p in found:
        if out and p["at"] - out[-1]["at"] < MIN_POINT_GAP_S:
            continue
        if p["at"] > duration_s - 0.5:
            continue
        out.append(p)
    return out[:point_budget(duration_s)]


def fallback_points(lines: list[Line], duration_s: float) -> list[dict[str, Any]]:
    """Without AI: numbers and exclamations, the way an editor would guess."""
    raw = []
    for i, line in enumerate(lines):
        words = split_words(line.text)
        for j, w in enumerate(words):
            if re.search(r"\d", w):
                raw.append({"line": i + 1, "words": " ".join(words[j:j + 2])})
                break
        else:
            if line.text.strip().endswith("!") and len(words) >= 2:
                raw.append({"line": i + 1, "words": " ".join(words[-2:])})
    return place_points(lines, raw, duration_s)


async def pick_points(lines: list[Line], duration_s: float) -> list[dict[str, Any]]:
    n = point_budget(duration_s)
    listing = "\n".join(f"[{i + 1}] ({l.start:.1f}s) {l.text}" for i, l in enumerate(lines) if l.text.strip())
    prompt = (f"Video length: {duration_s:.0f} seconds. Pick at most {n} key moments.\n\n"
              f"SUBTITLE LINES:\n{listing[:12000]}\n\nAnswer with the JSON now.")
    text = await run_llm("auto_prompt", prompt, system_prompt=_POINTS_SYSTEM, timeout=LLM_TIMEOUT_S)
    return place_points(lines, parse_points(text), duration_s)


def zoom_expr(points: list[dict[str, Any]], time_var: str = "in_time") -> str:
    """ffmpeg expression of the zoom factor over time: 1 + a bump at every point (rise, hold, fall),
    the levels alternating — for ``zoompan=z='…'``."""
    terms = []
    for i, p in enumerate(points):
        a = float(p["at"])
        lvl = ZOOM_LEVELS[i % len(ZOOM_LEVELS)]
        e = a + ZOOM_RISE_S + ZOOM_HOLD_S + ZOOM_FALL_S
        terms.append(f"{lvl - 1:.3f}*min(clip(({time_var}-{a:.3f})/{ZOOM_RISE_S},0,1),clip(({e:.3f}-{time_var})/{ZOOM_FALL_S},0,1))")
    return "1" if not terms else "1+" + "+".join(terms)


def zoom_at(points: list[dict[str, Any]], t: float) -> float:
    """The same curve evaluated in Python (previews, tests)."""
    z = 1.0
    for i, p in enumerate(points):
        a = float(p["at"])
        lvl = ZOOM_LEVELS[i % len(ZOOM_LEVELS)]
        e = a + ZOOM_RISE_S + ZOOM_HOLD_S + ZOOM_FALL_S
        z += (lvl - 1) * min(max(0.0, min(1.0, (t - a) / ZOOM_RISE_S)), max(0.0, min(1.0, (e - t) / ZOOM_FALL_S)))
    return z
