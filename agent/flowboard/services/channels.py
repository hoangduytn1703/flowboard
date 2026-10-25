"""Channels ("Kênh"): the pages a seller posts to, and the brainstorm that
turns a channel's first posts into a direction for the next ones.

A channel is a few fields the seller fills in (platforms, business,
description, audience, goal). Once it has :data:`BRAINSTORM_MIN_POSTS`
posts, :func:`brainstorm` asks the LLM to read them (plus the channel's
clips) and write a profile — positioning, voice, content pillars, do /
don't, hashtags, next ideas. :func:`channel_block` renders channel +
profile for the post writer's prompt so later posts stay on purpose.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError

logger = logging.getLogger(__name__)

#: key → (label, how posts there should read)
PLATFORMS: dict[str, tuple[str, str]] = {
    "facebook": ("Facebook", "Facebook post: hook on line one, short paragraphs with blank lines, one question that invites comments, 3-6 hashtags at the end"),
    "instagram": ("Instagram", "Instagram caption: strong first line (the rest is hidden behind 'more'), line breaks, emoji as bullets, 8-15 hashtags in a block at the end"),
    "tiktok": ("TikTok", "TikTok caption: at most ~150 characters, punchy, 3-5 hashtags; the video does the talking"),
    "threads": ("Threads", "Threads post: conversational, under 500 characters, 0-3 hashtags, ends with something to reply to"),
    "youtube": ("YouTube", "YouTube description / community post: first two lines matter, plain sentences, 3-5 hashtags"),
    "zalo": ("Zalo", "Zalo OA post: friendly and direct, clear offer or info, hashtags optional"),
}
#: key → label. A page picks up to :data:`MAX_CATEGORIES` (Facebook allows
#: three), e.g. "Nhà sáng tạo nội dung số" + "Khoa học & công nghệ" + "Cửa hàng".
CATEGORIES: dict[str, str] = {
    # what the page sells
    "fashion": "Thời trang",
    "cosmetics": "Mỹ phẩm & làm đẹp",
    "food": "Đồ ăn / uống",
    "grocery": "Tạp hoá & phụ kiện",
    "home": "Gia dụng & nhà cửa",
    "mom_baby": "Mẹ & bé",
    "health": "Sức khoẻ & thể thao",
    "tech": "Công nghệ & phụ kiện số",
    "pets": "Thú cưng",
    "shop": "Cửa hàng / bán lẻ online",
    "affiliate": "Review & săn deal (affiliate)",
    # what the page talks about
    "creator": "Nhà sáng tạo nội dung số",
    "science": "Khoa học & công nghệ",
    "education": "Giáo dục / kiến thức",
    "entertainment": "Giải trí / hài",
    "news": "Tin tức & sự kiện",
    "travel": "Du lịch & ẩm thực",
    "lifestyle": "Đời sống / cá nhân",
    "family": "Gia đình & nuôi dạy con",
    "finance": "Tài chính / kiếm tiền online",
    "community": "Cộng đồng / nhóm sở thích",
    "other": "Khác",
}
MAX_CATEGORIES = 3


def category_keys(channel: Optional[dict]) -> list[str]:
    """The page's categories, oldest shape (``category`` string) included."""
    keys = [k for k in (channel or {}).get("categories") or [] if k in CATEGORIES]
    legacy = (channel or {}).get("category")
    if not keys and legacy in CATEGORIES:
        keys = [legacy]
    return keys[:MAX_CATEGORIES]
BRAINSTORM_MIN_POSTS = 3
#: a profile is stale once this many posts were saved after it
BRAINSTORM_STALE_POSTS = 5
MAX_POSTS_IN_PROMPT = 12
MAX_CLIPS_IN_PROMPT = 8

_SYSTEM = (
    "You are a content strategist for a Vietnamese affiliate seller's social page. From the page's description and "
    "its first posts / clips, write a short, concrete direction the page should follow so future posts feel like "
    "one voice with one purpose. Use only what the material shows; do not invent products, numbers or claims.\n"
    "Output ONLY one JSON object with these keys (Vietnamese text, concise):\n"
    "- positioning: 1-2 sentences — what the page is for and for whom\n"
    "- audience: 1 sentence\n"
    "- voice: 1-2 sentences — tone, how it addresses readers (xưng hô), what it avoids\n"
    "- pillars: 3-5 items, each {name, note} — the recurring content themes\n"
    "- post_mix: 1-2 sentences — which post types / rhythm fit (hỏi ý kiến, review, mẹo, chốt đơn…)\n"
    "- do: 3-6 short rules\n"
    "- dont: 3-6 short rules\n"
    "- hashtags: 5-10 hashtags the page should reuse (strings starting with '#', no spaces)\n"
    "- ideas: 5 next post ideas, each one sentence\n"
    "- summary: 2-3 sentences the seller can read in ten seconds\n"
    "No prose outside the JSON, no code fences."
)


class ChannelError(RuntimeError):
    pass


def platform_labels(keys: list) -> list[str]:
    return [PLATFORMS[k][0] for k in keys or [] if k in PLATFORMS]


def platform_style(key: Optional[str]) -> str:
    return PLATFORMS.get(key or "", PLATFORMS["facebook"])[1]


def primary_platform(channel: Optional[dict]) -> str:
    plats = [p for p in (channel or {}).get("platforms") or [] if p in PLATFORMS]
    return plats[0] if plats else "facebook"


def brainstorm_due(channel: dict, post_count: int) -> bool:
    """A first brainstorm once there are enough posts; again when the
    profile is :data:`BRAINSTORM_STALE_POSTS` posts old."""
    if post_count < BRAINSTORM_MIN_POSTS:
        return False
    prof = channel.get("brainstorm") or {}
    if not prof:
        return True
    return post_count - int(prof.get("post_count") or 0) >= BRAINSTORM_STALE_POSTS


def channel_block(channel: Optional[dict]) -> str:
    """The channel and its direction, for a writer prompt."""
    if not channel:
        return ""
    lines = [f"CHANNEL / PAGE: {channel.get('name') or ''}"]
    plats = platform_labels(channel.get("platforms") or [])
    if plats:
        lines.append("Platforms: " + ", ".join(plats))
    cats = category_keys(channel)
    if cats:
        lines.append("Business / page categories: " + ", ".join(CATEGORIES[k] for k in cats))
    for key, label in (("description", "About the page"), ("audience", "Audience"), ("goal", "Goal of the posts")):
        if channel.get(key):
            lines.append(f"{label}: {str(channel[key])[:400]}")
    if channel.get("link"):
        lines.append(f"Page link: {channel['link']}")
    review = channel.get("page_review") or {}
    if review:
        lines.append("WHAT THE LIVE PAGE LOOKS LIKE (read from the page itself):")
        if review.get("summary"):
            lines.append(f"- {str(review['summary'])[:400]}")
        if review.get("house_style"):
            lines.append(f"- How its posts are written (match this): {str(review['house_style'])[:500]}")
        if review.get("sample_hooks"):
            lines.append("- Real opening lines: " + " | ".join(str(h)[:120] for h in review["sample_hooks"][:5]))
        if review.get("suggestions"):
            lines.append("- Improvements to apply: " + "; ".join(str(x)[:140] for x in review["suggestions"][:4]))
    prof = channel.get("brainstorm") or {}
    if prof:
        lines.append("PAGE DIRECTION (follow it unless the seller asks otherwise):")
        for key, label in (("positioning", "Positioning"), ("voice", "Voice"), ("post_mix", "Post mix")):
            if prof.get(key):
                lines.append(f"- {label}: {str(prof[key])[:300]}")
        pillars = [f"{p.get('name')}" + (f" ({p.get('note')})" if p.get("note") else "") for p in prof.get("pillars") or [] if isinstance(p, dict) and p.get("name")]
        if pillars:
            lines.append("- Content pillars: " + "; ".join(pillars[:5]))
        if prof.get("do"):
            lines.append("- Do: " + "; ".join(str(x) for x in prof["do"][:6]))
        if prof.get("dont"):
            lines.append("- Don't: " + "; ".join(str(x) for x in prof["dont"][:6]))
        if prof.get("hashtags"):
            lines.append("- House hashtags: " + " ".join(str(x) for x in prof["hashtags"][:10]))
    return "\n".join(lines)


def _material(channel: dict, posts: list[dict], clips: list[dict]) -> str:
    parts = [channel_block({**channel, "brainstorm": None})]
    if posts:
        shown = []
        for i, p in enumerate(posts[:MAX_POSTS_IN_PROMPT], 1):
            body = str(p.get("body") or "").strip()[:700]
            tags = str(p.get("hashtags") or "").strip()
            shown.append(f"[Post {i}] ({p.get('kind') or 'post'}) {body}" + (f"\nhashtags: {tags}" if tags else ""))
        parts.append("POSTS SO FAR:\n" + "\n\n".join(shown))
    if clips:
        shown = []
        for c in clips[:MAX_CLIPS_IN_PROMPT]:
            voice = " / ".join(v for v in c.get("lines") or [] if v)[:400]
            shown.append(f"- {c.get('name')}" + (f": {voice}" if voice else ""))
        parts.append("VIDEO CLIPS MADE FOR THIS PAGE (voice-over):\n" + "\n".join(shown))
    prev = channel.get("brainstorm") or {}
    if prev.get("summary"):
        parts.append(f"PREVIOUS DIRECTION (refresh it with the new posts; keep what still holds): {prev['summary']}")
    parts.append("Write the direction now.")
    return "\n\n".join(parts)


def _parse(text: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ChannelError("no JSON object in the answer")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise ChannelError(f"bad JSON: {exc}") from exc
    out: dict[str, Any] = {}
    for key in ("positioning", "audience", "voice", "post_mix", "summary"):
        out[key] = str(data.get(key) or "").strip()
    if not out["positioning"] and not out["summary"]:
        raise ChannelError("empty direction")
    pillars = []
    for p in data.get("pillars") or []:
        if isinstance(p, dict) and p.get("name"):
            pillars.append({"name": str(p["name"]).strip(), "note": str(p.get("note") or "").strip()})
        elif isinstance(p, str) and p.strip():
            pillars.append({"name": p.strip(), "note": ""})
    out["pillars"] = pillars[:6]
    for key in ("do", "dont", "ideas"):
        out[key] = [str(x).strip() for x in (data.get(key) or []) if str(x).strip()][:8]
    tags = data.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    seen: list[str] = []
    for t in tags:
        t = "#" + re.sub(r"[\s#]+", "", str(t))
        if len(t) > 1 and t not in seen:
            seen.append(t)
    out["hashtags"] = seen[:12]
    return out


async def brainstorm(channel: dict, posts: list[dict], clips: list[dict], *, timeout: float = 150.0) -> dict[str, Any]:
    """The channel's direction from its material. Raises :class:`ChannelError`."""
    if not posts and not clips and not (channel.get("description") or "").strip() and not channel.get("page_review"):
        raise ChannelError("Kênh chưa có bài viết, clip hay mô tả nào để brainstorm")
    try:
        text = await run_llm("auto_prompt", _material(channel, posts, clips), system_prompt=_SYSTEM, timeout=timeout)
    except LLMError as exc:
        raise ChannelError(f"LLM failed: {exc}") from exc
    profile = _parse(text)
    profile["at"] = datetime.now(timezone.utc).isoformat()
    profile["post_count"] = len(posts)
    profile["clip_count"] = len(clips)
    return profile
