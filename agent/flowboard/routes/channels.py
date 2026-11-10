"""Channels ("Kênh"): the pages the seller posts to.

  GET    /api/channels/options         platforms + business categories for the form
  GET    /api/channels                 all channels, with post / clip counts
  POST   /api/channels                 create
  GET    /api/channels/{id}            one channel + counts + ``brainstorm_due``
  PATCH  /api/channels/{id}            edit fields (not the brainstorm)
  DELETE /api/channels/{id}            delete; posts / clips keep existing, unlinked
  POST   /api/channels/{id}/brainstorm read the channel's posts + clips → direction profile
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Board, Channel, Node, Post
from flowboard.services import channel_page, facebook_publish
from flowboard.services import channels as svc

router = APIRouter(prefix="/api/channels", tags=["channels"])


class ChannelBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    platforms: Optional[list[str]] = Field(default=None, max_length=8)
    category: Optional[str] = Field(default=None, max_length=32)  # legacy single value
    categories: Optional[list[str]] = Field(default=None, max_length=12)
    description: Optional[str] = Field(default=None, max_length=2000)
    audience: Optional[str] = Field(default=None, max_length=400)
    goal: Optional[str] = Field(default=None, max_length=400)
    link: Optional[str] = Field(default=None, max_length=500)


def _clean(body: ChannelBody) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    if "platforms" in data and data["platforms"] is not None:
        data["platforms"] = [p for p in data["platforms"] if p in svc.PLATFORMS]
    # Categories: the list wins; a lone legacy ``category`` becomes a one-item list.
    if data.get("categories") is not None:
        seen: list[str] = []
        for k in data["categories"]:
            if k in svc.CATEGORIES and k not in seen:
                seen.append(k)
        data["categories"] = seen[: svc.MAX_CATEGORIES]
        data["category"] = data["categories"][0] if data["categories"] else ""
    elif "category" in data:
        if data["category"] not in svc.CATEGORIES:
            data["category"] = "other" if data["category"] else ""
        data["categories"] = [data["category"]] if data["category"] else []
    for key in ("name", "description", "audience", "goal", "link"):
        if isinstance(data.get(key), str):
            data[key] = data[key].strip()
    if data.get("link"):
        data["link"] = channel_page.normalize_link(data["link"])
        if not channel_page.link_allowed(data["link"]):
            raise HTTPException(400, "Link kênh phải là Facebook, TikTok, Instagram, YouTube, Threads hoặc Zalo (https://…)")
    return data


def _counts(channel_ids: list[int]) -> tuple[dict[int, int], dict[int, int]]:
    """posts and clips per channel. Clips sit in ``board.data.quicktool.channel_id``
    (JSON), so boards are read once and counted here."""
    posts: dict[int, int] = {}
    clips: dict[int, int] = {}
    if not channel_ids:
        return posts, clips
    with get_session() as s:
        for cid, n in s.exec(select(Post.channel_id, func.count()).where(Post.channel_id.in_(channel_ids)).group_by(Post.channel_id)).all():
            posts[int(cid)] = int(n)
        for data in s.exec(select(Board.data)).all():
            cid = ((data or {}).get("quicktool") or {}).get("channel_id")
            if cid in channel_ids:
                clips[cid] = clips.get(cid, 0) + 1
    return posts, clips


def _row(c: Channel, posts: int = 0, clips: int = 0) -> dict[str, Any]:
    row = {
        "id": c.id, "name": c.name, "platforms": list(c.platforms or []), "category": c.category,
        "categories": svc.category_keys({"categories": c.categories, "category": c.category}),
        "description": c.description, "audience": c.audience, "goal": c.goal,
        "link": c.link or "", "page_review": dict(c.page_review) if c.page_review else None,
        "fb_page_id": c.fb_page_id or "", "fb_page_name": c.fb_page_name or "",
        "fb_connected": bool(c.fb_page_id and facebook_publish.has_token(c.id)),
        "brainstorm": dict(c.brainstorm) if c.brainstorm else None,
        "posts": posts, "clips": clips,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }
    row["brainstorm_due"] = svc.brainstorm_due(row, posts)
    return row


def get_channel(channel_id: Optional[int]) -> Optional[dict[str, Any]]:
    """The channel as a dict for prompts (None when missing)."""
    if not channel_id:
        return None
    with get_session() as s:
        c = s.get(Channel, channel_id)
        return _row(c) if c else None


def _material(channel_id: int) -> tuple[list[dict], list[dict]]:
    with get_session() as s:
        posts = s.exec(select(Post).where(Post.channel_id == channel_id).order_by(Post.id.desc())
                       .limit(svc.MAX_POSTS_IN_PROMPT)).all()
        post_rows = [{"kind": p.kind, "body": p.body, "hashtags": p.hashtags} for p in posts]
        boards = [b for b in s.exec(select(Board).order_by(Board.id.desc())).all()
                  if ((b.data or {}).get("quicktool") or {}).get("channel_id") == channel_id][:svc.MAX_CLIPS_IN_PROMPT]
        clip_rows = []
        for b in boards:
            videos = s.exec(select(Node).where(Node.board_id == b.id, Node.type == "video").order_by(Node.id)).all()
            clip_rows.append({"name": b.name, "lines": [str((v.data or {}).get("narration") or "").strip() for v in videos]})
    return post_rows, clip_rows


@router.get("/options")
def options() -> dict[str, Any]:
    return {
        "platforms": [{"key": k, "label": v[0]} for k, v in svc.PLATFORMS.items()],
        "categories": [{"key": k, "label": v} for k, v in svc.CATEGORIES.items()],
        "brainstorm_min_posts": svc.BRAINSTORM_MIN_POSTS,
        "max_categories": svc.MAX_CATEGORIES,
    }


@router.get("")
def list_channels() -> list[dict]:
    with get_session() as s:
        rows = s.exec(select(Channel).order_by(Channel.id.desc())).all()
    posts, clips = _counts([c.id for c in rows])
    return [_row(c, posts.get(c.id, 0), clips.get(c.id, 0)) for c in rows]


@router.post("", status_code=201)
def create_channel(body: ChannelBody) -> dict:
    data = _clean(body)
    if not data.get("name"):
        raise HTTPException(400, "Kênh cần có tên")
    with get_session() as s:
        c = Channel(**{k: v for k, v in data.items() if v is not None})
        s.add(c)
        s.commit()
        s.refresh(c)
        return _row(c)


@router.get("/{channel_id}")
def read_channel(channel_id: int) -> dict:
    with get_session() as s:
        c = s.get(Channel, channel_id)
        if c is None:
            raise HTTPException(404, "channel not found")
    posts, clips = _counts([channel_id])
    return _row(c, posts.get(channel_id, 0), clips.get(channel_id, 0))


@router.patch("/{channel_id}")
def update_channel(channel_id: int, body: ChannelBody) -> dict:
    data = _clean(body)
    if "name" in data and not data["name"]:
        raise HTTPException(400, "Kênh cần có tên")
    with get_session() as s:
        c = s.get(Channel, channel_id)
        if c is None:
            raise HTTPException(404, "channel not found")
        if "link" in data and (data["link"] or "") != (c.link or ""):
            c.page_review = None  # a review of another page no longer applies
        for k, v in data.items():
            if v is not None:
                setattr(c, k, v)
        c.updated_at = datetime.now(timezone.utc)
        s.add(c)
        s.commit()
        s.refresh(c)
    posts, clips = _counts([channel_id])
    return _row(c, posts.get(channel_id, 0), clips.get(channel_id, 0))


@router.delete("/{channel_id}")
def delete_channel(channel_id: int) -> dict:
    with get_session() as s:
        c = s.get(Channel, channel_id)
        if c is None:
            raise HTTPException(404, "channel not found")
        s.delete(c)
        facebook_publish.set_token(channel_id, None)
        for p in s.exec(select(Post).where(Post.channel_id == channel_id)).all():
            p.channel_id = None
            s.add(p)
        # Clips point at the channel inside their JSON; unlink them too.
        for b in s.exec(select(Board)).all():
            qt = (b.data or {}).get("quicktool") or {}
            if qt.get("channel_id") == channel_id:
                b.data = {**b.data, "quicktool": {**qt, "channel_id": None}}
                s.add(b)
        s.commit()
    return {"ok": True}


@router.post("/{channel_id}/brainstorm")
async def brainstorm_channel(channel_id: int) -> dict:
    channel = get_channel(channel_id)
    if channel is None:
        raise HTTPException(404, "channel not found")
    posts, clips = _material(channel_id)
    try:
        profile = await svc.brainstorm(channel, posts, clips)
    except svc.ChannelError as exc:
        raise HTTPException(502 if "LLM" in str(exc) else 400, f"Chưa brainstorm được: {exc}")
    with get_session() as s:
        c = s.get(Channel, channel_id)
        if c is None:
            raise HTTPException(404, "channel not found")
        c.brainstorm = profile
        c.updated_at = datetime.now(timezone.utc)
        s.add(c)
        s.commit()
        s.refresh(c)
    return _row(c, len(posts), len(clips))


@router.post("/{channel_id}/review")
async def review_channel_page(channel_id: int) -> dict:
    """Open the channel's link (through the extension), let the LLM review the
    page, keep the review on the channel. 400 when there is no link / the page
    can't be read, 502 when the LLM fails."""
    channel = get_channel(channel_id)
    if channel is None:
        raise HTTPException(404, "channel not found")
    if not channel.get("link"):
        raise HTTPException(400, "Kênh chưa có link — thêm link ở ✎ Sửa")
    try:
        page = await channel_page.read_page(channel["link"])
        review = await channel_page.review(channel, page)
    except channel_page.ChannelPageError as exc:
        raise HTTPException(502 if str(exc).startswith("AI") else 400, str(exc))
    with get_session() as s:
        c = s.get(Channel, channel_id)
        if c is None:
            raise HTTPException(404, "channel not found")
        c.page_review = review
        c.updated_at = datetime.now(timezone.utc)
        s.add(c)
        s.commit()
        s.refresh(c)
    posts, clips = _counts([channel_id])
    return _row(c, posts.get(channel_id, 0), clips.get(channel_id, 0))


# ── Facebook Page connection (auto-posting) ────────────────────────────────

class FacebookTokenBody(BaseModel):
    token: str = Field(min_length=20, max_length=1000)
    page_id: Optional[str] = Field(default=None, max_length=64)


@router.post("/facebook/inspect")
async def inspect_facebook_token(body: FacebookTokenBody) -> dict:
    """What a pasted token can post to: the pages it manages (a user token)
    or its own page (a page token). Nothing is stored."""
    try:
        info = await facebook_publish.inspect_token(body.token)
    except facebook_publish.FacebookError as exc:
        raise HTTPException(400, str(exc))
    # Page tokens are secrets: the browser only needs to know which pages exist.
    return {**info, "pages": [{"id": p["id"], "name": p["name"]} for p in info["pages"]]}


@router.post("/{channel_id}/facebook")
async def connect_facebook_page(channel_id: int, body: FacebookTokenBody) -> dict:
    """Connect the channel to a Facebook Page: with a user token ``page_id``
    picks one of its pages (that page's own token is kept); with a page
    token the page is the token's. The token goes to the central store."""
    with get_session() as s:
        if s.get(Channel, channel_id) is None:
            raise HTTPException(404, "channel not found")
    try:
        info = await facebook_publish.inspect_token(body.token)
    except facebook_publish.FacebookError as exc:
        raise HTTPException(400, str(exc))
    pages = info["pages"]
    page = next((p for p in pages if body.page_id and p["id"] == body.page_id), None) if body.page_id else (pages[0] if len(pages) == 1 else None)
    if page is None:
        if len(pages) > 1 and not body.page_id:
            raise HTTPException(400, "Token quản lý nhiều Page — chọn Page muốn kết nối.")
        raise HTTPException(400, "Không thấy Page này trong token.")
    facebook_publish.set_token(channel_id, page["access_token"])
    with get_session() as s:
        c = s.get(Channel, channel_id)
        if c is None:
            raise HTTPException(404, "channel not found")
        c.fb_page_id, c.fb_page_name = page["id"], page["name"]
        c.updated_at = datetime.now(timezone.utc)
        s.add(c)
        s.commit()
    return get_channel(channel_id) or {}


@router.delete("/{channel_id}/facebook")
def disconnect_facebook_page(channel_id: int) -> dict:
    facebook_publish.set_token(channel_id, None)
    with get_session() as s:
        c = s.get(Channel, channel_id)
        if c is None:
            raise HTTPException(404, "channel not found")
        c.fb_page_id, c.fb_page_name = "", ""
        c.updated_at = datetime.now(timezone.utc)
        s.add(c)
        s.commit()
    return get_channel(channel_id) or {}
