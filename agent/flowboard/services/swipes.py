"""The swipe file ("🔥 Mẫu đang hot"): posts and videos that did well, kept
with the LLM's breakdown of *why* — hook, structure, emotional triggers,
format, call to action — and turned into the seller's own version for a
product on a channel.

Reading the source: a link to a Facebook / Threads / … post is read through
the Chrome extension (``channel_page.read_page``); a TikTok / Douyin /
YouTube / Reels link is downloaded (``video_fetch``) and watched by Gemini
(``reference_video.analyze``) for its transcript and shot list; plain text
pasted by the seller is used as is.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Optional
from urllib.parse import urlparse

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Asset, Edge, Node, Post, Swipe
from flowboard.services import post_writer
from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError
from flowboard.timestamps import utc_iso

logger = logging.getLogger(__name__)

VIDEO_HOSTS = ("tiktok.com", "douyin.com", "iesdouyin.com", "youtube.com", "youtu.be", "instagram.com/reel", "fb.watch")
POST_HOSTS = ("facebook.com", "fb.com", "threads.net", "threads.com", "instagram.com", "x.com", "twitter.com", "zalo.me")
MAX_VIDEO_S = 600
MAX_TEXT = 6000


class SwipeError(RuntimeError):
    pass


_SYSTEM = (
    "You analyse one social post or short video that performed well on Vietnamese social media, for a TikTok Shop / Shopee "
    "affiliate seller who wants to understand WHY it worked and reuse the mechanics (never copy the text). Answer in Vietnamese "
    "except the keys. Output ONLY a JSON object:\n"
    "{\"title\": str (<= 60 chars, what it is about), \"summary\": str (2-3 sentences), "
    "\"hook_type\": str (one of: question, surprise, pain, number, story, contrarian, visual, other), "
    "\"hook\": str (the opening line / first seconds, quoted or described), "
    "\"structure\": [str] (the beats in order, 3-7 items, each 'Bước n: …'), "
    "\"why_it_works\": [str] (3-5 concrete reasons), \"triggers\": [str] (emotions / motives it plays on, 2-5), "
    "\"format\": str (how it is laid out / shot: lists, dialogue, before-after, POV, voice-over…), "
    "\"cta\": str (how it asks for action, or 'không'), "
    "\"skeleton\": str (a reusable Vietnamese template of the same structure with [placeholders] for product / audience / numbers, "
    "6-12 lines), \"tags\": [str] (3-6 short Vietnamese tags: ngành, kiểu nội dung)} — no prose, no code fences."
)
_ADAPT_BLOCK = (
    "FOLLOW THE STRUCTURE OF THIS PROVEN POST (its mechanics, not its words — do not copy sentences, do not mention it):\n"
    "- Hook type: {hook_type} (original hook: {hook})\n- Beats: {structure}\n- Why it worked: {why}\n- Format: {format}\n- Call to action style: {cta}\n"
    "Template:\n{skeleton}"
)


def _platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for key in ("tiktok", "douyin", "iesdouyin", "youtube", "youtu.be", "instagram", "facebook", "fb.watch", "fb.com",
                "threads", "x.com", "twitter", "zalo"):
        if key in host:
            return {"iesdouyin": "douyin", "youtu.be": "youtube", "fb.watch": "facebook", "fb.com": "facebook",
                    "x.com": "x", "twitter": "x"}.get(key, key)
    return host or "text"


def is_video_link(url: str) -> bool:
    u = url.lower()
    return any(h in u for h in VIDEO_HOSTS) or ("facebook.com" in u and ("/reel" in u or "/videos/" in u))


def row(sw: Swipe) -> dict[str, Any]:
    return {"id": sw.id, "kind": sw.kind, "url": sw.url, "platform": sw.platform, "title": sw.title, "text": sw.text,
            "analysis": dict(sw.analysis) if sw.analysis else None, "tags": list(sw.tags or []), "uses": sw.uses,
            "created_at": utc_iso(sw.created_at)}


def list_swipes() -> list[dict[str, Any]]:
    with get_session() as s:
        return [row(x) for x in s.exec(select(Swipe).order_by(Swipe.id.desc())).all()]  # type: ignore[union-attr]


def get_swipe(swipe_id: int) -> Optional[dict[str, Any]]:
    with get_session() as s:
        sw = s.get(Swipe, swipe_id)
        return row(sw) if sw else None


def delete_swipe(swipe_id: int) -> bool:
    with get_session() as s:
        sw = s.get(Swipe, swipe_id)
        if sw is None:
            return False
        s.delete(sw)
        s.commit()
        return True


# ── reading the source ─────────────────────────────────────────────────────

async def _read_post_link(url: str) -> dict[str, Any]:
    from flowboard.services import channel_page

    try:
        page = await channel_page.read_page(url)
    except channel_page.ChannelPageError as exc:
        raise SwipeError(str(exc)) from exc
    text = channel_page.clean_text(str(page.get("text") or ""))
    if len(text) < 80:
        raise SwipeError("Trang mở được nhưng không thấy nội dung bài — dán thẳng nội dung bài vào ô văn bản.")
    return {"title": str(page.get("title") or "")[:120], "text": text[:MAX_TEXT]}


async def _read_video_link(url: str) -> dict[str, Any]:
    """Download the video, let Gemini watch it: transcript + shots as text."""
    from flowboard.routes.reference_video import _host_allowed
    from flowboard.services import media as media_service
    from flowboard.services import reference_video
    from flowboard.services.llm import gemini_api
    from flowboard.services.video_fetch import FetchError, fetch_video

    if not _host_allowed(url):
        raise SwipeError("Link video phải là TikTok, Douyin, YouTube, Instagram, Facebook hoặc X.")
    if not gemini_api.configured():
        raise SwipeError("Xem video cần Gemini API key — thêm trong Cài đặt → Gemini key.")
    media_id = uuid.uuid4().hex
    try:
        path, title = await asyncio.to_thread(fetch_video, url, media_id, media_service.MEDIA_CACHE_DIR, max_duration_s=MAX_VIDEO_S)
    except FetchError as exc:
        raise SwipeError(f"Không tải được video: {exc}") from exc
    mime = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}.get(path.suffix.lower(), "video/mp4")
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(path), mime=mime))
        s.commit()
    try:
        a = await reference_video.analyze(path, None)
    except reference_video.ReferenceVideoError as exc:
        raise SwipeError(f"Gemini không xem được video: {exc}") from exc
    lines = [f"Title: {title or ''}", f"Hook (first seconds): {a.get('hook') or ''}", f"Style: {a.get('style') or ''} · Tone: {a.get('tone') or ''}",
             f"Transcript (vi): {a.get('voice_transcript_vi') or a.get('script_vi') or ''}", "Shots:"]
    for i, sh in enumerate(a.get("shots") or [], 1):
        lines.append(f"  {i}. [{sh.get('start_s', '?')}-{sh.get('end_s', '?')}s] {sh.get('shot') or ''} — {sh.get('action') or ''}"
                     + (f" — text on screen: {sh.get('on_screen_text')}" if sh.get("on_screen_text") else ""))
    return {"title": (title or str(a.get("hook") or ""))[:120], "text": "\n".join(lines)[:MAX_TEXT], "media_id": media_id}


async def read_source(url: Optional[str], text: Optional[str]) -> dict[str, Any]:
    """``{kind, url, platform, title, text}`` from a link or pasted text."""
    from flowboard.services.video_fetch import extract_url

    url = (extract_url(url or "") or (url or "")).strip()
    text = (text or "").strip()
    if url:
        if is_video_link(url):
            src = await _read_video_link(url)
            return {"kind": "video", "url": url, "platform": _platform(url), **src}
        src = await _read_post_link(url)
        return {"kind": "post", "url": url, "platform": _platform(url), **src}
    if len(text) < 40:
        raise SwipeError("Dán link bài / video, hoặc dán nội dung bài (ít nhất vài câu).")
    return {"kind": "post", "url": "", "platform": "text", "title": text.split("\n")[0][:120], "text": text[:MAX_TEXT]}


# ── analysis ───────────────────────────────────────────────────────────────

def _parse(text: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise SwipeError("AI không trả về phân tích.")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise SwipeError(f"AI trả về JSON hỏng: {exc}") from exc
    lst = lambda k: [str(x).strip() for x in (data.get(k) or []) if str(x).strip()][:8]  # noqa: E731
    return {
        "title": str(data.get("title") or "").strip()[:80], "summary": str(data.get("summary") or "").strip()[:600],
        "hook_type": str(data.get("hook_type") or "other").strip(), "hook": str(data.get("hook") or "").strip()[:300],
        "structure": lst("structure"), "why_it_works": lst("why_it_works"), "triggers": lst("triggers"),
        "format": str(data.get("format") or "").strip()[:200], "cta": str(data.get("cta") or "").strip()[:200],
        "skeleton": str(data.get("skeleton") or "").strip()[:2000], "tags": [t[:30] for t in lst("tags")][:6],
    }


async def analyze(url: Optional[str], text: Optional[str], *, timeout: float = 150.0) -> dict[str, Any]:
    """Read the source, analyse it, keep it. Returns the saved row."""
    src = await read_source(url, text)
    prompt = (f"SOURCE: {src['kind']} on {src['platform']}" + (f" ({src['url']})" if src["url"] else "") + "\n"
              + (f"TITLE: {src['title']}\n" if src.get("title") else "") + f"CONTENT:\n{src['text']}")
    try:
        out = await run_llm("auto_prompt", prompt, system_prompt=_SYSTEM, timeout=timeout)
    except LLMError as exc:
        raise SwipeError(f"AI không phân tích được: {exc}") from exc
    analysis = _parse(out)
    if src.get("media_id"):
        analysis["media_id"] = src["media_id"]
    with get_session() as s:
        sw = Swipe(kind=src["kind"], url=src["url"], platform=src["platform"], title=analysis["title"] or src["title"],
                   text=src["text"], analysis=analysis, tags=analysis["tags"])
        s.add(sw)
        s.commit()
        s.refresh(sw)
        return row(sw)


# ── writing our own version ────────────────────────────────────────────────

def adapt_block(analysis: dict[str, Any]) -> str:
    return _ADAPT_BLOCK.format(
        hook_type=analysis.get("hook_type") or "other", hook=analysis.get("hook") or "", structure=" → ".join(analysis.get("structure") or []),
        why="; ".join(analysis.get("why_it_works") or []), format=analysis.get("format") or "", cta=analysis.get("cta") or "không",
        skeleton=analysis.get("skeleton") or "",
    )


def _bump(swipe_id: int) -> None:
    with get_session() as s:
        sw = s.get(Swipe, swipe_id)
        if sw is not None:
            sw.uses = (sw.uses or 0) + 1
            s.add(sw)
            s.commit()


async def adapt_post(swipe_id: int, *, channel: dict, product: Optional[dict], kind: str = "story",
                     wish: Optional[str] = None) -> dict[str, Any]:
    """A saved post for the channel written on the swipe's structure."""
    sw = get_swipe(swipe_id)
    if sw is None or not sw.get("analysis"):
        raise SwipeError("Không thấy mẫu này.")
    brief: dict[str, Any] = {"kind": kind, "cta": "link" if product and product.get("aff_link") else "none", "length": "medium",
                             "images": 0, "topic": (wish or "").strip() or None}
    try:
        post = await post_writer.write_post(brief, product=product, channel=channel, extra=adapt_block(sw["analysis"]))
    except post_writer.PostWriterError as exc:
        raise SwipeError(str(exc)) from exc
    with get_session() as s:
        row_ = Post(kind=kind, title=(post.get("title") or sw["title"])[:120], body=post["body"],
                    hashtags=" ".join(post.get("hashtags") or []), first_comment=post.get("first_comment") or "",
                    product_id=int(product["id"]) if product else None, channel_id=int(channel["id"]), images=[],
                    image_prompts=list(post.get("image_prompts") or []), brief={**brief, "swipe_id": swipe_id})
        s.add(row_)
        s.commit()
        s.refresh(row_)
        post_id = row_.id
    _bump(swipe_id)
    return {"post_id": post_id, "title": post.get("title") or sw["title"], "body": post["body"], "reply": post.get("reply") or ""}


def _scene_pairs(board_id: int) -> list[tuple[int, Optional[int]]]:
    """``(image node id, its video node id)`` per scene, in scene order."""
    with get_session() as s:
        nodes = s.exec(select(Node).where(Node.board_id == board_id).order_by(Node.id)).all()
        edges = s.exec(select(Edge).where(Edge.board_id == board_id)).all()
    videos = {n.id for n in nodes if n.type == "video"}
    next_video: dict[int, int] = {}
    for e in edges:
        if e.target_id in videos and e.source_id not in next_video:
            next_video[e.source_id] = e.target_id
    return [(n.id, next_video.get(n.id)) for n in nodes if n.type == "image"]


async def adapt_clip(swipe_id: int, *, channel_id: int, product: dict, template_id: Optional[str] = None,
                     wish: Optional[str] = None) -> dict[str, Any]:
    """A clip board for the product whose script follows the swipe's beats."""
    from fastapi import HTTPException

    from flowboard.routes.templates import FromTemplateBody, create_board_from_template
    from flowboard.services.script_tailor import TailorError, tailor_board

    sw = get_swipe(swipe_id)
    if sw is None or not sw.get("analysis"):
        raise SwipeError("Không thấy mẫu này.")
    tid = template_id or product.get("template_id") or "affiliate_reel"
    try:
        board = await create_board_from_template(FromTemplateBody(
            template_id=tid, name=f"{product['name']} — theo mẫu: {sw['title'][:40]}", inputs={},
            product_id=int(product["id"]), channel_id=channel_id, tailor=False,
        ))
    except HTTPException as exc:
        raise SwipeError(str(exc.detail))
    instructions = ("Follow the beats and hook type of this proven video/post, adapted to the product (do not copy its words):\n"
                    + adapt_block(sw["analysis"]) + (f"\nSeller's wish: {wish.strip()}" if wish and wish.strip() else ""))
    tailored = False
    try:
        await tailor_board(int(board["id"]), _scene_pairs(int(board["id"])), instructions=instructions[:3500])
        tailored = True
    except TailorError as exc:
        logger.warning("swipe: clip %s not tailored: %s", board["id"], exc)
    _bump(swipe_id)
    return {"board_id": board["id"], "name": board["name"], "template_id": tid, "tailored": tailored}
