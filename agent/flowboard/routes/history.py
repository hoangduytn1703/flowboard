"""Job history — the Quicktool's read-only view over the ``Request`` table.

The Canvas activity feed (``routes/activity.py``) projects the same rows for
the bell dropdown. This one is for the ``/history`` page: it joins the node
and board so a row can say *which clip* it belongs to, pulls the prompt /
narration into a one-line summary, lists the media ids the job produced
(so the page can offer a download for each), and attaches a credit
estimate so the user can see roughly what a day of generation cost.

Endpoints (all read-only):
  GET /api/history?limit=50&before_id=&type=&status=&board_id=
      → {items: [HistoryRow], next_before_id}
  GET /api/history/summary
      → {today: {jobs, done, error, credits_estimate}, week: {...}, total_media}
  GET /api/history/{id}
      → HistoryRow + params / result (for the detail modal and "retry")
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Board, Node, Request
from flowboard.services.flow_sdk import DEFAULT_VIDEO_QUALITY, OMNI_FLASH_CREDIT_COST
from flowboard.timestamps import utc_iso

router = APIRouter(prefix="/api/history", tags=["history"])

#: Vietnamese labels per request type. Unknown types fall back to the raw
#: type string so a new worker handler still renders.
TYPE_LABELS_VI: dict[str, str] = {
    "gen_image": "Tạo ảnh",
    "gen_video": "Tạo video (Veo)",
    "gen_video_omni": "Tạo video (Omni)",
    "edit_image": "Sửa ảnh",
    "export_video": "Ghép video",
    "create_project": "Tạo project Flow",
    "http": "Gọi Flow",
    "vision": "Đọc ảnh (AI)",
    "auto_prompt": "Viết prompt",
    "auto_prompt_batch": "Viết prompt (hàng loạt)",
    "planner": "Lập kế hoạch",
    "narration": "Viết lời đọc",
    "storyboard_split": "Tách storyboard",
    "chat_agent": "Trợ lý chat",
    "upload": "Tải ảnh lên",
    "upload_url": "Tải ảnh từ link",
}

#: Statuses the summary / the ``status=error`` filter treat as failures.
#: The worker stamps ``failed`` (and ``timeout`` for the 5-minute video
#: budget); ``error`` is accepted as an alias because that is what the node
#: status and the UI call it.
ERROR_STATUSES: tuple[str, ...] = ("failed", "timeout", "error")

#: Flow credit price per Veo render, keyed by the ``video_quality`` the
#: worker dispatches. Estimates — Flow does not report the real charge back,
#: and the ``*_relaxed`` queues are the 0-credit low-priority ones.
VEO_CREDITS: dict[str, int] = {
    "lite": 10,
    "fast": 20,
    "quality": 100,
    "lite_relaxed": 0,
    "fast_relaxed": 0,
}

#: Omni Flash falls back to this duration when the request carries none —
#: mirrors the worker default (8 s).
OMNI_DEFAULT_DURATION_S = 8

#: Types that cost nothing on the user's Flow plan (images are included in
#: Pro/Ultra; the rest never touch Flow's credit meter).
FREE_TYPES: frozenset[str] = frozenset({
    "gen_image", "edit_image", "export_video", "create_project", "http",
    "vision", "auto_prompt", "auto_prompt_batch", "planner", "narration",
    "storyboard_split", "chat_agent", "upload", "upload_url",
})

#: Types whose output is media worth counting / downloading.
MEDIA_TYPES: frozenset[str] = frozenset({
    "gen_image", "gen_video", "gen_video_omni", "edit_image", "export_video",
    "upload", "upload_url",
})

#: Types the page may resubmit as-is through ``POST /api/requests``.
RETRYABLE_TYPES: frozenset[str] = frozenset({"gen_image", "gen_video", "gen_video_omni"})

SUMMARY_CHARS = 90


# ── projection helpers ───────────────────────────────────────────────────────

def _duration_ms(req: Request) -> Optional[int]:
    if req.finished_at is None:
        return None
    return int((req.finished_at - req.created_at).total_seconds() * 1000)


def _variant_count(params: dict) -> int:
    raw = params.get("variant_count")
    try:
        n = int(raw) if raw is not None else 1
    except (TypeError, ValueError):
        n = 1
    return max(1, n)


def credits_estimate(req_type: str, params: Optional[dict]) -> Optional[int]:
    """Rough Flow credit cost of one request, or None when unknown.

    Veo: ``params.video_quality`` → :data:`VEO_CREDITS`. Omni Flash:
    ``params.duration_s`` → ``flow_sdk.OMNI_FLASH_CREDIT_COST``. Both are
    multiplied by ``variant_count`` because every variant is its own render.
    """
    params = params or {}
    if req_type == "gen_video_omni":
        raw = params.get("duration_s")
        try:
            dur = int(raw) if raw is not None else OMNI_DEFAULT_DURATION_S
        except (TypeError, ValueError):
            dur = OMNI_DEFAULT_DURATION_S
        base = OMNI_FLASH_CREDIT_COST.get(dur)
        if base is None:
            return None
        return base * _variant_count(params)
    if req_type == "gen_video":
        q = params.get("video_quality")
        q = q.strip().lower() if isinstance(q, str) and q.strip() else DEFAULT_VIDEO_QUALITY
        base = VEO_CREDITS.get(q)
        if base is None:
            return None
        return base * _variant_count(params)
    if req_type in FREE_TYPES:
        return 0
    return None


def media_ids_of(result: Optional[dict]) -> list[str]:
    """Collect media ids from the shapes the worker and the sidecar writers
    use: ``media_ids`` (positional list), ``media_entries[].media_id``,
    single ``media_id`` / ``out_media_id``. Order preserved, de-duplicated."""
    if not isinstance(result, dict):
        return []
    out: list[str] = []

    def add(mid: Any) -> None:
        if isinstance(mid, str) and mid.strip() and mid not in out:
            out.append(mid.strip())

    raw = result.get("media_ids")
    if isinstance(raw, list):
        for m in raw:
            add(m)
    entries = result.get("media_entries")
    if isinstance(entries, list):
        for e in entries:
            if isinstance(e, dict):
                add(e.get("media_id"))
    add(result.get("media_id"))
    add(result.get("out_media_id"))
    return out


def _first_text(*candidates: Any) -> Optional[str]:
    for c in candidates:
        if isinstance(c, list):
            c = next((x for x in c if isinstance(x, str) and x.strip()), None)
        if isinstance(c, str) and c.strip():
            return " ".join(c.split())
    return None


def summary_of(params: Optional[dict], node_data: Optional[dict]) -> Optional[str]:
    """One-line gist: the prompt or narration the job ran with, else the
    node's own prompt / narration / title. Trimmed to ~90 chars."""
    params = params or {}
    node_data = node_data or {}
    items = params.get("items")
    first_item_narr = None
    if isinstance(items, list) and items and isinstance(items[0], dict):
        first_item_narr = items[0].get("narration") or items[0].get("caption")
    text = _first_text(
        params.get("prompt"),
        params.get("prompts"),
        params.get("narrations"),
        first_item_narr,
        params.get("text"),
        params.get("name"),
        node_data.get("prompt"),
        node_data.get("narration"),
        node_data.get("title"),
    )
    if text is None:
        return None
    if len(text) > SUMMARY_CHARS:
        return text[: SUMMARY_CHARS - 1].rstrip() + "…"
    return text


def _project(
    req: Request,
    node: Optional[Node],
    board: Optional[Board],
    *,
    full: bool = False,
) -> dict:
    params = req.params if isinstance(req.params, dict) else {}
    result = req.result if isinstance(req.result, dict) else {}
    media_ids = media_ids_of(result)
    node_data = node.data if node is not None and isinstance(node.data, dict) else {}
    row: dict[str, Any] = {
        "id": req.id,
        "type": req.type,
        "type_label_vi": TYPE_LABELS_VI.get(req.type, req.type),
        "status": req.status,
        "created_at": utc_iso(req.created_at),
        "finished_at": utc_iso(req.finished_at),
        "duration_ms": _duration_ms(req),
        "board": {"id": board.id, "name": board.name} if board is not None else None,
        "node": (
            {
                "id": node.id,
                "short_id": node.short_id,
                "title": node_data.get("title"),
                "type": node.type,
            }
            if node is not None
            else None
        ),
        "summary": summary_of(params, node_data),
        "media_ids": media_ids,
        "thumbnail": media_ids[0] if media_ids else None,
        "credits_estimate": credits_estimate(req.type, params),
        "error": req.error,
        # The page offers "retry" only when the node the job targeted still
        # exists; a request whose node was deleted would 404 on resubmit.
        "can_retry": req.type in RETRYABLE_TYPES and node is not None,
    }
    if full:
        row["params"] = params
        row["result"] = result
    return row


def _load_nodes_and_boards(
    s, node_ids: Iterable[Optional[int]]
) -> tuple[dict[int, Node], dict[int, Board]]:
    ids = {n for n in node_ids if n is not None}
    nodes: dict[int, Node] = {}
    boards: dict[int, Board] = {}
    if not ids:
        return nodes, boards
    for n in s.exec(select(Node).where(Node.id.in_(ids))).all():
        if n.id is not None:
            nodes[n.id] = n
    board_ids = {n.board_id for n in nodes.values()}
    if board_ids:
        for b in s.exec(select(Board).where(Board.id.in_(board_ids))).all():
            if b.id is not None:
                boards[b.id] = b
    return nodes, boards


def _csv(value: Optional[str]) -> Optional[set[str]]:
    if not value:
        return None
    parts = {t.strip() for t in value.split(",") if t.strip()}
    return parts or None


# ── routes ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def history_summary() -> dict:
    """Counts for the strip above the list: today, the last 7 days, and the
    total number of media files every finished job has produced.

    "Today" is the local calendar day (single-user local tool), compared in
    UTC against the naive-UTC timestamps SQLite hands back."""
    now_local = datetime.now().astimezone()
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start.astimezone(timezone.utc).replace(tzinfo=None)
    week_start_utc = (datetime.now(timezone.utc) - timedelta(days=7)).replace(tzinfo=None)

    def bucket() -> dict[str, int]:
        return {"jobs": 0, "done": 0, "error": 0, "credits_estimate": 0}

    today, week = bucket(), bucket()
    total_media = 0
    with get_session() as s:
        rows = s.exec(
            select(Request.type, Request.status, Request.params, Request.result, Request.created_at)
        ).all()
    for req_type, status, params, result, created_at in rows:
        created = created_at
        if created is not None and created.tzinfo is not None:
            created = created.astimezone(timezone.utc).replace(tzinfo=None)
        if status == "done" and req_type in MEDIA_TYPES:
            total_media += len(media_ids_of(result))
        for start, acc in ((week_start_utc, week), (today_start_utc, today)):
            if created is None or created < start:
                continue
            acc["jobs"] += 1
            if status == "done":
                acc["done"] += 1
            elif status in ERROR_STATUSES:
                acc["error"] += 1
            # Credits are spent when Flow accepts the job, whether or not it
            # finishes, so count everything that is not still queued.
            if status != "queued":
                acc["credits_estimate"] += credits_estimate(req_type, params) or 0
    return {"today": today, "week": week, "total_media": total_media}


@router.get("")
def list_history(
    limit: int = Query(50, ge=1, le=200),
    before_id: Optional[int] = Query(None, ge=1),
    type: Optional[str] = Query(None, description="Comma-separated type filter"),
    status: Optional[str] = Query(None, description="Comma-separated status filter; `error` = failed+timeout"),
    board_id: Optional[int] = Query(None, ge=1),
) -> dict:
    """Newest first, cursor-paginated: pass ``next_before_id`` back as
    ``before_id`` for the next page (``null`` when there is none)."""
    type_filter = _csv(type)
    status_filter = _csv(status)
    if status_filter and "error" in status_filter:
        status_filter |= set(ERROR_STATUSES)
    fetch = limit + 1

    with get_session() as s:
        stmt = select(Request).order_by(Request.id.desc()).limit(fetch)
        if before_id is not None:
            stmt = stmt.where(Request.id < before_id)
        if type_filter:
            stmt = stmt.where(Request.type.in_(type_filter))
        if status_filter:
            stmt = stmt.where(Request.status.in_(status_filter))
        if board_id is not None:
            if s.get(Board, board_id) is None:
                raise HTTPException(404, "board not found")
            node_ids = list(s.exec(select(Node.id).where(Node.board_id == board_id)).all())
            if not node_ids:
                return {"items": [], "next_before_id": None}
            stmt = stmt.where(Request.node_id.in_(node_ids))
        rows = s.exec(stmt).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        nodes, boards = _load_nodes_and_boards(s, (r.node_id for r in rows))
        items = []
        for r in rows:
            node = nodes.get(r.node_id) if r.node_id is not None else None
            board = boards.get(node.board_id) if node is not None else None
            items.append(_project(r, node, board))

    next_before_id = rows[-1].id if has_more and rows else None
    return {"items": items, "next_before_id": next_before_id}


@router.get("/{request_id}")
def get_history_detail(request_id: int) -> dict:
    """The full row — params, result, error — for the detail modal and for
    rebuilding a ``POST /api/requests`` body on retry."""
    with get_session() as s:
        req = s.get(Request, request_id)
        if req is None:
            raise HTTPException(404, "history row not found")
        node = s.get(Node, req.node_id) if req.node_id is not None else None
        board = s.get(Board, node.board_id) if node is not None else None
        return _project(req, node, board, full=True)


# ── POST /api/history/clear ────────────────────────────────────────────
# "🧹 Dọn lịch sử": drop finished rows. Queued / running jobs are never
# touched (the worker owns them). Media files and Flow's real credit balance
# are untouched too — only the history rows and the credit estimates they
# carry go. ``dry_run`` answers "how many would go" for the confirm button.

FINISHED_STATUSES: tuple[str, ...] = ("done", "failed", "timeout", "error", "canceled")
CLEAR_SCOPES = {"all", "errors", "older"}


class ClearBody(BaseModel):
    scope: str = "all"  # all finished | errors only | older than ``days``
    days: int = Field(default=30, ge=1, le=3650)
    dry_run: bool = False


def _clear_stmt(body: ClearBody):
    statuses = ("failed", "timeout", "error", "canceled") if body.scope == "errors" else FINISHED_STATUSES
    stmt = select(Request).where(Request.status.in_(statuses))
    if body.scope == "older":
        # Aware: the column type (UTCDateTime) refuses naive datetimes as bind values.
        cutoff = datetime.now(timezone.utc) - timedelta(days=body.days)
        stmt = stmt.where(Request.created_at < cutoff)
    return stmt


@router.post("/clear")
def clear_history(body: ClearBody) -> dict:
    if body.scope not in CLEAR_SCOPES:
        raise HTTPException(400, f"scope phải là một trong {sorted(CLEAR_SCOPES)}")
    with get_session() as s:
        rows = s.exec(_clear_stmt(body)).all()
        count = len(rows)
        if not body.dry_run and rows:
            for r in rows:
                s.delete(r)
            s.commit()
    return {"count": count, "deleted": 0 if body.dry_run else count, "dry_run": body.dry_run}
