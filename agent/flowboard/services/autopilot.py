"""🤖 Tự động đăng — a Facebook Page that posts by itself on a fixed schedule (7/11).

A plan (:class:`AutoPlan`) says when (weekdays + times, Vietnam time) and what (the Posts form: kind, topic, tone,
pictures, a story series, products to talk about, which AI writes). The loop (:func:`run_loop`, every minute) looks
``lead_minutes`` ahead: each slot coming up gets one :class:`AutoRun` — inserting it is the claim (unique per plan +
slot, so two machines on the same database never both write) — and that run writes the post with the plan's AI
(the other one when it fails), draws its pictures through Flow, saves it in "Bài đã lưu" and puts it on the calendar
as an auto slot. From there the posting loop (services/scheduler) publishes it like any other.

The rule the seller asked for: a slot goes out only when its post is ready. Writing fails → retried every 10 minutes
while there is time; still nothing by the slot (+10 min) → the slot is skipped and says why. A picture Flow will not
draw does not hold the post back (it goes with the pictures it has). Slots that passed while the agent was off are
listed as missed, never posted late.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from flowboard.db import get_session, has_engine
from flowboard.db.models import AppSetting, AutoPlan, AutoRun, Channel, Post, Product, Request, Schedule
from flowboard.timestamps import utc_iso

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
TICK_S = 60.0
LEAD_MIN, LEAD_MAX, LEAD_DEFAULT = 30, 24 * 60, 180
MAX_TIMES = 6
#: A run being worked on is leased this long (renewed at every step); a lapsed lease = picked up again.
LEASE = timedelta(minutes=10)
RETRY_AFTER = timedelta(minutes=10)
MAX_ATTEMPTS = 3
#: A post ready this late after its slot still goes out; later than that the slot is skipped.
LATE_OK = timedelta(minutes=10)
#: Slots that passed while the agent was off are listed (as missed) this far back.
MISSED_LOOKBACK = timedelta(hours=12)
IMAGE_TIMEOUT_S = 4 * 60
POLL_S = 3.0
#: The plan's latest posts shown to the writer so the next one picks a new topic / opening.
RECENT_FOR_VARIETY = 8
AI_LABELS = {"claude": "Claude CLI", "gemini": "Gemini"}
PRODUCT_MODES = ("none", "fixed", "rotate")
DEFAULT_BRIEF: dict[str, Any] = {"kind": "discussion", "tone": "friendly", "length": "medium", "cta": "none", "hook": "auto",
                                 "format": "auto", "emoji": "some", "boosts": [], "images": 1}
#: Brief keys a plan keeps (the Posts form's); anything else is dropped.
BRIEF_KEYS = ("kind", "topic", "audience", "tone", "length", "cta", "hook", "format", "emoji", "boosts", "images",
              "image_wish", "extra")
#: hooks taken in turn when the plan says "AI tự chọn", so the posts do not all open alike
ROTATE_HOOKS = ("question", "story", "number", "pain", "surprise")
WEEKDAYS_VI = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")

#: run status → what the page shows (the calendar slot refines "ready")
ACTIVE = ("writing", "pictures", "waiting")


class AutopilotError(ValueError):
    """A plan that cannot be saved / turned on as asked (shown to the seller)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── the plan ───────────────────────────────────────────────────────────────

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _clean_times(values: Iterable[Any]) -> list[str]:
    out: set[str] = set()
    for v in values or []:
        m = _TIME_RE.match(str(v).strip())
        if m:
            out.add(f"{int(m.group(1)):02d}:{m.group(2)}")
    return sorted(out)


def clean_brief(brief: Any) -> dict[str, Any]:
    from flowboard.services.post_writer import MAX_IMAGES

    src = brief if isinstance(brief, dict) else {}
    out = {k: src[k] for k in BRIEF_KEYS if k in src and src[k] not in (None, "")}
    try:
        out["images"] = max(0, min(MAX_IMAGES, int(src.get("images", DEFAULT_BRIEF["images"]) or 0)))
    except (TypeError, ValueError):
        out["images"] = DEFAULT_BRIEF["images"]
    if "boosts" in out and not isinstance(out["boosts"], list):
        out.pop("boosts")
    if out.get("kind") == "serial":
        out["kind"] = "story"
    for k in ("topic", "audience", "image_wish", "extra"):
        if k in out:
            out[k] = str(out[k]).strip()[:1500]
    return out


def clean_fields(data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """The editable fields of a plan, checked (AutopilotError on what cannot be saved). ``partial`` = only the keys given."""
    from flowboard.services.llm.registry import AI_CHOICES

    out: dict[str, Any] = {}
    if "name" in data or not partial:
        out["name"] = str(data.get("name") or "").strip()[:80]
    if "channel_id" in data or not partial:
        try:
            out["channel_id"] = int(data.get("channel_id") or 0)
        except (TypeError, ValueError):
            out["channel_id"] = 0
        if not out["channel_id"]:
            raise AutopilotError("Chọn kênh / page cho lịch tự động.")
    if "days" in data or not partial:
        days = sorted({int(d) for d in data.get("days") or [] if str(d).lstrip("-").isdigit() and 0 <= int(d) <= 6})
        if not days:
            raise AutopilotError("Chọn ít nhất một ngày trong tuần.")
        out["days"] = days
    if "times" in data or not partial:
        times = _clean_times(data.get("times") or [])
        if not times:
            raise AutopilotError("Chọn ít nhất một giờ đăng (HH:MM).")
        if len(times) > MAX_TIMES:
            raise AutopilotError(f"Tối đa {MAX_TIMES} giờ đăng mỗi ngày.")
        out["times"] = times
    if "lead_minutes" in data or not partial:
        try:
            lead = int(data.get("lead_minutes") or LEAD_DEFAULT)
        except (TypeError, ValueError):
            lead = LEAD_DEFAULT
        out["lead_minutes"] = max(LEAD_MIN, min(LEAD_MAX, lead))
    if "brief" in data or not partial:
        out["brief"] = clean_brief(data.get("brief"))
    if "series" in data or not partial:
        out["series"] = str(data.get("series") or "").strip()[:80]
    if "product_mode" in data or "product_ids" in data or not partial:
        mode = data.get("product_mode") or "none"
        if mode not in PRODUCT_MODES:
            mode = "none"
        ids = [int(x) for x in data.get("product_ids") or [] if str(x).isdigit()]
        if mode != "none" and not ids:
            raise AutopilotError("Chọn sản phẩm cho lịch (hoặc chọn \"Không gắn sản phẩm\").")
        out["product_mode"], out["product_ids"] = mode, (ids[:1] if mode == "fixed" else ids[:30]) if mode != "none" else []
    if "ai" in data or not partial:
        out["ai"] = data.get("ai") if data.get("ai") in AI_CHOICES else "claude"
    if "fb_story" in data or not partial:
        out["fb_story"] = bool(data.get("fb_story"))
    return out


def slots_between(days: Iterable[int], times: Iterable[str], start: datetime, end: datetime) -> list[datetime]:
    """The plan's slot times (UTC) in ``(start, end]``."""
    days, times = set(days), _clean_times(times)
    if not days or not times:
        return []
    out: list[datetime] = []
    d: date = start.astimezone(TZ).date() - timedelta(days=1)
    last = end.astimezone(TZ).date() + timedelta(days=1)
    while d <= last:
        if d.weekday() in days:
            for t in times:
                hh, mm = map(int, t.split(":"))
                at = datetime.combine(d, time(hh, mm), tzinfo=TZ).astimezone(timezone.utc)
                if start < at <= end:
                    out.append(at)
        d += timedelta(days=1)
    return sorted(out)


def describe_when(days: Iterable[int], times: Iterable[str]) -> str:
    days = sorted(set(days))
    day_txt = "Mỗi ngày" if len(days) == 7 else " ".join(WEEKDAYS_VI[d] for d in days)
    return f"{day_txt} · {', '.join(_clean_times(times))}"


def _slot_label(at: datetime) -> str:
    local = at.astimezone(TZ)
    return f"{WEEKDAYS_VI[local.weekday()]} {local:%d/%m %H:%M}"


def _check_channel(channel_id: int, enabled: bool) -> None:
    from flowboard.services import scheduler

    with get_session() as s:
        if s.get(Channel, channel_id) is None:
            raise AutopilotError("Không thấy kênh này.")
    if enabled and not scheduler.can_auto(channel_id):
        raise AutopilotError("Kênh này chưa kết nối Facebook Page nên không tự đăng được — kết nối ở trang Kênh trước.")


def create_plan(data: dict[str, Any]) -> dict[str, Any]:
    fields = clean_fields(data)
    enabled = bool(data.get("enabled", True))
    _check_channel(fields["channel_id"], enabled)
    with get_session() as s:
        if not fields["name"]:
            ch = s.get(Channel, fields["channel_id"])
            fields["name"] = f"Tự động — {ch.name if ch else 'kênh'}"[:80]
        plan = AutoPlan(**fields, enabled=enabled)
        s.add(plan)
        s.commit()
        s.refresh(plan)
        pid = plan.id
    return get_plan(pid)  # type: ignore[arg-type]


def update_plan(plan_id: int, data: dict[str, Any]) -> dict[str, Any]:
    fields = clean_fields(data, partial=True)
    with get_session() as s:
        plan = s.get(AutoPlan, plan_id)
        if plan is None:
            raise AutopilotError("Không thấy lịch tự động này.")
        enabled = bool(data["enabled"]) if "enabled" in data else plan.enabled
        _check_channel(fields.get("channel_id", plan.channel_id), enabled)
        turned_on = enabled and not plan.enabled
        for k, v in fields.items():
            setattr(plan, k, v)
        plan.enabled = enabled
        if turned_on:
            plan.enabled_at = _now()  # slots before this are not "missed"
        plan.updated_at = _now()
        s.add(plan)
        s.commit()
        days, times, channel_id = list(plan.days), list(plan.times), plan.channel_id
    if not enabled:
        _cancel_future(plan_id, "Lịch tự động đã tạm dừng — bài không đăng.")
    elif {"days", "times", "channel_id"} & fields.keys():
        keep = set(slots_between(days, times, _now(), _now() + timedelta(days=60)))
        _cancel_future(plan_id, "Giờ đăng của lịch đã đổi — khung này bỏ.", keep=keep, channel_id=channel_id)
    return get_plan(plan_id)


def delete_plan(plan_id: int) -> bool:
    _cancel_future(plan_id, "Lịch tự động đã xoá — bài không đăng.")
    with get_session() as s:
        plan = s.get(AutoPlan, plan_id)
        if plan is None:
            return False
        for run in s.exec(select(AutoRun).where(AutoRun.plan_id == plan_id)).all():
            s.delete(run)
        s.delete(plan)
        s.commit()
    return True


def _cancel_future(plan_id: int, why: str, *, keep: Optional[set[datetime]] = None, channel_id: Optional[int] = None) -> int:
    """Runs of this plan still to go out → skipped, their calendar slots too (the posts stay in "Bài đã lưu").
    ``keep`` = slot times still in the plan (a schedule edit cancels only the ones that left it)."""
    now = _now()
    n = 0
    with get_session() as s:
        runs = s.exec(select(AutoRun).where(AutoRun.plan_id == plan_id, AutoRun.slot_at > now - LATE_OK)).all()
        for run in runs:
            if run.status not in (*ACTIVE, "ready"):
                continue
            if keep is not None and _aware(run.slot_at) in keep:
                if channel_id is None or not run.schedule_id:
                    continue
                sc = s.get(Schedule, run.schedule_id)
                if sc is None or sc.channel_id == channel_id:
                    continue
            if run.schedule_id:
                sc = s.get(Schedule, run.schedule_id)
                if sc is not None and sc.status == "planned":
                    sc.status, sc.updated_at = "skipped", now
                    sc.note = (why + (" · " + sc.note if sc.note else ""))[:300]
                    s.add(sc)
            run.status, run.error, run.updated_at, run.lease_until = "skipped", why, now, None
            s.add(run)
            n += 1
        s.commit()
    return n


# ── reading ────────────────────────────────────────────────────────────────

def _channel_names(ids: set[int]) -> dict[int, tuple[str, bool]]:
    from flowboard.services import scheduler

    out: dict[int, tuple[str, bool]] = {}
    with get_session() as s:
        for cid in ids:
            ch = s.get(Channel, cid)
            if ch is not None:
                out[cid] = (ch.name, False)
    return {cid: (name, scheduler.can_auto(cid)) for cid, (name, _) in out.items()}


def _plan_row(plan: AutoPlan, channels: dict[int, tuple[str, bool]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    name, connected = channels.get(plan.channel_id, ("(kênh đã xoá)", False))
    now = _now()
    upcoming = slots_between(plan.days, plan.times, now, now + timedelta(days=14))[:4] if plan.enabled else []
    by_slot = {r["slot_at"]: r for r in runs}
    return {
        "id": plan.id, "name": plan.name, "channel_id": plan.channel_id, "channel": name, "connected": connected,
        "enabled": plan.enabled, "days": list(plan.days), "times": list(plan.times), "lead_minutes": plan.lead_minutes,
        "brief": dict(plan.brief or {}), "series": plan.series, "product_mode": plan.product_mode,
        "product_ids": list(plan.product_ids or []), "ai": plan.ai, "fb_story": plan.fb_story,
        "when": describe_when(plan.days, plan.times),
        "next": [{"at": utc_iso(at), "label": _slot_label(at), "run": by_slot.get(utc_iso(at))} for at in upcoming],
        "runs": runs[:12],
        "created_at": utc_iso(plan.created_at), "updated_at": utc_iso(plan.updated_at),
    }


def _run_rows(runs: list[AutoRun]) -> list[dict[str, Any]]:
    post_ids = {r.post_id for r in runs if r.post_id}
    slot_ids = {r.schedule_id for r in runs if r.schedule_id}
    with get_session() as s:
        posts = {p.id: p for p in s.exec(select(Post).where(Post.id.in_(post_ids))).all()} if post_ids else {}  # type: ignore[union-attr]
        slots = {sc.id: sc for sc in s.exec(select(Schedule).where(Schedule.id.in_(slot_ids))).all()} if slot_ids else {}  # type: ignore[union-attr]
    out = []
    for r in runs:
        at = _aware(r.slot_at)
        p = posts.get(r.post_id) if r.post_id else None
        sc = slots.get(r.schedule_id) if r.schedule_id else None
        state, link, error = r.status, "", r.error
        if r.status == "ready" and sc is not None:
            result = sc.result or {}
            state = {"planned": "scheduled", "posting": "posting", "posted": "posted",
                     "failed": "post_failed", "skipped": "skipped"}.get(sc.status, "scheduled")
            link = str(result.get("permalink") or "")
            if sc.status == "failed":
                error = str(result.get("error") or "Đăng lỗi")
            elif sc.status == "skipped":
                error = sc.note or error
        out.append({
            "id": r.id, "plan_id": r.plan_id, "slot_at": utc_iso(at), "label": _slot_label(at) if at else "",
            "status": state, "post_id": r.post_id, "post_title": p.title if p else "", "images": len(p.images or []) if p else 0,
            "episode": p.episode if p else 0, "schedule_id": r.schedule_id, "link": link, "ai": AI_LABELS.get(r.ai_used, r.ai_used),
            "error": error, "note": r.note, "attempts": r.attempts, "updated_at": utc_iso(r.updated_at),
        })
    return out


def list_runs(plan_id: Optional[int] = None, limit: int = 30) -> list[dict[str, Any]]:
    with get_session() as s:
        q = select(AutoRun)
        if plan_id is not None:
            q = q.where(AutoRun.plan_id == plan_id)
        runs = s.exec(q.order_by(AutoRun.slot_at.desc()).limit(max(1, min(200, limit)))).all()  # type: ignore[union-attr]
    return _run_rows(list(runs))


def list_plans(channel_id: Optional[int] = None) -> list[dict[str, Any]]:
    with get_session() as s:
        q = select(AutoPlan)
        if channel_id is not None:
            q = q.where(AutoPlan.channel_id == channel_id)
        plans = s.exec(q.order_by(AutoPlan.id)).all()
        runs = s.exec(select(AutoRun).where(AutoRun.plan_id.in_([p.id for p in plans]))  # type: ignore[union-attr]
                      .order_by(AutoRun.slot_at.desc())).all() if plans else []
    rows = _run_rows(list(runs))
    channels = _channel_names({p.channel_id for p in plans})
    return [_plan_row(p, channels, [r for r in rows if r["plan_id"] == p.id]) for p in plans]


def get_plan(plan_id: int) -> dict[str, Any]:
    with get_session() as s:
        plan = s.get(AutoPlan, plan_id)
        if plan is None:
            raise AutopilotError("Không thấy lịch tự động này.")
        runs = s.exec(select(AutoRun).where(AutoRun.plan_id == plan_id).order_by(AutoRun.slot_at.desc()).limit(40)).all()  # type: ignore[union-attr]
    return _plan_row(plan, _channel_names({plan.channel_id}), _run_rows(list(runs)))


def active_runs() -> list[dict[str, Any]]:
    """Runs being written right now (the "việc đang chạy" button)."""
    if not has_engine():
        return []
    with get_session() as s:
        rows = s.exec(select(AutoRun, AutoPlan).where(AutoRun.plan_id == AutoPlan.id,
                                                      AutoRun.status.in_(("writing", "pictures")))).all()  # type: ignore[union-attr]
    return [{"run_id": r.id, "plan": p.name, "slot": _slot_label(_aware(r.slot_at)), "status": r.status,
             "started_at": utc_iso(r.updated_at)} for r, p in rows]


# ── the loop ───────────────────────────────────────────────────────────────

_tasks: dict[int, asyncio.Task] = {}


def _start(run_id: int) -> None:
    if run_id in _tasks and not _tasks[run_id].done():
        return
    _tasks[run_id] = asyncio.create_task(_work(run_id), name=f"autopilot-run-{run_id}")


def _take(run_id: int) -> bool:
    """Lease the run for this process, atomically (a lapsed lease can be taken over)."""
    now = _now()
    with get_session() as s:
        res = s.execute(sa_update(AutoRun).where(
            AutoRun.id == run_id,
            (AutoRun.lease_until.is_(None)) | (AutoRun.lease_until < now),  # type: ignore[union-attr]
        ).values(lease_until=now + LEASE, updated_at=now))
        s.commit()
        return res.rowcount == 1


def _set(run_id: int, **fields: Any) -> None:
    with get_session() as s:
        run = s.get(AutoRun, run_id)
        if run is None:
            return
        for k, v in fields.items():
            setattr(run, k, v)
        run.updated_at = _now()
        if run.status in ACTIVE and run.status != "waiting":
            run.lease_until = _now() + LEASE  # still working: keep the lease
        s.add(run)
        s.commit()


def _claim(plan_id: int, slot_at: datetime, status: str, error: str = "") -> Optional[int]:
    """Insert the run for (plan, slot); None when it exists already (another tick / machine got it first)."""
    now = _now()
    with get_session() as s:
        run = AutoRun(plan_id=plan_id, slot_at=slot_at, status=status, error=error,
                      lease_until=now + LEASE if status == "writing" else None)
        s.add(run)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            return None
        s.refresh(run)
        return run.id


async def tick() -> int:
    """Claim and start the slots coming up within each enabled plan's lead time; list the ones missed; pick up runs
    left halfway (restart) or waiting to retry. Returns how many runs were started."""
    from flowboard import plans

    if not has_engine() or not plans.active_allows("autopilot"):  # not in the account's plan (any more)
        return 0
    now = _now()
    started = 0
    with get_session() as s:
        plans = s.exec(select(AutoPlan).where(AutoPlan.enabled == True)).all()  # noqa: E712
        plans = [(p.id, list(p.days), list(p.times), p.lead_minutes, _aware(p.enabled_at)) for p in plans]
    for plan_id, days, times, lead, enabled_at in plans:
        horizon = now + timedelta(minutes=lead)
        floor = max(enabled_at or now, now - MISSED_LOOKBACK)
        slots = slots_between(days, times, floor, horizon)
        if not slots:
            continue
        with get_session() as s:
            have = {_aware(r.slot_at) for r in s.exec(select(AutoRun).where(
                AutoRun.plan_id == plan_id, AutoRun.slot_at >= slots[0], AutoRun.slot_at <= slots[-1])).all()}
        for at in slots:
            if at in have:
                continue
            if at <= now:
                _claim(plan_id, at, "missed", "Agent không chạy lúc cần soạn bài cho khung này — không đăng bù.")
                continue
            run_id = _claim(plan_id, at, "writing")
            if run_id is not None:
                _start(run_id)
                started += 1
    # runs left halfway (the agent restarted, the other machine closed) or due for another try
    with get_session() as s:
        todo = s.exec(select(AutoRun).where(AutoRun.status.in_(ACTIVE), AutoRun.slot_at > now - LATE_OK)).all()  # type: ignore[union-attr]
        todo = [(r.id, r.status, _aware(r.next_try_at), _aware(r.lease_until)) for r in todo]
    for run_id, status, next_try, lease in todo:
        if run_id in _tasks and not _tasks[run_id].done():
            continue
        if status == "waiting" and next_try and next_try > now:
            continue
        if lease and lease > now:
            continue
        if _take(run_id):
            _start(run_id)
            started += 1
    # runs that never made it by their slot
    with get_session() as s:
        late = s.exec(select(AutoRun).where(AutoRun.status.in_(ACTIVE), AutoRun.slot_at <= now - LATE_OK)).all()  # type: ignore[union-attr]
        for run in late:
            if run.id in _tasks and not _tasks[run.id].done():
                continue
            lease = _aware(run.lease_until)
            if lease and lease > now:  # still being worked on (another machine): it skips the slot itself
                continue
            run.status, run.lease_until, run.updated_at = "skipped", None, now
            run.error = (f"Chưa soạn xong khi tới giờ — bỏ khung này. {run.error}").strip()[:500]
            s.add(run)
        s.commit()
    return started


async def run_loop() -> None:
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop must outlive one bad tick
            logger.warning("autopilot tick failed: %s", exc)
        await asyncio.sleep(TICK_S)


def prepare_next(plan_id: int) -> dict[str, Any]:
    """"⚡ Soạn ngay": the plan's next slot that has nothing yet is written now (to see what it will post)."""
    now = _now()
    with get_session() as s:
        plan = s.get(AutoPlan, plan_id)
        if plan is None:
            raise AutopilotError("Không thấy lịch tự động này.")
        if not plan.enabled:
            raise AutopilotError("Lịch đang tạm dừng — bật lại rồi soạn.")
        slots = slots_between(plan.days, plan.times, now + timedelta(minutes=2), now + timedelta(days=14))
        have = {_aware(r.slot_at) for r in s.exec(select(AutoRun).where(AutoRun.plan_id == plan_id, AutoRun.slot_at > now)).all()}
    for at in slots:
        if at in have:
            continue
        run_id = _claim(plan_id, at, "writing")
        if run_id is not None:
            _start(run_id)
            return {"run_id": run_id, "slot_at": utc_iso(at), "label": _slot_label(at)}
    raise AutopilotError("Các khung trong 14 ngày tới đều đã có bài.")


# ── one run ────────────────────────────────────────────────────────────────

async def _work(run_id: int) -> None:
    try:
        await _prepare(run_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — a run that fails says why and may try again
        msg = str(exc)[:500] or exc.__class__.__name__
        logger.warning("autopilot: run %s failed: %s", run_id, msg)
        with get_session() as s:
            run = s.get(AutoRun, run_id)
            slot_at, attempts = (_aware(run.slot_at), run.attempts) if run else (None, MAX_ATTEMPTS)
        retry = slot_at is not None and attempts < MAX_ATTEMPTS and slot_at - _now() > RETRY_AFTER + timedelta(minutes=5)
        _set(run_id, status="waiting" if retry else "failed", error=msg, lease_until=None,
             next_try_at=_now() + RETRY_AFTER if retry else None)
    finally:
        _tasks.pop(run_id, None)


async def _prepare(run_id: int) -> None:
    from flowboard.routes.channels import get_channel
    from flowboard.services import scheduler

    with get_session() as s:
        run = s.get(AutoRun, run_id)
        if run is None or run.status not in ACTIVE:
            return
        plan = s.get(AutoPlan, run.plan_id)
        slot_at = _aware(run.slot_at)
        post_id = run.post_id
    if plan is None or not plan.enabled:
        _set(run_id, status="skipped", error="Lịch tự động đã tắt.", lease_until=None)
        return
    channel = get_channel(plan.channel_id)
    if channel is None:
        raise AutopilotError("Kênh của lịch không còn nữa.")
    if not scheduler.can_auto(plan.channel_id):
        raise AutopilotError("Kênh chưa kết nối Facebook Page (hoặc token hết hạn) — không tự đăng được.")
    if post_id is None:
        _set(run_id, status="writing", attempts=(run.attempts or 0) + 1, error="")
        post_id, product_id, ai_used = await _write(plan, run_id, slot_at, channel)
        _set(run_id, status="pictures", post_id=post_id, product_id=product_id, ai_used=ai_used)
    await _pictures(run_id, post_id, plan, slot_at)
    now = _now()
    if now > slot_at + LATE_OK:
        _set(run_id, status="skipped", lease_until=None,
             error="Soạn xong trễ giờ đăng quá 10 phút — bỏ khung này; bài vẫn nằm trong Bài đã lưu.")
        return
    slot = scheduler.create("post", max(slot_at, now), post_id=post_id, channel_id=plan.channel_id, auto=True,
                            note=f"🤖 Tự động: {plan.name}", fb_format="post", fb_story=plan.fb_story)
    _set(run_id, status="ready", schedule_id=slot["id"], lease_until=None, next_try_at=None, error="")
    logger.info("autopilot: run %s ready — post %s goes out %s", run_id, post_id, _slot_label(slot_at))


def _pick_product(plan: AutoPlan) -> Optional[int]:
    ids = [int(x) for x in plan.product_ids or []]
    if plan.product_mode == "none" or not ids:
        return None
    with get_session() as s:
        alive = {p.id for p in s.exec(select(Product).where(Product.id.in_(ids))).all()}  # type: ignore[union-attr]
        ids = [i for i in ids if i in alive]
        if not ids:
            return None
        if plan.product_mode == "fixed":
            return ids[0]
        # in turn: the one this plan talked about longest ago (never first)
        used: dict[int, datetime] = {}
        for r in s.exec(select(AutoRun).where(AutoRun.plan_id == plan.id, AutoRun.product_id.is_not(None))).all():  # type: ignore[union-attr]
            at = _aware(r.created_at)
            if r.product_id in ids and at and (r.product_id not in used or at > used[r.product_id]):
                used[r.product_id] = at
    return min(ids, key=lambda i: (used.get(i) or datetime.min.replace(tzinfo=timezone.utc), ids.index(i)))


def _recent_posts(plan_id: int, channel_id: int) -> list[Post]:
    with get_session() as s:
        rows = s.exec(select(Post).where(Post.channel_id == channel_id).order_by(Post.id.desc()).limit(60)).all()  # type: ignore[union-attr]
    return [p for p in rows if (p.brief or {}).get("auto_plan") == plan_id][:RECENT_FOR_VARIETY]


def _extra_block(plan: AutoPlan, slot_at: datetime, brief: dict[str, Any], recent: list[Post]) -> str:
    lines = [f"AUTO SCHEDULE: this post goes out on its own on {_slot_label(slot_at)} (Vietnam time) and nobody reads it "
             "before it is posted — stick strictly to the facts given about the product and the page; never invent "
             "prices, numbers, results, reviews or flaws."]
    if not str(brief.get("topic") or "").strip() and not plan.series:
        lines.append("No topic was given: pick a fresh topic that fits the page (its direction, pillars and ideas above).")
    if recent and not plan.series:
        lines.append("ALREADY POSTED by this schedule (newest first) — take a different topic or angle and a different "
                     "opening line from every one of these:")
        for p in recent:
            first = (p.body or "").strip().split("\n")[0][:140]
            lines.append(f"- {p.title[:100]} — {first}")
    return "\n".join(lines)


async def _write(plan: AutoPlan, run_id: int, slot_at: datetime, channel: dict[str, Any]) -> tuple[int, Optional[int], str]:
    from flowboard.routes.posts import _save_written, _series_context
    from flowboard.services import post_writer
    from flowboard.services.llm.registry import use_ai
    from flowboard.services.products import get_product

    product_id = _pick_product(plan)
    product = get_product(product_id) if product_id else None
    brief: dict[str, Any] = {**DEFAULT_BRIEF, **clean_brief(plan.brief)}
    if product and product.get("aff_link") and brief.get("cta") in (None, "", "none"):
        brief["cta"] = "link"  # the link goes in the first comment
    recent = _recent_posts(plan.id, plan.channel_id)
    if (brief.get("hook") or "auto") == "auto" and not plan.series:
        brief["hook"] = ROTATE_HOOKS[len(recent) % len(ROTATE_HOOKS)]
    brief["auto_plan"] = plan.id
    series_ctx = None
    if plan.series:
        series_ctx = _series_context(plan.series, plan.channel_id) or {"name": plan.series, "episode": 1, "previous": []}
    extra = _extra_block(plan, slot_at, brief, recent)
    order = [plan.ai, *[a for a in AI_LABELS if a != plan.ai]]
    errors: list[str] = []
    for ai in order:
        try:
            with use_ai(ai):
                post = await post_writer.write_post(brief, product=product, clip=None, channel=channel,
                                                    series=series_ctx, extra=extra, timeout=180.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — try the other AI
            errors.append(f"{AI_LABELS[ai]}: {str(exc)[:200]}")
            logger.info("autopilot: run %s — %s could not write: %s", run_id, ai, exc)
            continue
        row = _save_written(post, brief=brief, product_id=product_id, channel_id=plan.channel_id, board_id=None,
                            series=plan.series, episode=series_ctx["episode"] if series_ctx else 0)
        if errors:
            _set(run_id, note=("Viết bằng " + AI_LABELS[ai] + " vì " + "; ".join(errors))[:500])
        return int(row["id"]), product_id, ai
    raise AutopilotError("AI chưa viết được bài — " + "; ".join(errors))


def _image_model() -> Optional[str]:
    import json

    with get_session() as s:
        row = s.get(AppSetting, "ui_prefs")
    try:
        v = json.loads(row.value).get("imageModel") if row else None
    except ValueError:
        v = None
    return v if isinstance(v, str) and v else None


async def _pictures(run_id: int, post_id: int, plan: AutoPlan, slot_at: datetime) -> None:
    """The post's AI pictures through Flow (square, the product photo as reference), all asked at once; whatever Flow
    does not draw before the slot is left out (noted on the run) — the post still goes out."""
    from flowboard.services import media as media_service
    from flowboard.services.flow_project import effective_project_id
    from flowboard.services.products import get_product
    from flowboard.worker.processor import get_worker

    with get_session() as s:
        post = s.get(Post, post_id)
        run = s.get(AutoRun, run_id)
        if post is None or run is None:
            raise AutopilotError("Bài vừa viết không còn nữa.")
        want = max(0, min(int((post.brief or {}).get("images") or 0), len(post.image_prompts or [])))
        have = list(post.images or [])
        prompts = list(post.image_prompts or [])[:want]
        requests = list(run.image_requests or [])
        product_id = post.product_id
    if want == 0 or len(have) >= want:
        return
    project = effective_project_id()
    if not project:
        _set(run_id, note="Chưa ghim Flow project — bài đăng không kèm ảnh.")
        return
    product = get_product(product_id) if product_id else None
    refs = list((product or {}).get("media_ids") or [])[:1]
    im = _image_model()
    while len(requests) < len(prompts):
        params: dict[str, Any] = {"prompt": prompts[len(requests)], "media_provider": "flow", "project_id": project,
                                  "aspect_ratio": "IMAGE_ASPECT_RATIO_SQUARE", "variant_count": 1, "origin": "autopilot",
                                  "autopilot_run": run_id}
        if refs:
            params["ref_media_ids"] = refs
        if im:
            params["image_model"] = im
        with get_session() as s:
            req = Request(type="gen_image", params=params, status="queued")
            s.add(req)
            s.commit()
            s.refresh(req)
            requests.append(req.id)
        get_worker().enqueue(requests[-1])
        _set(run_id, image_requests=list(requests))
    deadline = min(_now() + timedelta(seconds=IMAGE_TIMEOUT_S), slot_at - timedelta(minutes=2))
    pending = {k: rid for k, rid in enumerate(requests[:len(prompts)])}
    got: dict[int, str] = {}
    failed: list[str] = []
    while pending and _now() < deadline:
        for k, rid in list(pending.items()):
            with get_session() as s:
                r = s.get(Request, rid)
                status, result, err = (r.status, r.result or {}, r.error) if r else ("failed", {}, "request missing")
            if status == "done":
                ids = result.get("media_ids") or []
                if ids:
                    got[k] = ids[0]
                    try:
                        if media_service.cached_path(ids[0]) is None:
                            await media_service.fetch_and_cache(ids[0])
                    except Exception as exc:  # noqa: BLE001 — loaded at posting time anyway
                        logger.info("autopilot: pre-fetch of %s failed: %s", ids[0], exc)
                else:
                    failed.append(f"ảnh {k + 1}: Flow không trả ảnh (bộ lọc nội dung?)")
                pending.pop(k)
            elif status in ("failed", "canceled", "timeout", "error"):
                failed.append(f"ảnh {k + 1}: {str(err or status)[:120]}")
                pending.pop(k)
        _set(run_id, status="pictures")  # renews the lease
        if pending:
            await asyncio.sleep(POLL_S)
    if pending:
        failed.append(f"{len(pending)} ảnh Flow chưa vẽ xong trước giờ đăng")
    images = [got[k] for k in sorted(got)]
    if images:
        with get_session() as s:
            post = s.get(Post, post_id)
            if post is not None:
                post.images = images
                post.updated_at = _now()
                s.add(post)
                s.commit()
    if failed:
        _set(run_id, note=("Đăng kèm " + (f"{len(images)}/{want} ảnh" if images else "không ảnh") + " — " + "; ".join(failed))[:500])
