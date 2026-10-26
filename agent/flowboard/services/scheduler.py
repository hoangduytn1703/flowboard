"""The posting calendar ("Lịch đăng"): slots for saved posts and finished
clips, reminders when they are due, and automatic publishing to a
channel's connected Facebook Page.

Times are stored in UTC; "golden hours" are computed in Vietnam time
(:data:`TZ`) per platform. A slot is *due* once its time has passed and
it is still ``planned``: the Today page lists it; if it is ``auto`` the
loop (:func:`run_loop`, started by the app) publishes it and records the
Facebook post id, or the error, in ``result``.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlmodel import select

from flowboard.db import get_session, has_engine
from flowboard.db.models import Board, Channel, Node, Post, Schedule
from flowboard.services import facebook_publish
from flowboard.timestamps import utc_iso

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
KINDS = ("post", "clip")
STATUSES = ("planned", "posted", "failed", "skipped")
#: How often the loop looks for due auto slots.
TICK_S = 60.0
#: A due auto slot older than this is not published any more (the agent was
#: off for a day: posting yesterday's "good morning" at 3 pm looks wrong).
AUTO_GRACE = timedelta(hours=2)

#: Platform → local hours that usually do well in Vietnam (sorted).
GOLDEN_HOURS: dict[str, tuple[time, ...]] = {
    "facebook": (time(7, 30), time(12, 0), time(20, 0)),
    "instagram": (time(11, 0), time(19, 30)),
    "tiktok": (time(12, 0), time(19, 0), time(21, 0)),
    "threads": (time(8, 0), time(21, 0)),
    "youtube": (time(19, 0),),
    "zalo": (time(9, 0), time(20, 0)),
}
DEFAULT_HOURS: tuple[time, ...] = (time(8, 0), time(12, 0), time(20, 0))


class ScheduleError(RuntimeError):
    pass


#: A slot may be set this far in the past ("Đăng ngay" creates one at "now").
PAST_GRACE = timedelta(minutes=2)


def check_future(when: datetime) -> None:
    if _aware(when) < _now() - PAST_GRACE:
        raise ScheduleError("Giờ đăng đã qua — chọn một giờ trong tương lai.")


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_when(value: str) -> datetime:
    """An ISO timestamp from the browser (``Z`` or offset; naive = Vietnam time) → aware UTC."""
    raw = (value or "").strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ScheduleError("Giờ đăng không hợp lệ.") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc)


def row(sc: Schedule, *, title: str = "", thumb: Optional[str] = None, channel: str = "",
        platforms: Optional[list[str]] = None, fb_connected: bool = False) -> dict[str, Any]:
    when = _aware(sc.scheduled_at)
    due = sc.status == "planned" and when is not None and when <= _now()
    return {
        "id": sc.id, "kind": sc.kind, "post_id": sc.post_id, "board_id": sc.board_id, "channel_id": sc.channel_id,
        "scheduled_at": utc_iso(when), "status": sc.status, "due": due, "auto": bool(sc.auto), "note": sc.note or "",
        "result": dict(sc.result) if sc.result else None, "posted_at": utc_iso(_aware(sc.posted_at)),
        "created_at": utc_iso(_aware(sc.created_at)),
        "title": title, "thumbnail": thumb, "channel": channel, "platforms": platforms or [],
        "fb_connected": fb_connected,
    }


def _decorate(items: list[Schedule]) -> list[dict[str, Any]]:
    """Rows with what the calendar card shows: the post's / clip's title and
    picture, the channel's name and whether it can auto-publish."""
    post_ids = {i.post_id for i in items if i.post_id}
    board_ids = {i.board_id for i in items if i.board_id}
    channel_ids = {i.channel_id for i in items if i.channel_id}
    posts: dict[int, Post] = {}
    boards: dict[int, Board] = {}
    thumbs: dict[int, str] = {}
    channels: dict[int, Channel] = {}
    with get_session() as s:
        if post_ids:
            posts = {p.id: p for p in s.exec(select(Post).where(Post.id.in_(post_ids))).all()}  # type: ignore[union-attr]
        if board_ids:
            boards = {b.id: b for b in s.exec(select(Board).where(Board.id.in_(board_ids))).all()}  # type: ignore[union-attr]
            for bid, t, d in s.exec(select(Node.board_id, Node.type, Node.data).where(Node.board_id.in_(board_ids))).all():  # type: ignore[union-attr]
                if bid not in thumbs and t in ("image", "visual_asset") and (d or {}).get("mediaId"):
                    thumbs[bid] = d["mediaId"]
        if channel_ids:
            channels = {c.id: c for c in s.exec(select(Channel).where(Channel.id.in_(channel_ids))).all()}  # type: ignore[union-attr]
    out = []
    for sc in items:
        title, thumb = "", None
        if sc.kind == "post" and sc.post_id in posts:
            p = posts[sc.post_id]
            title = p.title or p.body.split("\n")[0][:80]
            thumb = (p.images or [None])[0]
        elif sc.kind == "clip" and sc.board_id in boards:
            title = boards[sc.board_id].name
            thumb = thumbs.get(sc.board_id)
        else:
            title = "(đã xoá)"
        ch = channels.get(sc.channel_id) if sc.channel_id else None
        out.append(row(sc, title=title, thumb=thumb, channel=ch.name if ch else "",
                       platforms=list(ch.platforms or []) if ch else [],
                       fb_connected=bool(ch and ch.fb_page_id and facebook_publish.get_token(ch.id))))
    return out


def list_slots(start: Optional[datetime] = None, end: Optional[datetime] = None,
               channel_id: Optional[int] = None, status: Optional[str] = None) -> list[dict[str, Any]]:
    with get_session() as s:
        q = select(Schedule)
        if start is not None:
            q = q.where(Schedule.scheduled_at >= start)
        if end is not None:
            q = q.where(Schedule.scheduled_at < end)
        if channel_id is not None:
            q = q.where(Schedule.channel_id == channel_id)
        if status:
            q = q.where(Schedule.status == status)
        items = s.exec(q.order_by(Schedule.scheduled_at)).all()
    return _decorate(list(items))


def due_slots() -> list[dict[str, Any]]:
    """Planned slots whose time has passed (newest due first is not wanted: oldest first)."""
    with get_session() as s:
        items = s.exec(select(Schedule).where(Schedule.status == "planned", Schedule.scheduled_at <= _now())
                       .order_by(Schedule.scheduled_at)).all()
    return _decorate(list(items))


def _check_target(kind: str, post_id: Optional[int], board_id: Optional[int], channel_id: Optional[int]) -> int:
    """The channel the slot ends up on (the item's own when none given)."""
    if kind not in KINDS:
        raise ScheduleError("kind phải là post hoặc clip")
    with get_session() as s:
        if kind == "post":
            if not post_id or (p := s.get(Post, post_id)) is None:
                raise ScheduleError("Không thấy bài viết này.")
            channel_id = channel_id or p.channel_id
        else:
            if not board_id or (b := s.get(Board, board_id)) is None:
                raise ScheduleError("Không thấy clip này.")
            channel_id = channel_id or ((b.data or {}).get("quicktool") or {}).get("channel_id")
        if not channel_id or s.get(Channel, channel_id) is None:
            raise ScheduleError("Chọn kênh / page để lên lịch.")
    return int(channel_id)


def create(kind: str, when: datetime, *, post_id: Optional[int] = None, board_id: Optional[int] = None,
           channel_id: Optional[int] = None, auto: bool = False, note: str = "") -> dict[str, Any]:
    check_future(when)
    channel_id = _check_target(kind, post_id, board_id, channel_id)
    if auto and not can_auto(channel_id):
        raise ScheduleError("Kênh này chưa kết nối Facebook Page nên không tự đăng được — bỏ chọn \"Tự đăng\" hoặc kết nối Page trước.")
    with get_session() as s:
        sc = Schedule(kind=kind, post_id=post_id if kind == "post" else None, board_id=board_id if kind == "clip" else None,
                      channel_id=channel_id, scheduled_at=when, auto=auto, note=(note or "").strip()[:300])
        s.add(sc)
        s.commit()
        s.refresh(sc)
    return _decorate([sc])[0]


def update(slot_id: int, **fields: Any) -> dict[str, Any]:
    with get_session() as s:
        sc = s.get(Schedule, slot_id)
        if sc is None:
            raise ScheduleError("Không thấy lịch này.")
        if "scheduled_at" in fields and fields["scheduled_at"] is not None:
            if sc.status == "posted":
                raise ScheduleError("Bài này đã đăng rồi, không đổi giờ được.")
            check_future(fields["scheduled_at"])
            sc.scheduled_at = fields["scheduled_at"]
            if sc.status in ("failed", "skipped"):
                sc.status, sc.result = "planned", None  # moved: give it another go
        if "channel_id" in fields and fields["channel_id"]:
            if s.get(Channel, fields["channel_id"]) is None:
                raise ScheduleError("Không thấy kênh này.")
            sc.channel_id = int(fields["channel_id"])
        if "auto" in fields and fields["auto"] is not None:
            if fields["auto"] and not can_auto(sc.channel_id or 0):
                raise ScheduleError("Kênh này chưa kết nối Facebook Page nên không tự đăng được.")
            sc.auto = bool(fields["auto"])
        if "note" in fields and fields["note"] is not None:
            sc.note = str(fields["note"]).strip()[:300]
        if "status" in fields and fields["status"]:
            if fields["status"] not in STATUSES:
                raise ScheduleError("Trạng thái không hợp lệ.")
            sc.status = fields["status"]
            if fields["status"] == "posted":
                sc.posted_at = _now()
                sc.result = {**(sc.result or {}), "by": "manual"} if sc.result else {"by": "manual"}
            elif fields["status"] == "planned":
                sc.posted_at, sc.result = None, None
        sc.updated_at = _now()
        s.add(sc)
        s.commit()
        s.refresh(sc)
    return _decorate([sc])[0]


def delete(slot_id: int) -> bool:
    with get_session() as s:
        sc = s.get(Schedule, slot_id)
        if sc is None:
            return False
        s.delete(sc)
        s.commit()
        return True


def can_auto(channel_id: int) -> bool:
    if not channel_id:
        return False
    with get_session() as s:
        ch = s.get(Channel, channel_id)
    return bool(ch and ch.fb_page_id and facebook_publish.get_token(channel_id))


# ── golden hours ───────────────────────────────────────────────────────────

def golden_hours(platforms: list[str]) -> list[time]:
    hours: set[time] = set()
    for p in platforms or []:
        hours.update(GOLDEN_HOURS.get(p, ()))
    return sorted(hours or DEFAULT_HOURS)


def suggest_slots(channel_id: int, *, days: int = 7, limit: int = 6, start: Optional[datetime] = None) -> list[dict[str, Any]]:
    """The next free golden-hour slots of the channel (Vietnam time), skipping
    hours that already hold a slot. ``[{at, label}]`` with ``at`` in UTC."""
    with get_session() as s:
        ch = s.get(Channel, channel_id)
        if ch is None:
            raise ScheduleError("Không thấy kênh này.")
        platforms = list(ch.platforms or [])
        now = (start or _now())
        taken = {_aware(x.scheduled_at) for x in s.exec(
            select(Schedule).where(Schedule.channel_id == channel_id, Schedule.scheduled_at >= now,
                                   Schedule.status == "planned")).all()}
    hours = golden_hours(platforms)
    local_now = now.astimezone(TZ)
    out: list[dict[str, Any]] = []
    for d in range(days + 1):
        day = (local_now + timedelta(days=d)).date()
        for h in hours:
            at_local = datetime.combine(day, h, tzinfo=TZ)
            at = at_local.astimezone(timezone.utc)
            if at <= now + timedelta(minutes=10) or any(abs((at - t).total_seconds()) < 1800 for t in taken if t):
                continue
            weekday = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"][at_local.weekday()]
            out.append({"at": utc_iso(at), "label": f"{weekday} {at_local:%d/%m} · {at_local:%H:%M}"})
            if len(out) >= limit:
                return out
    return out


# ── publishing ─────────────────────────────────────────────────────────────

def _media_file(media_id: Optional[str]) -> Optional[Path]:
    if not media_id:
        return None
    from flowboard.services import media as media_service

    try:
        return media_service.cached_path(media_id)
    except Exception as exc:  # noqa: BLE001 — a missing picture must not hide the real error
        logger.warning("scheduler: media %s unavailable: %s", media_id, exc)
        return None


def _payload(sc: Schedule) -> tuple[str, list[Path], Optional[Path], str]:
    """``(message, photos, video, first_comment)`` for the slot's item."""
    from flowboard.routes.exports import _final_media
    from flowboard.services.post_writer import post_text_of

    with get_session() as s:
        if sc.kind == "post":
            p = s.get(Post, sc.post_id or 0)
            if p is None:
                raise ScheduleError("Bài viết của lịch này đã bị xoá.")
            if p.video:
                # A post with a video goes out as a video post (Facebook takes photos or one video).
                video = _media_file(p.video)
                if video is None:
                    raise ScheduleError("Không thấy file video của bài trên máy này (tạo lại video ở trang Bài viết).")
                return post_text_of(p.body, p.hashtags), [], video, p.first_comment or ""
            photos = [f for f in (_media_file(m) for m in (p.images or [])[:facebook_publish.MAX_PHOTOS]) if f]
            return post_text_of(p.body, p.hashtags), photos, None, p.first_comment or ""
        b = s.get(Board, sc.board_id or 0)
        if b is None:
            raise ScheduleError("Clip của lịch này đã bị xoá.")
        media_id = _final_media(b.id)
        if not media_id:
            raise ScheduleError("Clip chưa ghép xong — ghép ở Bước 5 trước khi đăng.")
        video = _media_file(media_id)
        if video is None:
            raise ScheduleError("Không thấy file clip đã ghép trên máy này (tải về từ cloud hoặc ghép lại).")
        # The clip's latest post is its caption; otherwise the clip's name.
        post = s.exec(select(Post).where(Post.board_id == b.id).order_by(Post.id.desc())).first()  # type: ignore[union-attr]
        if post is not None:
            return post_text_of(post.body, post.hashtags), [], video, post.first_comment or ""
        return b.name, [], video, ""


async def publish(slot_id: int) -> dict[str, Any]:
    """Publish one slot now through its channel's Facebook Page; the slot
    records the outcome either way."""
    with get_session() as s:
        sc = s.get(Schedule, slot_id)
        if sc is None:
            raise ScheduleError("Không thấy lịch này.")
        if sc.status == "posted":
            raise ScheduleError("Lịch này đã đăng rồi.")
        ch = s.get(Channel, sc.channel_id or 0)
        if ch is None:
            raise ScheduleError("Kênh của lịch này không còn.")
        page_id, channel_id = ch.fb_page_id, ch.id
    try:
        message, photos, video, first_comment = _payload(sc)
        out = await facebook_publish.publish_post(channel_id, page_id, message, photos=photos, video=video,
                                                  first_comment=first_comment)
        status, result = "posted", {"by": "facebook", **out}
    except (ScheduleError, facebook_publish.FacebookError) as exc:
        status, result = "failed", {"by": "facebook", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — recorded on the slot, never crashes the loop
        logger.exception("scheduler: publishing slot %s failed", slot_id)
        status, result = "failed", {"by": "facebook", "error": f"Lỗi khi đăng: {exc}"}
    with get_session() as s:
        sc = s.get(Schedule, slot_id)
        if sc is not None:
            sc.status, sc.result, sc.updated_at = status, result, _now()
            sc.posted_at = _now() if status == "posted" else None
            s.add(sc)
            s.commit()
            s.refresh(sc)
            return _decorate([sc])[0]
    raise ScheduleError("Không thấy lịch này.")


async def tick() -> int:
    """Publish every due auto slot (once). Returns how many were attempted."""
    if not has_engine():
        return 0
    now = _now()
    with get_session() as s:
        due = s.exec(select(Schedule).where(Schedule.status == "planned", Schedule.auto == True,  # noqa: E712
                                            Schedule.scheduled_at <= now).order_by(Schedule.scheduled_at)).all()
        ids = [(sc.id, _aware(sc.scheduled_at)) for sc in due]
    n = 0
    for slot_id, when in ids:
        if when is not None and now - when > AUTO_GRACE:
            with get_session() as s:
                sc = s.get(Schedule, slot_id)
                if sc is not None:
                    sc.status, sc.updated_at = "failed", now
                    sc.result = {"by": "facebook", "error": "Quá giờ hơn 2 tiếng khi agent không chạy — không tự đăng nữa. Đổi giờ để đăng lại hoặc đăng tay."}
                    s.add(sc)
                    s.commit()
            continue
        await publish(slot_id)
        n += 1
    return n


async def run_loop() -> None:
    """Background task: look for due auto slots every :data:`TICK_S`."""
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop must outlive one bad tick
            logger.warning("scheduler tick failed: %s", exc)
        await asyncio.sleep(TICK_S)
