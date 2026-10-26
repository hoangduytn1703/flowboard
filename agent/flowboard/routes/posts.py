"""Facebook posts ("Bài viết"): write with the LLM, keep a library.

  GET    /api/posts/options        post types / tones / lengths / calls to action for the form
  POST   /api/posts/write          {brief, product_id?, board_id?, current?, message?, history?} → {reply, post}
  POST   /api/posts/revise-image   {prompt, request} → {prompt}   an image prompt rewritten from a Vietnamese wish
  GET    /api/posts                saved posts, newest first (?board_id= filters)
  POST   /api/posts                save one
  PATCH  /api/posts/{id}           edit (text, hashtags, images…)
  DELETE /api/posts/{id}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Board, Node, Post
from flowboard.routes.channels import get_channel
from flowboard.services import hooks as hooks_svc
from flowboard.services import post_writer
from flowboard.services.products import get_product

router = APIRouter(prefix="/api/posts", tags=["posts"])


class ChatTurn(BaseModel):
    role: str = "user"
    text: str = Field(default="", max_length=2000)


class WriteBody(BaseModel):
    brief: dict[str, Any] = Field(default_factory=dict)
    product_id: Optional[int] = None
    board_id: Optional[int] = None
    channel_id: Optional[int] = None
    # A story told across posts: its name; the writer reads the earlier episodes.
    series: Optional[str] = Field(default=None, max_length=80)
    current: Optional[dict[str, Any]] = None
    message: Optional[str] = Field(default=None, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=30)


class HooksBody(BaseModel):
    body: str = Field(min_length=1, max_length=6000)
    channel_id: Optional[int] = None
    product_id: Optional[int] = None
    n: Optional[int] = Field(default=None, ge=2, le=hooks_svc.MAX_VARIANTS)


class ClipHooksBody(BaseModel):
    board_id: int
    n: Optional[int] = Field(default=None, ge=2, le=hooks_svc.MAX_VARIANTS)


@router.post("/hooks")
async def post_hooks(body: HooksBody) -> dict[str, Any]:
    """Opening-line variants for a post (A/B): ``{variants: [{style, label, line}]}``."""
    try:
        variants = await hooks_svc.post_hooks(
            body.body, channel=get_channel(body.channel_id), product=get_product(body.product_id) if body.product_id else None, n=body.n,
        )
    except post_writer.PostWriterError as exc:
        raise HTTPException(502 if "LLM" in str(exc) else 400, str(exc))
    return {"variants": variants}


@router.post("/clip-hooks")
async def clip_hooks(body: ClipHooksBody) -> dict[str, Any]:
    """Opening voice-line variants for scene 1 of a clip (A/B)."""
    clip, product_id, channel_id = _clip_context(body.board_id)
    if clip is None:
        raise HTTPException(404, "không có clip này")
    try:
        variants = await hooks_svc.clip_hooks(
            clip["lines"], clip_name=clip["name"], channel=get_channel(channel_id),
            product=get_product(product_id) if product_id else None, n=body.n,
        )
    except post_writer.PostWriterError as exc:
        raise HTTPException(502 if "LLM" in str(exc) else 400, str(exc))
    return {"variants": variants, "current": clip["lines"][0] if clip["lines"] else ""}


class PostBody(BaseModel):
    kind: Optional[str] = Field(default=None, max_length=32)
    title: Optional[str] = Field(default=None, max_length=120)
    body: Optional[str] = Field(default=None, max_length=8000)
    hashtags: Optional[str] = Field(default=None, max_length=600)
    first_comment: Optional[str] = Field(default=None, max_length=600)
    product_id: Optional[int] = None
    board_id: Optional[int] = None
    channel_id: Optional[int] = None
    series: Optional[str] = Field(default=None, max_length=80)
    episode: Optional[int] = Field(default=None, ge=0, le=9999)
    images: Optional[list[str]] = Field(default=None, max_length=8)
    image_prompts: Optional[list[str]] = Field(default=None, max_length=8)
    video: Optional[str] = Field(default=None, max_length=80)
    brief: Optional[dict[str, Any]] = None


def _row(p: Post) -> dict[str, Any]:
    return {
        "id": p.id, "kind": p.kind, "title": p.title, "body": p.body, "hashtags": p.hashtags,
        "first_comment": p.first_comment or "",
        "product_id": p.product_id, "board_id": p.board_id, "channel_id": p.channel_id, "series": p.series or "",
        "episode": p.episode or 0, "images": list(p.images or []), "video": p.video or "",
        "image_prompts": list(p.image_prompts or []), "brief": dict(p.brief or {}),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _clip_context(board_id: int) -> tuple[Optional[dict], Optional[int], Optional[int]]:
    """The clip's name + voice lines (scene order by node id), its product id and its channel id."""
    with get_session() as s:
        board = s.get(Board, board_id)
        if board is None:
            return None, None, None
        videos = s.exec(select(Node).where(Node.board_id == board_id, Node.type == "video").order_by(Node.id)).all()
        lines = [str((v.data or {}).get("narration") or "").strip() for v in videos]
        qt = (board.data or {}).get("quicktool") or {}
        pid, cid = qt.get("product_id"), qt.get("channel_id")
        return {"name": board.name, "lines": lines}, (int(pid) if pid else None), (int(cid) if cid else None)


def _series_context(name: Optional[str], channel_id: Optional[int]) -> Optional[dict[str, Any]]:
    """``{name, episode, previous}`` for the next episode of ``name``: earlier
    posts of that series (same channel when the post has one), oldest first."""
    name = (name or "").strip()
    if not name:
        return None
    with get_session() as s:
        q = select(Post).where(Post.series == name)
        if channel_id is not None:
            q = q.where((Post.channel_id == channel_id) | (Post.channel_id.is_(None)))  # type: ignore[union-attr]
        rows = s.exec(q.order_by(Post.episode, Post.id)).all()
        prev = [{"episode": p.episode or i + 1, "title": p.title, "body": p.body} for i, p in enumerate(rows)]
    return {"name": name, "episode": (max((p["episode"] for p in prev), default=0) + 1), "previous": prev}


@router.get("/series")
def list_series(channel_id: Optional[int] = Query(None)) -> list[dict[str, Any]]:
    """The story series so far: name, episodes, latest title — for the picker."""
    with get_session() as s:
        q = select(Post).where(Post.series != "")
        if channel_id is not None:
            q = q.where((Post.channel_id == channel_id) | (Post.channel_id.is_(None)))  # type: ignore[union-attr]
        rows = s.exec(q.order_by(Post.id.desc())).all()
    out: dict[str, dict[str, Any]] = {}
    for p in rows:
        row = out.setdefault(p.series, {"name": p.series, "episodes": 0, "last_episode": 0, "last_title": p.title, "channel_id": p.channel_id})
        row["episodes"] += 1
        row["last_episode"] = max(row["last_episode"], p.episode or 0)
    return list(out.values())


@router.get("/options")
def options() -> dict[str, Any]:
    return {
        "kinds": [{"key": k, "label": v[0]} for k, v in post_writer.POST_TYPES.items()],
        "tones": [{"key": k, "label": v} for k, v in post_writer.TONES.items()],
        "lengths": [{"key": "short", "label": "Ngắn"}, {"key": "medium", "label": "Vừa"}, {"key": "long", "label": "Dài"}],
        "ctas": [{"key": "none", "label": "Không kêu gọi — bài để đọc"}, {"key": "comment", "label": "Mời bình luận"},
                 {"key": "inbox", "label": "Mời inbox"}, {"key": "link", "label": "Link ở bình luận đầu"},
                 {"key": "share", "label": "Mời chia sẻ / tag bạn"}],
        "hooks": [{"key": k, "label": v[0]} for k, v in post_writer.HOOKS.items()],
        "formats": [{"key": k, "label": v[0]} for k, v in post_writer.FORMATS.items()],
        "boosts": [{"key": k, "label": v[0]} for k, v in post_writer.BOOSTS.items()],
        "emojis": [{"key": k, "label": v[0]} for k, v in post_writer.EMOJIS.items()],
        "max_images": post_writer.MAX_IMAGES,
    }


def _write_context(body: "WriteBody") -> tuple[Optional[dict], Optional[int], Optional[dict], dict]:
    """``(clip, product_id, product, channel)`` for a write; 400 without a channel."""
    clip, clip_product, clip_channel = (None, None, None)
    if body.board_id is not None:
        clip, clip_product, clip_channel = _clip_context(body.board_id)
    product_id = body.product_id or clip_product
    product = get_product(product_id) if product_id else None
    channel_id = body.channel_id or clip_channel
    if not channel_id:
        raise HTTPException(400, "Chọn kênh / page trước khi viết bài.")
    channel = get_channel(channel_id)
    if channel is None:
        raise HTTPException(400, "Kênh / page đã chọn không còn — chọn kênh khác.")
    return clip, product_id, product, channel


#: Batch: hooks rotated over the posts (when the seller left "AI tự chọn"), so they do not all open alike.
BATCH_HOOKS = ("question", "story", "number", "pain", "surprise")
MAX_BATCH = 5


class WriteBatchBody(WriteBody):
    n: int = Field(default=3, ge=1, le=MAX_BATCH)


def _save_written(post: dict[str, Any], *, brief: dict, product_id: Optional[int], channel_id: int,
                  board_id: Optional[int], series: str = "", episode: int = 0) -> dict[str, Any]:
    with get_session() as s:
        row = Post(kind=str(brief.get("kind") or ""), title=(post.get("title") or post["body"].split("\n")[0])[:120],
                   body=post["body"], hashtags=" ".join(post.get("hashtags") or []), first_comment=post.get("first_comment") or "",
                   product_id=product_id, board_id=board_id, channel_id=channel_id, series=series, episode=episode,
                   images=[], image_prompts=list(post.get("image_prompts") or []), brief=dict(brief))
        s.add(row)
        s.commit()
        s.refresh(row)
        return _row(row)


@router.post("/write-batch")
async def write_batch(body: WriteBatchBody) -> dict[str, Any]:
    """Up to :data:`MAX_BATCH` posts in one go, each saved (so each can be
    scheduled). With a story series they are consecutive episodes, written
    one after another so each reads the ones before it; otherwise they are
    written side by side, each with a different opening and angle."""
    clip, product_id, product, channel = _write_context(body)
    brief = dict(body.brief or {})
    name = (body.series or "").strip()
    posts: list[dict[str, Any]] = []
    errors: list[str] = []
    if name:
        brief["kind"] = "serial"
        ctx = _series_context(name, channel["id"]) or {"name": name, "episode": 1, "previous": []}
        for _ in range(body.n):
            try:
                post = await post_writer.write_post(brief, product=product, clip=clip, channel=channel, series=ctx)
            except post_writer.PostWriterError as exc:
                errors.append(f"Tập {ctx['episode']}: {exc}")
                break  # the next episode would not know what happened in this one
            posts.append(_save_written(post, brief=brief, product_id=product_id, channel_id=channel["id"],
                                       board_id=body.board_id, series=name, episode=ctx["episode"]))
            ctx = {**ctx, "episode": ctx["episode"] + 1,
                   "previous": [*ctx["previous"], {"episode": ctx["episode"], "title": post.get("title"), "body": post["body"]}]}
    else:
        import asyncio

        def brief_for(i: int) -> dict:
            b = dict(brief)
            if (b.get("hook") or "auto") == "auto":
                b["hook"] = BATCH_HOOKS[i % len(BATCH_HOOKS)]
            return b

        extra = lambda i: (f"BATCH: this is post {i + 1} of {body.n} written together for the same page. Each post in the batch "  # noqa: E731
                           "must stand alone and take a clearly different angle, opening and example from the others — "
                           "never reuse the same first sentence or the same structure.")
        briefs = [brief_for(i) for i in range(body.n)]
        results = await asyncio.gather(*(post_writer.write_post(briefs[i], product=product, clip=clip, channel=channel, extra=extra(i))
                                         for i in range(body.n)), return_exceptions=True)
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                errors.append(f"Bài {i + 1}: {res}")
                continue
            posts.append(_save_written(res, brief=briefs[i], product_id=product_id, channel_id=channel["id"], board_id=body.board_id))
    if not posts:
        raise HTTPException(502, "AI chưa viết được bài nào: " + "; ".join(errors))
    return {"posts": posts, "errors": errors, "series": name, "channel_id": channel["id"], "product_id": product_id}


@router.post("/write")
async def write(body: WriteBody) -> dict[str, Any]:
    # Every post is written for a page: without one the writer has no voice or
    # audience to follow and the tokens go on an off-topic post.
    clip, product_id, product, channel = _write_context(body)
    series = _series_context(body.series, channel["id"])
    try:
        post = await post_writer.write_post(
            body.brief, product=product, clip=clip, channel=channel, series=series, current=body.current,
            message=body.message, history=[t.model_dump() for t in body.history],
        )
    except post_writer.PostWriterError as exc:
        raise HTTPException(502, f"AI chưa viết được bài: {exc}")
    return {"reply": post.pop("reply"), "post": post, "product_id": product_id,
            "channel_id": channel["id"] if channel else None,
            "series": series["name"] if series else "", "episode": series["episode"] if series else 0}


class ReviseImageBody(BaseModel):
    prompt: str = Field(default="", max_length=2000)
    request: str = Field(min_length=1, max_length=500)


@router.post("/revise-image")
async def revise_image(body: ReviseImageBody) -> dict[str, str]:
    try:
        return {"prompt": await post_writer.revise_image_prompt(body.prompt, body.request)}
    except post_writer.PostWriterError as exc:
        raise HTTPException(502, str(exc))


@router.get("")
def list_posts(board_id: Optional[int] = Query(None), channel_id: Optional[int] = Query(None),
               limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    with get_session() as s:
        q = select(Post).order_by(Post.id.desc()).limit(limit)
        if board_id is not None:
            q = q.where(Post.board_id == board_id)
        if channel_id is not None:
            q = q.where(Post.channel_id == channel_id)
        return [_row(p) for p in s.exec(q).all()]


@router.post("", status_code=201)
def create_post(body: PostBody) -> dict:
    if not (body.body or "").strip():
        raise HTTPException(400, "Bài viết đang trống")
    with get_session() as s:
        p = Post(**{k: v for k, v in body.model_dump().items() if v is not None})
        s.add(p)
        s.commit()
        s.refresh(p)
        return _row(p)


@router.patch("/{post_id}")
def update_post(post_id: int, body: PostBody) -> dict:
    with get_session() as s:
        p = s.get(Post, post_id)
        if p is None:
            raise HTTPException(404, "post not found")
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(p, k, v)
        p.updated_at = datetime.now(timezone.utc)
        s.add(p)
        s.commit()
        s.refresh(p)
        return _row(p)


@router.delete("/{post_id}")
def delete_post(post_id: int) -> dict:
    with get_session() as s:
        p = s.get(Post, post_id)
        if p is None:
            raise HTTPException(404, "post not found")
        s.delete(p)
        s.commit()
    return {"ok": True}
