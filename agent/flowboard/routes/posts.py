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

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Board, Node, Post, Schedule
from flowboard.routes.channels import get_channel
from flowboard.services import hooks as hooks_svc
from flowboard.services import fb_sync, post_writer
from flowboard.services.products import get_product
from flowboard.timestamps import utc_iso

router = APIRouter(prefix="/api/posts", tags=["posts"])
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="posts")


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


def _clip_videos(board_ids: set[int]) -> dict[int, str]:
    """board id → its finished (joined) clip's media id, one query for all."""
    if not board_ids:
        return {}
    out: dict[int, str] = {}
    with get_session() as s:
        rows = s.exec(select(Node.board_id, Node.id, Node.data)
                      .where(Node.board_id.in_(board_ids), Node.type.in_(["export", "merge"]))  # type: ignore[union-attr]
                      .order_by(Node.id)).all()
    for bid, _nid, data in rows:
        if isinstance(data, dict) and data.get("mediaId"):
            out[bid] = data["mediaId"]
    return out


def _post_schedules(posts: list[Post]) -> dict[int, dict[str, Any]]:
    """post id → where it stands on the calendar ("Lịch đăng"), so "Bài đã lưu"
    can show it is already taken care of. Its next planned slot (``due`` once
    the time has passed), else when it went out, else its last failed try;
    skipped slots do not count. A clip slot counts for the clip's newest post —
    the caption the clip goes out with (services/scheduler). Two queries for all."""
    from flowboard.services.scheduler import _aware, _now

    ids = {p.id for p in posts if p.id}
    boards = {p.board_id for p in posts if p.board_id}
    if not ids:
        return {}
    with get_session() as s:
        caption_of: dict[int, int] = {}
        if boards:
            for bid, pid in s.exec(select(Post.board_id, Post.id).where(Post.board_id.in_(boards))  # type: ignore[union-attr]
                                   .order_by(Post.id)).all():
                caption_of[bid] = pid  # the newest post wins
        cond = (Schedule.kind == "post") & Schedule.post_id.in_(ids)  # type: ignore[union-attr]
        if caption_of:
            cond = cond | ((Schedule.kind == "clip") & Schedule.board_id.in_(set(caption_of)))  # type: ignore[union-attr]
        slots = s.exec(select(Schedule).where(cond, Schedule.status.in_(["planned", "posted", "failed"]))).all()  # type: ignore[union-attr]
    by_post: dict[int, list[Schedule]] = {}
    for sc in slots:
        pid = sc.post_id if sc.kind == "post" else caption_of.get(sc.board_id or 0)
        if pid in ids:
            by_post.setdefault(pid, []).append(sc)
    now = _now()
    out: dict[int, dict[str, Any]] = {}
    for pid, items in by_post.items():
        planned = sorted((x for x in items if x.status == "planned"), key=lambda x: _aware(x.scheduled_at))
        posted = sorted((x for x in items if x.status == "posted"), key=lambda x: _aware(x.posted_at or x.scheduled_at))
        failed = sorted((x for x in items if x.status == "failed"), key=lambda x: _aware(x.scheduled_at))
        sc = planned[0] if planned else posted[-1] if posted else failed[-1]
        when = _aware(sc.posted_at if sc.status == "posted" and sc.posted_at else sc.scheduled_at)
        status = "due" if sc.status == "planned" and when <= now else sc.status
        out[pid] = {"slot_id": sc.id, "status": status, "at": utc_iso(when), "auto": bool(sc.auto),
                    "link": str((sc.result or {}).get("permalink") or ""), "planned": len(planned)}
    return out


def _row(p: Post, clip_video: Optional[str] = None, schedule: Any = ..., fb_manual: Any = ..., fb_stats: Any = ...) -> dict[str, Any]:
    """``clip_video``: the joined clip of ``p.board_id`` — what publishing sends
    when the post has no video of its own (services/scheduler). ``schedule``:
    its place on the calendar (:func:`_post_schedules`); ``fb_manual``: when
    its text went up by hand on a connected Page (services/fb_sync) — the
    editor shows it read-only. Both looked up when not given."""
    if clip_video is None and p.board_id:
        clip_video = _clip_videos({p.board_id}).get(p.board_id)
    if schedule is ...:
        schedule = _post_schedules([p]).get(p.id or 0)
    if fb_manual is ...:
        fb_manual = fb_sync.manual_for_posts({p.id}).get(p.id or 0) if p.id else None
    if fb_stats is ...:
        fb_stats = fb_sync.stats_for_posts({p.id}).get(p.id or 0) if p.id else None
    return {
        "clip_video": clip_video or "",
        "schedule": schedule,
        "fb_manual": fb_manual,
        # its numbers on Facebook (latest time it went up, by the tool or by hand)
        "fb_stats": fb_stats,
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
    # One entry per (series, channel): two pages may each run a story with the
    # same name, and the picker must not merge them (it filters by channel).
    out: dict[tuple[str, Optional[int]], dict[str, Any]] = {}
    for p in rows:
        row = out.setdefault((p.series, p.channel_id), {"name": p.series, "episodes": 0, "last_episode": 0, "last_title": p.title, "channel_id": p.channel_id})
        row["episodes"] += 1
        row["last_episode"] = max(row["last_episode"], p.episode or 0)
    return list(out.values())


@router.get("/options")
def options() -> dict[str, Any]:
    return {
        # A story series is its own yes/no now (any kind can run as one); "serial" stays only for old briefs.
        "kinds": [{"key": k, "label": v[0]} for k, v in post_writer.POST_TYPES.items() if k not in post_writer.LEGACY_KINDS],
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
        # the episodes keep the kind the seller picked (tips, review…); none → a plain story
        brief["kind"] = brief.get("kind") or "serial"
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
        rows = s.exec(q).all()
    ids = {p.id for p in rows if p.id}
    # four look-ups for the whole list (clip videos, schedule, posted by hand, numbers) — side by side: one after the
    # other was four more round trips to a cloud database (~500 ms measured for a short list)
    jobs = [_POOL.submit(_clip_videos, {p.board_id for p in rows if p.board_id}), _POOL.submit(_post_schedules, list(rows)),
            _POOL.submit(fb_sync.manual_for_posts, ids), _POOL.submit(fb_sync.stats_for_posts, ids)]
    videos, slots, by_hand, numbers = (j.result() for j in jobs)
    return [_row(p, videos.get(p.board_id) or "", slots.get(p.id or 0), by_hand.get(p.id or 0), numbers.get(p.id or 0)) for p in rows]


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
