"""What is running right now, for the floating "đang chạy" badge that sits on
every page (``components/BackgroundTasks``): leave a page while something
heavy works, the badge says so and one click goes back to it.

  GET /api/running            → {items: [{key, kind, title, detail, progress, started_at, link}]}
  GET /api/running/outcome?key=dub:<id>|clean:<id>|capcut:<id>|clip:<board>|flow:other|op:<id>
                              → {ok: bool, message}   how a task that left the list ended
  GET /api/running/latest?kind=post_write&claim=1
                              → the newest unclaimed in-page operation of a kind, with its
                                result when done (the posts page restores a post the AI
                                finished while you were on another page)

In-page operations (an AI write, a link read, a page review…) come from
``services/op_tracker`` (the ``_track_long_ops`` middleware).

Sources:
- dubbing jobs (``services/dub``: queued / running / rendering) → ``/tools/dub?job=<id>``
- links waiting in the dubbing link library (``services/dub_links``) → ``/tools/dub?links=1``
- AI subtitle-erase jobs (``services/video_clean``) → ``/tools/clean?job=<id>``
- Edit auto CapCut jobs (``services/capcut_auto``) → ``/tools/capcut?job=<id>``
- 🤖 Trợ lý AI background tasks (``services/assistant``) → the page of what it makes, chat opened (``?assistant=1``)
- Flow work in the request queue (images, videos, joins), grouped per clip
  → the clip's wizard step; work with no clip (a post's or a model's image)
  → ``/history``.

``progress`` is 0–100 when the job knows it, else null. Rows older than
:data:`STALE_AFTER` are ignored: an orphaned "running" row must not keep the
badge up forever.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Board, Node, Request
from flowboard.timestamps import utc_iso

router = APIRouter(prefix="/api/running", tags=["running"])

#: Worker request types worth a badge (LLM calls are short and page-bound).
FLOW_TYPES: dict[str, str] = {
    "gen_image": "ảnh",
    "edit_image": "ảnh",
    "gen_video": "video",
    "gen_video_omni": "video",
    "export_video": "ghép clip",
}
STALE_AFTER = timedelta(hours=2)


def _iso_from_ts(ts: float) -> Optional[str]:
    try:
        return utc_iso(datetime.fromtimestamp(ts, tz=timezone.utc))
    except (TypeError, ValueError, OSError):
        return None


def _dub_items() -> list[dict[str, Any]]:
    from flowboard.services import dub

    try:
        dub.load_jobs()
    except Exception:  # noqa: BLE001 — the badge must never break on a bad job file
        pass
    out = []
    for j in list(dub.JOBS.values()):
        if j.status not in ("queued", "running", "rendering"):
            continue
        if j.kind == "cut":  # a part of "✂️ Cắt video" being exported
            out.append({"key": f"dub:{j.id}", "kind": "cut", "title": f"Xuất “{j.name or j.title or 'video đã cắt'}”",
                        "detail": j.phase or "Đang xuất", "progress": int(j.progress) if j.status != "queued" else None,
                        "started_at": _iso_from_ts(j.started_at),
                        "link": f"/tools/cut?job={j.id}" + (f"&run={j.batch_id}" if j.batch_id else "")})
            continue
        out.append({
            "key": f"dub:{j.id}", "kind": "dub",
            "title": j.name or j.title or "Video lồng tiếng",
            "detail": j.phase or ("Chờ đến lượt" if j.status == "queued" else "Đang chạy"),
            "progress": int(j.progress) if j.status != "queued" else None,
            "started_at": _iso_from_ts(j.started_at),
            "link": f"/tools/dub?job={j.id}" + (f"&batch={j.batch_id}" if j.batch_id else ""),
        })
    return out


def _dub_split_items() -> list[dict[str, Any]]:
    """"✂️ Cắt thành nhiều video" running (ffmpeg, one thread per video)."""
    from flowboard.services import dub_split

    out = []
    for job_id, st in list(dub_split.SPLITS.items()):
        if st.get("status") != "running":
            continue
        out.append({"key": f"dubsplit:{job_id}", "kind": "dub", "title": f"Cắt “{st.get('title') or 'video'}”",
                    "detail": st.get("phase") or "Đang cắt", "progress": int(st.get("progress") or 0),
                    "started_at": _iso_from_ts(st.get("started_at") or 0), "link": f"/tools/dub?job={job_id}"})
    return out


def _cut_items() -> list[dict[str, Any]]:
    """"✂️ Cắt video" sessions downloading / being heard / cut."""
    from flowboard.services import video_cut

    return [dict(it, started_at=_iso_from_ts(it["started_at"])) for it in video_cut.running_items()]


def _dub_link_items() -> list[dict[str, Any]]:
    """Links waiting in the dubbing link library (they start one by one as the dub queue frees up)."""
    from flowboard.services import dub_links

    n = dub_links.waiting_count()
    if not n:
        return []
    return [{"key": "dublinks:queue", "kind": "dub", "title": "Thư viện link lồng tiếng",
             "detail": f"{n} link chờ đến lượt", "progress": None, "started_at": None, "link": "/tools/dub?links=1"}]


def _clean_items() -> list[dict[str, Any]]:
    from flowboard.services import video_clean

    out = []
    for j in list(video_clean.JOBS.values()):
        if j.status not in ("queued", "running"):
            continue
        out.append({
            "key": f"clean:{j.id}", "kind": "clean", "title": "Xoá chữ / phụ đề bằng AI",
            "detail": "Đang khởi động" if j.status == "queued" else f"Đang xoá… {j.progress}%",
            "progress": int(j.progress) if j.status == "running" else None,
            "started_at": _iso_from_ts(j.started_at), "link": f"/tools/clean?job={j.id}",
        })
    return out


def _capcut_items() -> list[dict[str, Any]]:
    from flowboard.services import capcut_auto

    out = []
    for j in capcut_auto.active():
        out.append({
            "key": f"capcut:{j.id}", "kind": "capcut",
            "title": f"Dự án CapCut: {(j.source or {}).get('title') or 'video'}",
            "detail": j.phase, "progress": int(j.progress) if j.status == "running" else None,
            "started_at": _iso_from_ts(j.started_at), "link": f"/tools/capcut?job={j.id}",
        })
    return out


def _assistant_items() -> list[dict[str, Any]]:
    from flowboard.services import assistant

    def back(link: str) -> str:  # the page of what it makes, with the chat open
        return f"{link}{'&' if '?' in link else '?'}assistant=1"

    return [{"key": f"assistant:{t['id']}", "kind": "assistant", "title": f"Trợ lý AI · {t['title']}", "detail": t["step"],
             "progress": None, "started_at": t["started_at"], "link": back(t.get("link") or "/today")}
            for t in assistant.running_tasks()]


def _autopilot_items() -> list[dict[str, Any]]:
    from flowboard.services import autopilot

    return [{"key": f"autopilot:{r['run_id']}", "kind": "autopilot", "title": f"Tự động đăng · {r['plan']}",
             "detail": ("AI đang viết bài" if r["status"] == "writing" else "Flow đang vẽ ảnh cho bài") + f" — khung {r['slot']}",
             "progress": None, "started_at": r["started_at"], "link": "/posts?auto=1"}
            for r in autopilot.active_runs()]


def _op_items() -> list[dict[str, Any]]:
    from flowboard.services import op_tracker

    return op_tracker.active_items()


def _step_for(kinds: set[str]) -> str:
    if "ghép clip" in kinds:
        return "export"
    if "video" in kinds:
        return "videos"
    return "images"


def _flow_items() -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - STALE_AFTER
    with get_session() as s:
        rows = s.exec(select(Request).where(Request.status.in_(("queued", "running")),  # type: ignore[union-attr]
                                            Request.type.in_(tuple(FLOW_TYPES)),  # type: ignore[union-attr]
                                            Request.created_at >= since)
                      .order_by(Request.id)).all()
        node_ids = {r.node_id for r in rows if r.node_id}
        node_board = {n.id: n.board_id for n in s.exec(select(Node).where(Node.id.in_(node_ids))).all()} if node_ids else {}  # type: ignore[union-attr]
        board_ids = set(node_board.values())
        boards = {b.id: b.name for b in s.exec(select(Board).where(Board.id.in_(board_ids))).all()} if board_ids else {}  # type: ignore[union-attr]
    groups: dict[Optional[int], dict[str, Any]] = {}
    for r in rows:
        if (r.params or {}).get("origin") in ("assistant", "autopilot"):
            continue  # the assistant's / auto posting's own row says it, with a link back
        bid = node_board.get(r.node_id) if r.node_id else None
        g = groups.setdefault(bid, {"kinds": {}, "first": r.created_at, "running": 0})
        label = FLOW_TYPES[r.type]
        g["kinds"][label] = g["kinds"].get(label, 0) + 1
        g["running"] += 1 if r.status == "running" else 0
    out = []
    for bid, g in groups.items():
        parts = [f"{n} {label}" for label, n in g["kinds"].items()]
        detail = ("Flow đang làm " if g["running"] else "Đang chờ Flow: ") + ", ".join(parts)
        if bid is not None:
            out.append({"key": f"clip:{bid}", "kind": "clip", "title": boards.get(bid) or f"Clip #{bid}", "detail": detail,
                        "progress": None, "started_at": utc_iso(g["first"]),
                        "link": f"/clips/{bid}/{_step_for(set(g['kinds']))}"})
        else:
            out.append({"key": "flow:other", "kind": "flow", "title": "Ảnh AI (bài viết / người mẫu)", "detail": detail,
                        "progress": None, "started_at": utc_iso(g["first"]), "link": "/history"})
    return out


@router.get("")
def running() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for source in (_dub_items, _dub_split_items, _cut_items, _dub_link_items, _clean_items, _capcut_items, _assistant_items, _autopilot_items, _flow_items, _op_items):
        try:
            items += source()
        except Exception:  # noqa: BLE001 — one broken source must not hide the others
            continue
    items.sort(key=lambda x: x.get("started_at") or "")
    return {"items": items}


#: A clip's Flow work counts as failed when a request of it failed this recently.
OUTCOME_WINDOW = timedelta(minutes=20)
_FAILED = ("failed", "timeout", "error")


@router.get("/outcome")
def outcome(key: str = Query(..., max_length=80)) -> dict[str, Any]:
    """How a task that just left :func:`running` ended, so the badge can say
    "xong" or "lỗi" instead of guessing."""
    kind, _, ident = key.partition(":")
    if kind == "op":
        from flowboard.services import op_tracker

        return op_tracker.outcome(ident) or {"ok": True, "message": "Đã xong"}
    if kind == "cut":
        from flowboard.services import video_cut

        return video_cut.outcome(ident)
    if kind == "dub":
        from flowboard.services import dub

        j = dub.JOBS.get(ident)
        if j is None:
            return {"ok": True, "message": ""}
        if j.status == "error":
            return {"ok": False, "message": j.error or "Lồng tiếng lỗi"}
        if j.status == "review":
            return {"ok": True, "message": "Đã dịch xong — chờ bạn xem lại rồi render"}
        return {"ok": True, "message": "Đã xong — bấm để xem kết quả"}
    if kind == "assistant" and ident.isdigit():
        from flowboard.services import assistant

        t = assistant.task_outcome(int(ident))
        if t and t["status"] == "error":
            return {"ok": False, "message": t["error"] or "Trợ lý gặp lỗi"}
        return {"ok": True, "message": f"{t['title']} — xong" if t else "Đã xong"}
    if kind == "autopilot" and ident.isdigit():
        from flowboard.db.models import AutoRun

        with get_session() as s:
            run = s.get(AutoRun, int(ident))
        if run is not None and run.status in ("failed", "waiting", "skipped"):
            return {"ok": False, "message": run.error or "Soạn bài tự động lỗi"}
        return {"ok": True, "message": "Bài tự động đã soạn xong, chờ tới giờ đăng"}
    if kind == "dublinks":
        return {"ok": True, "message": "Đã đưa hết link trong thư viện vào lồng tiếng"}
    if kind == "dubsplit":
        from flowboard.services import dub_split

        st = dub_split.state(ident)
        if st.get("status") == "error":
            return {"ok": False, "message": st.get("error") or "Cắt video lỗi"}
        return {"ok": True, "message": f"Đã cắt xong {st.get('done') or ''} video — bấm để xem".replace("  ", " ")}
    if kind == "clean":
        from flowboard.services import video_clean

        j = video_clean.JOBS.get(ident)
        if j is not None and j.status == "error":
            return {"ok": False, "message": j.error or "Xoá chữ lỗi"}
        return {"ok": True, "message": "Đã xong — bấm để xem kết quả"}
    if kind == "capcut":
        from flowboard.services import capcut_auto

        j = capcut_auto.JOBS.get(ident)
        if j is not None and j.status == "error":
            return {"ok": False, "message": j.error or "Tạo dự án CapCut lỗi"}
        name = ((j.result or {}).get("name") if j else None) or ""
        return {"ok": True, "message": f"Đã tạo dự án “{name}” — mở CapCut để xem" if name else "Đã xong"}
    if kind == "clip" and ident.isdigit():
        since = datetime.now(timezone.utc) - OUTCOME_WINDOW
        with get_session() as s:
            node_ids = [n.id for n in s.exec(select(Node).where(Node.board_id == int(ident))).all()]
            failed = s.exec(select(Request).where(Request.node_id.in_(node_ids), Request.status.in_(_FAILED),  # type: ignore[union-attr]
                                                  Request.type.in_(tuple(FLOW_TYPES)),  # type: ignore[union-attr]
                                                  Request.created_at >= since)).all() if node_ids else []
        if failed:
            return {"ok": False, "message": f"{len(failed)} việc Flow bị lỗi — mở clip để tạo lại"}
        return {"ok": True, "message": "Flow đã làm xong — bấm để xem"}
    return {"ok": True, "message": "Đã xong"}


@router.get("/latest")
def latest(kind: str = Query(..., max_length=40), claim: bool = False) -> dict[str, Any]:
    from flowboard.services import op_tracker

    return op_tracker.latest(kind, claim=claim) or {}
