"""Opening-line variants ("5 câu mở đầu khác") for A/B testing a post or a
clip's first voice line.

The first line decides whether a post gets its "Xem thêm" tap and whether
a clip survives its first second, so the seller gets several hooks in
different styles (question, surprising fact, pain, number, story, contrarian
— :data:`post_writer.HOOKS`) and picks, or publishes two versions.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from flowboard.services.channels import channel_block
from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError
from flowboard.services.post_writer import HOOKS, PostWriterError, _product_block

MAX_VARIANTS = 8
DEFAULT_VARIANTS = 5
#: A clip's opening voice line fits one second-or-two of speech.
CLIP_HOOK_WORDS = 14

_STYLES = {k: v for k, v in HOOKS.items() if k != "auto"}

_SYSTEM_POST = (
    "You write opening lines (the first 1-2 lines, before the first blank line) for a Vietnamese social post. The seller "
    "will A/B test them. You get the CURRENT POST; keep its topic, facts and voice, do not add facts. Each variant must be a "
    "different STYLE from the list given, natural spoken Vietnamese (xưng 'mình'), no clickbait lies, no engagement bait "
    "('comment CÓ', 'tag 3 người'), at most 2 lines and 40 words, emoji at most one. "
    "Output ONLY a JSON object: {\"variants\": [{\"style\": str (the style key), \"line\": str}]} — no prose, no code fences."
)
_SYSTEM_CLIP = (
    "You write the opening spoken line of a short Vietnamese TikTok Shop video (the first scene's voice-over). The seller "
    "will A/B test them. You get the CURRENT SCRIPT (voice lines per scene) and the product; keep the facts, do not invent "
    f"claims, prices or discounts. Each variant must be a different STYLE from the list, natural spoken Vietnamese, at most "
    f"{CLIP_HOOK_WORDS} words (it must fit about two seconds), no hashtags, no emoji. "
    "Output ONLY a JSON object: {\"variants\": [{\"style\": str (the style key), \"line\": str}]} — no prose, no code fences."
)


def _styles_block(n: int) -> str:
    keys = list(_STYLES)[:n]
    return "STYLES (one variant each, in this order):\n" + "\n".join(f"- {k}: {_STYLES[k][1]}" for k in keys)


def _parse(text: str, n: int) -> list[dict[str, str]]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise PostWriterError("AI không trả về danh sách câu mở đầu.")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise PostWriterError(f"AI trả về JSON hỏng: {exc}") from exc
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for v in data.get("variants") or []:
        if not isinstance(v, dict):
            continue
        line = re.sub(r"\s+", " ", str(v.get("line") or "")).strip() if "\n" not in str(v.get("line") or "") else str(v.get("line")).strip()
        style = str(v.get("style") or "").strip()
        if not line or line.lower() in seen:
            continue
        seen.add(line.lower())
        out.append({"style": style if style in _STYLES else "auto", "label": _STYLES.get(style, ("Khác",))[0], "line": line[:300]})
        if len(out) >= n:
            break
    if not out:
        raise PostWriterError("AI không nghĩ ra câu mở đầu nào — thử lại.")
    return out


def _count(n: Optional[int]) -> int:
    try:
        return max(2, min(MAX_VARIANTS, int(n or DEFAULT_VARIANTS)))
    except (TypeError, ValueError):
        return DEFAULT_VARIANTS


async def post_hooks(body: str, *, channel: Optional[dict] = None, product: Optional[dict] = None,
                     n: Optional[int] = None, timeout: float = 90.0) -> list[dict[str, str]]:
    """Opening-line variants for a post body."""
    body = (body or "").strip()
    if len(body) < 20:
        raise PostWriterError("Bài chưa có nội dung để viết câu mở đầu.")
    n = _count(n)
    parts = [_styles_block(n)]
    if (chb := channel_block(channel)):
        parts.append(chb)
    if (pb := _product_block(product)):
        parts.append(pb)
    parts.append(f"CURRENT POST:\n{body[:3000]}")
    parts.append(f"Write {n} opening lines now.")
    try:
        text = await run_llm("auto_prompt", "\n\n".join(parts), system_prompt=_SYSTEM_POST, timeout=timeout)
    except LLMError as exc:
        raise PostWriterError(f"LLM failed: {exc}") from exc
    return _parse(text, n)


async def clip_hooks(lines: list[str], *, clip_name: str = "", channel: Optional[dict] = None,
                     product: Optional[dict] = None, n: Optional[int] = None, timeout: float = 90.0) -> list[dict[str, str]]:
    """Opening voice-line variants for a clip whose scene lines are ``lines``."""
    lines = [str(x or "").strip() for x in lines]
    if not any(lines):
        raise PostWriterError("Clip chưa có lời thoại — viết lời thoại ở Bước 2 trước.")
    n = _count(n)
    parts = [_styles_block(n)]
    if (chb := channel_block(channel)):
        parts.append(chb)
    if (pb := _product_block(product)):
        parts.append(pb)
    script = "\n".join(f"Scene {i + 1}: {l or '(no line)'}" for i, l in enumerate(lines))
    head = f'CURRENT SCRIPT of "{clip_name}"' if clip_name else "CURRENT SCRIPT"
    parts.append(f"{head}:\n{script[:3000]}")
    parts.append(f"Write {n} opening lines for scene 1 now.")
    try:
        text = await run_llm("auto_prompt", "\n\n".join(parts), system_prompt=_SYSTEM_CLIP, timeout=timeout)
    except LLMError as exc:
        raise PostWriterError(f"LLM failed: {exc}") from exc
    out = _parse(text, n)
    for v in out:  # a spoken hook must stay short
        words = v["line"].split()
        if len(words) > CLIP_HOOK_WORDS + 6:
            v["line"] = " ".join(words[:CLIP_HOOK_WORDS + 6])
    return out


def replace_opening(body: str, line: str) -> str:
    """``body`` with its opening (everything before the first blank line) replaced by ``line``."""
    body = (body or "").strip()
    line = (line or "").strip()
    if not body:
        return line
    parts = re.split(r"\n\s*\n", body, maxsplit=1)
    return line if len(parts) == 1 else f"{line}\n\n{parts[1].strip()}"
