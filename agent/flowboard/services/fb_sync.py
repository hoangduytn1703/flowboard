"""Read a connected Facebook Page's own posts back into Flowboard
("🔄 Đồng bộ từ Facebook" on "Lịch đăng").

- A post that went up **by hand** on Facebook (or from Meta Business Suite)
  shows on the calendar as "🌐 đăng tay", at the time it went out.
- A saved post (Bài đã lưu) whose text went up by hand is marked as posted
  there (read-only in the editor), and its planned slots on that page are
  skipped so the tool never publishes it a second time.
- What the tool published itself (a Schedule slot's ``result.post_id``: the
  feed post id, or the video id of a Reel / video) is recognised and never
  listed twice.

Graph API: ``GET /{page}/published_posts`` — the page's own posts, Reels
included (``added_video`` whose ``attachments.target.id`` is the reel's
video id) — with each post's ❤ / 💬 / ↗ and, with ``read_insights``, its
views (``post_media_view``; Meta dropped ``post_impressions*``); plus
``GET /{page}/video_reels`` for the Reels' plays, watch time and retention.
Two calls a page per sync. The Page token the channel was connected with has
``pages_read_engagement``, which the posts need. Synced every
:data:`SYNC_EVERY_S` by :func:`run_loop`, and when "Lịch đăng" / "Bài viết"
open (:func:`sync_all` with ``max_age``); the last :data:`WINDOW_DAYS` days.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Optional

import httpx
from sqlmodel import select

from flowboard.db import get_session, has_engine
from flowboard.db.models import AppSetting, Channel, FbPost, Post, Schedule
from flowboard.services import facebook_publish
from flowboard.services.post_writer import post_text_of
from flowboard.timestamps import utc_iso

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30
SYNC_EVERY_S = 30 * 60
#: Opening "Lịch đăng" / "Bài viết" syncs again only when the last sync is older than this.
STALE_S = 10 * 60
#: A saved post and a Facebook post are the same text from this similarity up
#: (hashtags, links and spacing ignored) — a pasted post with a word or two edited still matches.
MATCH_RATIO = 0.8
#: A saved post made after the Facebook post went up (e.g. "⧉ Bản sao" of it) is not its source.
MATCH_AFTER = timedelta(hours=1)
PAGE_LIMIT = 100
MAX_PAGES = 10
FIELDS = "id,created_time,message,permalink_url,status_type,full_picture,attachments{media_type,type,target{id},url}"
COUNTS = "reactions.summary(true).limit(0),comments.summary(true).limit(0),shares"
#: needs read_insights; without it the posts are read with their ❤ / 💬 / ↗ only
INSIGHTS = "insights.metric(post_media_view,post_total_media_view_unique,post_clicks)"
REEL_FIELDS = ("id,length,video_insights.metric(fb_reels_total_plays,fb_reels_replay_count,post_video_avg_time_watched,"
               "post_video_view_time,post_video_followers,post_video_retention_graph)")
STATE_KEY = "fb_sync:{}"

_LOCK = asyncio.Lock()


class SyncError(RuntimeError):
    """Said to the person in front of the screen."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _parse_time(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


# ── matching a Facebook post to a saved post ──────────────────────────────

_TAG_RE = re.compile(r"#[\wÀ-ỹ]+")
_URL_RE = re.compile(r"https?://\S+")


def norm_text(text: str) -> str:
    """The words of a post: hashtags, links, case and spacing do not count."""
    t = unicodedata.normalize("NFC", text or "").lower()
    t = _URL_RE.sub(" ", _TAG_RE.sub(" ", t))
    return re.sub(r"\s+", " ", t).strip()


def similarity(a: str, b: str) -> float:
    """0–1 for two normalised texts (only the first 1500 characters count)."""
    if not a or not b:
        return 0.0
    m = SequenceMatcher(None, a[:1500], b[:1500], autojunk=False)
    if m.real_quick_ratio() < MATCH_RATIO or m.quick_ratio() < MATCH_RATIO:
        return 0.0
    return m.ratio()


def best_match(message: str, went_up: datetime, candidates: list[tuple[int, str, datetime]],
               keep: Optional[int] = None) -> Optional[int]:
    """The saved post (id) a Facebook post carries, if any. ``candidates`` =
    ``(post id, normalised text, created_at)``; ``keep`` = the post it was
    matched to last time (wins a tie, so the link does not jump around);
    otherwise the oldest of equally good ones (the original, not a copy)."""
    text = norm_text(message)
    if len(text) < 20:
        return None  # a photo with "❤️" under it is nobody's post
    best: tuple[float, int, int] | None = None
    for pid, ctext, created in candidates:
        if created - MATCH_AFTER > went_up:
            continue
        score = similarity(text, ctext)
        if score < MATCH_RATIO:
            continue
        rank = (round(score, 3), 1 if pid == keep else 0, -pid)
        if best is None or rank > best:
            best = rank  # type: ignore[assignment]
    return -best[2] if best else None


# ── reading the page ──────────────────────────────────────────────────────

def _insights(raw: dict[str, Any], key: str) -> dict[str, Any]:
    """``{metric: value}`` of an expanded insights field (the lifetime figure when a metric has several periods)."""
    out: dict[str, Any] = {}
    for m in (raw.get(key) or {}).get("data") or []:
        vals = m.get("values") or []
        if vals and (m.get("name") not in out or m.get("period") == "lifetime"):
            out[m["name"]] = vals[0].get("value")
    return out


def _num(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _item(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    went_up = _parse_time(str(raw.get("created_time") or ""))
    if not raw.get("id") or went_up is None:
        return None
    att = ((raw.get("attachments") or {}).get("data") or [{}])[0] or {}
    url = str(att.get("url") or "")
    ins = _insights(raw, "insights")
    stats = {
        "reactions": _num(((raw.get("reactions") or {}).get("summary") or {}).get("total_count")),
        "comments": _num(((raw.get("comments") or {}).get("summary") or {}).get("total_count")),
        "shares": _num((raw.get("shares") or {}).get("count")),
    }
    if ins:
        stats.update(views=_num(ins.get("post_media_view")), viewers=_num(ins.get("post_total_media_view_unique")),
                     clicks=_num(ins.get("post_clicks")))
    return {
        "fb_id": str(raw["id"]), "created_time": went_up, "kind": str(raw.get("status_type") or ""),
        "message": str(raw.get("message") or ""), "permalink": str(raw.get("permalink_url") or url or ""),
        "picture": str(raw.get("full_picture") or ""), "media_id": str((att.get("target") or {}).get("id") or ""),
        "reel": "/reel/" in url, "stats": stats,
    }


async def _read_all(client: httpx.AsyncClient, path: str, **params: Any) -> list[dict[str, Any]]:
    """Every row of a Graph list (following ``paging.next``, at most :data:`MAX_PAGES` pages)."""
    rows: list[dict[str, Any]] = []
    data = await facebook_publish._get(client, path, **params)
    for _ in range(MAX_PAGES):
        rows.extend(data.get("data") or [])
        nxt = (data.get("paging") or {}).get("next")
        if not nxt:
            break
        resp = await client.get(nxt)
        if resp.status_code >= 400:
            raise facebook_publish.FacebookError(facebook_publish._error_message(resp))
        data = resp.json()
    return rows


def _reel_stats(raw: dict[str, Any]) -> dict[str, Any]:
    ins = _insights(raw, "video_insights")
    graph = ins.get("post_video_retention_graph")
    retention = [round(float(graph[k]), 4) for k in sorted(graph, key=lambda x: int(x))] if isinstance(graph, dict) and graph else []
    out = {"plays": _num(ins.get("fb_reels_total_plays")), "replays": _num(ins.get("fb_reels_replay_count")),
           "avg_watch_s": round(_num(ins.get("post_video_avg_time_watched")) / 1000, 1),
           "watch_time_s": round(_num(ins.get("post_video_view_time")) / 1000),
           "followers": _num(ins.get("post_video_followers")), "retention": retention}
    try:
        out["length_s"] = round(float(raw.get("length") or 0), 1)
    except (TypeError, ValueError):
        out["length_s"] = 0
    return out


async def fetch_page_posts(page_id: str, token: str, since: datetime) -> tuple[list[dict[str, Any]], Optional[str]]:
    """The page's own posts since ``since``, newest first, each with its numbers.
    Returns ``(posts, stats_problem)``: numbers that could not be read (no
    ``read_insights``…) are left out and said, the posts are still read."""
    problem: Optional[str] = None
    since_ts = int(since.timestamp())
    async with httpx.AsyncClient(timeout=facebook_publish.TIMEOUT_S) as client:
        try:
            rows = await _read_all(client, f"{page_id}/published_posts", fields=f"{FIELDS},{COUNTS},{INSIGHTS}",
                                   limit=PAGE_LIMIT, since=since_ts, access_token=token)
        except facebook_publish.FacebookError as exc:
            problem = f"Không đọc được lượt xem ({exc}) — cần quyền read_insights."
            rows = await _read_all(client, f"{page_id}/published_posts", fields=f"{FIELDS},{COUNTS}",
                                   limit=PAGE_LIMIT, since=since_ts, access_token=token)
        items = [x for x in (_item(r) for r in rows) if x]
        if any(it["reel"] for it in items):
            try:
                reels = {str(r["id"]): _reel_stats(r) for r in await _read_all(
                    client, f"{page_id}/video_reels", fields=REEL_FIELDS, limit=50, since=since_ts, access_token=token) if r.get("id")}
            except facebook_publish.FacebookError as exc:
                problem = problem or f"Không đọc được số liệu Reel ({exc})."
                reels = {}
            for it in items:
                if it["media_id"] in reels:
                    it["stats"].update(reels[it["media_id"]])
    return items, problem


# ── state shown in the UI ─────────────────────────────────────────────────

def _state(channel_id: int) -> dict[str, Any]:
    with get_session() as s:
        row = s.get(AppSetting, STATE_KEY.format(channel_id))
    try:
        return json.loads(row.value) if row else {}
    except ValueError:
        return {}


def _save_state(channel_id: int, state: dict[str, Any]) -> None:
    with get_session() as s:
        row = s.get(AppSetting, STATE_KEY.format(channel_id))
        if row is None:
            row = AppSetting(key=STATE_KEY.format(channel_id), value="")
        row.value, row.updated_at = json.dumps(state, ensure_ascii=False), _now()
        s.add(row)
        s.commit()


def connected_channels() -> list[Channel]:
    """Channels with a Facebook Page connected (page id + token)."""
    with get_session() as s:
        rows = s.exec(select(Channel).where(Channel.fb_page_id != None)).all()  # noqa: E711
    return [c for c in rows if c.fb_page_id and facebook_publish.get_token(c.id)]


def status() -> dict[str, Any]:
    """Per connected channel: when it was last synced and how it went."""
    items = []
    for ch in connected_channels():
        st = _state(ch.id)
        items.append({"channel_id": ch.id, "channel": ch.name, **{k: st.get(k) for k in ("at", "error", "manual", "fetched", "stats_error")}})
    return {"channels": items}


# ── one sync ──────────────────────────────────────────────────────────────

def _tool_published(s, channel_id: int) -> dict[str, Schedule]:
    """Facebook id → the slot the tool published it from (feed post id, or a Reel's / video's id)."""
    out: dict[str, Schedule] = {}
    for sc in s.exec(select(Schedule).where(Schedule.channel_id == channel_id, Schedule.status == "posted")).all():
        fid = str((sc.result or {}).get("post_id") or "")
        if fid:
            out[fid] = sc
    return out


async def sync_channel(channel_id: int) -> dict[str, Any]:
    """Read the page's posts of the last :data:`WINDOW_DAYS` days into ``FbPost`` and
    match them to saved posts. Returns what changed; the outcome is also kept for the UI."""
    with get_session() as s:
        ch = s.get(Channel, channel_id)
        if ch is None:
            raise SyncError("Không thấy kênh này.")
        page_id, name = ch.fb_page_id, ch.name
    token = facebook_publish.get_token(channel_id)
    if not page_id or not token:
        raise SyncError(f"Kênh \"{name}\" chưa kết nối Facebook Page.")
    since = _now() - timedelta(days=WINDOW_DAYS)
    try:
        items, stats_problem = await fetch_page_posts(page_id, token, since)
    except facebook_publish.FacebookError as exc:
        _save_state(channel_id, {**_state(channel_id), "at": utc_iso(_now()), "error": str(exc)})
        raise SyncError(f"Đọc bài của Page \"{name}\" không được: {exc}") from exc

    now = _now()
    added = manual = matched = skipped = 0
    with get_session() as s:
        tool = _tool_published(s, channel_id)
        existing = {r.fb_id: r for r in s.exec(select(FbPost).where(FbPost.channel_id == channel_id)).all()}
        posts = s.exec(select(Post).where((Post.channel_id == channel_id) | (Post.channel_id == None))).all()  # noqa: E711
        candidates = [(p.id, norm_text(post_text_of(p.body, p.hashtags)), _aware(p.created_at) or now)
                      for p in posts if p.id and (p.body or "").strip() and p.kind != "tiktok_caption"]
        seen: set[str] = set()
        newly_matched: dict[int, datetime] = {}
        for it in items:
            seen.add(it["fb_id"])
            row = existing.get(it["fb_id"])
            if row is None:
                row = FbPost(channel_id=channel_id, fb_id=it["fb_id"], created_time=it["created_time"])
                added += 1
            for k in ("media_id", "created_time", "kind", "reel", "message", "permalink", "picture"):
                setattr(row, k, it[k])
            # numbers that could not be read this time (no read_insights, Reels call failed) keep their last value
            row.stats = {**(row.stats or {}), **it["stats"], "at": utc_iso(now)}
            slot = tool.get(it["fb_id"]) or (tool.get(it["media_id"]) if it["media_id"] else None)
            if slot is not None:
                row.slot_id, row.post_id = slot.id, slot.post_id
            else:
                row.slot_id = None
                before = row.post_id
                row.post_id = best_match(it["message"], it["created_time"], candidates, keep=before)
                manual += 1
                if row.post_id:
                    matched += 1
                    if row.post_id != before:
                        newly_matched[row.post_id] = it["created_time"]
            row.synced_at = now
            s.add(row)
        # deleted on Facebook (inside the window we just read in full) → gone here too
        removed = 0
        for fid, row in existing.items():
            if fid not in seen and (_aware(row.created_time) or now) >= since:
                s.delete(row)
                removed += 1
        # a saved post that went up by hand must not be published again by a planned slot on that page
        for pid, went_up in newly_matched.items():
            for sc in s.exec(select(Schedule).where(Schedule.kind == "post", Schedule.post_id == pid,
                                                    Schedule.channel_id == channel_id, Schedule.status == "planned")).all():
                local = went_up.astimezone(timezone(timedelta(hours=7))).strftime("%H:%M %d/%m")
                sc.status, sc.updated_at = "skipped", now
                sc.note = (f"Bỏ qua: bài đã đăng tay trên Facebook lúc {local}, tool không đăng lại. " + (sc.note or ""))[:300]
                s.add(sc)
                skipped += 1
        s.commit()
    out = {"channel_id": channel_id, "channel": name, "at": utc_iso(now), "error": None, "fetched": len(items),
           "manual": manual, "matched": matched, "added": added, "removed": removed, "skipped_slots": skipped,
           "stats_error": stats_problem}
    _save_state(channel_id, out)
    logger.info("fb_sync: %s — %d posts, %d by hand (%d match a saved post), %d new, %d removed, %d slots skipped",
                name, len(items), manual, matched, added, removed, skipped)
    return out


async def sync_all(max_age: Optional[float] = None) -> dict[str, Any]:
    """Every connected page; with ``max_age`` (seconds) only the ones synced longer ago than that.
    One sync at a time — a second caller gets ``{"busy": true}``."""
    if _LOCK.locked():
        return {"busy": True, "channels": []}
    async with _LOCK:
        results = []
        for ch in connected_channels():
            if max_age is not None:
                last = _parse_iso(_state(ch.id).get("at"))
                if last is not None and (_now() - last).total_seconds() < max_age:
                    continue
            try:
                results.append(await sync_channel(ch.id))
            except SyncError as exc:
                results.append({"channel_id": ch.id, "channel": ch.name, "error": str(exc)})
        return {"busy": False, "channels": results}


def _parse_iso(value: Any) -> Optional[datetime]:
    try:
        return _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00"))) if value else None
    except ValueError:
        return None


async def run_loop() -> None:
    """Background task: sync every page every :data:`SYNC_EVERY_S` while an account is open."""
    while True:
        await asyncio.sleep(60)
        try:
            if has_engine():
                await sync_all(max_age=SYNC_EVERY_S)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop must outlive one bad sync
            logger.warning("fb_sync loop: %s", exc)


# ── what the pages show ───────────────────────────────────────────────────

def _row(r: FbPost, channels: dict[int, str], titles: dict[int, str]) -> dict[str, Any]:
    # a saved post deleted since the last sync is not "in Bài đã lưu" any more (the next sync drops the link)
    post_id = r.post_id if r.post_id in titles else None
    return {
        "id": r.id, "channel_id": r.channel_id, "channel": channels.get(r.channel_id, ""), "fb_id": r.fb_id,
        "at": utc_iso(_aware(r.created_time)), "kind": r.kind, "reel": r.reel,
        "title": (r.message or "").strip().split("\n")[0][:80] or ("Reel" if r.reel else "Bài không có chữ"),
        "message": r.message, "permalink": r.permalink, "picture": r.picture,
        "post_id": post_id, "post_title": titles.get(post_id or 0, ""), "stats": r.stats,
    }


def list_manual(start: datetime, end: datetime, channel_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Posts that went up by hand (not through the tool) in ``[start, end)``, oldest first."""
    with get_session() as s:
        q = select(FbPost).where(FbPost.slot_id == None, FbPost.created_time >= start, FbPost.created_time < end)  # noqa: E711
        if channel_id is not None:
            q = q.where(FbPost.channel_id == channel_id)
        rows = s.exec(q.order_by(FbPost.created_time)).all()
        channels = {c.id: c.name for c in s.exec(select(Channel)).all()}
        pids = {r.post_id for r in rows if r.post_id}
        titles = {}
        if pids:
            titles = {p.id: (p.title or p.body.split("\n")[0][:80]) for p in s.exec(select(Post).where(Post.id.in_(pids))).all()}  # type: ignore[union-attr]
    return [_row(r, channels, titles) for r in rows]


def manual_for_posts(post_ids: set[int]) -> dict[int, dict[str, Any]]:
    """Saved post id → the latest time it went up by hand on Facebook (Bài đã lưu shows it read-only)."""
    if not post_ids:
        return {}
    with get_session() as s:
        rows = s.exec(select(FbPost).where(FbPost.slot_id == None, FbPost.post_id.in_(post_ids))  # noqa: E711  # type: ignore[union-attr]
                      .order_by(FbPost.created_time)).all()
        channels = {c.id: c.name for c in s.exec(select(Channel)).all()}
    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        out[r.post_id] = {"at": utc_iso(_aware(r.created_time)), "link": r.permalink, "reel": r.reel,
                          "channel": channels.get(r.channel_id, ""), "fb_id": r.fb_id,
                          "count": (out.get(r.post_id) or {}).get("count", 0) + 1}
    return out


def stats_for_posts(post_ids: set[int]) -> dict[int, dict[str, Any]]:
    """Saved post id → the numbers of its latest time on Facebook (by the tool or by hand), with ``reel`` / ``link``."""
    if not post_ids:
        return {}
    with get_session() as s:
        rows = s.exec(select(FbPost).where(FbPost.post_id.in_(post_ids)).order_by(FbPost.created_time)).all()  # type: ignore[union-attr]
    return {r.post_id: {**(r.stats or {}), "reel": r.reel, "link": r.permalink, "posted_at": utc_iso(_aware(r.created_time))}
            for r in rows if r.stats}


def stats_for_slots(slot_ids: set[int]) -> dict[int, dict[str, Any]]:
    """Calendar slot id → the numbers of what the tool published from it."""
    if not slot_ids:
        return {}
    with get_session() as s:
        rows = s.exec(select(FbPost).where(FbPost.slot_id.in_(slot_ids))).all()  # type: ignore[union-attr]
    return {r.slot_id: {**(r.stats or {}), "reel": r.reel} for r in rows if r.stats}
