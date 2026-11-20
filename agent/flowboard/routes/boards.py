from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import delete as sql_delete, select

from flowboard.db import get_session
from flowboard.db.models import (
    Asset,
    Board,
    BoardFlowProject,
    ChatAttachment,
    ChatMessage,
    ChatRun,
    Edge,
    Node,
    PipelineRun,
    Plan,
    PlanRevision,
    Reference,
    Request,
)
# Shared rather than re-implemented: `utc_iso` is the single place that
# knows SQLite hands datetimes back naive, and that a missing `Z` makes
# every timestamp read 7h early on a UTC+7 client. See its docstring.
from flowboard.timestamps import utc_iso
# Same reason: how request types are classified is shared with the worker
# rather than restated here. See `list_board_requests`.
from flowboard.request_types import MEDIA_PRODUCING_TYPES, SIDECAR_REQUEST_TYPES

router = APIRouter(prefix="/api/boards", tags=["boards"])

# In-flight = the statuses the worker can still move a row out of.
# `done` / `failed` / `timeout` / `canceled` are all terminal.
ACTIVE_REQUEST_STATUSES = ("queued", "running")

# ...and in-flight is not enough on its own: `vision` and `auto_prompt`
# also open a `running` Request row (services/activity.py), against a node,
# and they settle it themselves inside their own HTTP handler. They are
# never queued to the worker, so there is nothing for a resumed poll to
# wait on — and handing one to the GENERATION poll is actively
# destructive, because their result carries no `media_ids` and that poll
# reads the absence as "this node rendered nothing".
#
# So the listing is keyed by kind, not by a single "resumable" flag: a
# caller names the kinds it can actually handle, and gets nothing else.
# `MEDIA_PRODUCING_TYPES` is exactly the set the worker dispatches AND
# whose result a generation poll can act on; `SIDECAR_REQUEST_TYPES` is
# the synchronous LLM set, which needs its own much smaller poll.
RESUMABLE_REQUEST_TYPES = tuple(sorted(MEDIA_PRODUCING_TYPES))
SIDECAR_RESUMABLE_TYPES = tuple(sorted(SIDECAR_REQUEST_TYPES))

# `worker` stays the default so a caller that says nothing — including
# every caller written before sidecar resume existed — keeps getting only
# the rows a generation poll can safely act on. Opting into `sidecar` is
# a deliberate act by a caller that has somewhere to put text results.
REQUEST_KINDS: dict[str, tuple[str, ...]] = {
    "worker": RESUMABLE_REQUEST_TYPES,
    "sidecar": SIDECAR_RESUMABLE_TYPES,
}
DEFAULT_REQUEST_KINDS = "worker"


class BoardCreate(BaseModel):
    name: str
    data: Optional[dict] = None


class BoardUpdate(BaseModel):
    name: Optional[str] = None
    # Shallow-merged into Board.data; a null value removes the key.
    data: Optional[dict] = None


def _board_summary(board: Board, nodes: list[tuple]) -> dict:
    """The board row plus what the Quicktool home and "Hôm nay" need to draw
    its card: scene / clip progress, a thumbnail, failed nodes and the
    finished clip. ``nodes`` are this board's ``(type, status, data)``."""
    scenes = [(st, d) for t, st, d in nodes if t == "image"]
    clips = [(st, d) for t, st, d in nodes if t == "video"]
    exports = [d for t, _st, d in nodes if t in ("export", "merge") and (d or {}).get("mediaId")]
    thumb = next((d.get("mediaId") for t, _st, d in nodes
                  if t in ("image", "visual_asset", "Storyboard") and (d or {}).get("mediaId")), None)
    qt = (board.data or {}).get("quicktool") or {}
    return {
        "id": board.id,
        "name": board.name,
        "data": board.data or {},
        "created_at": board.created_at,
        "summary": {
            "scenes": len(scenes),
            "scenes_done": sum(1 for _st, d in scenes if (d or {}).get("mediaId")),
            "clips": len(clips),
            "clips_done": sum(1 for _st, d in clips if (d or {}).get("mediaId")),
            # Scenes / clips whose last generation failed (Flow dropped it…).
            "errors": sum(1 for st, _d in scenes + clips if st == "error"),
            "clip_errors": sum(1 for st, _d in clips if st == "error"),
            "exported": bool(exports),
            "export_media": exports[-1].get("mediaId") if exports else None,
            "downloaded_at": qt.get("downloaded_at"),
            "thumbnail": thumb,
        },
    }


@router.get("")
def list_boards(summary: bool = Query(False)):
    with get_session() as s:
        boards = s.exec(select(Board)).all()
        if summary:
            # One query for every board's nodes: per-board queries cost a
            # round trip each (~44 ms on Neon) and the library lists them all.
            by_board: dict[int, list[tuple]] = {}
            for bid, t, st, d in s.exec(select(Node.board_id, Node.type, Node.status, Node.data)).all():
                by_board.setdefault(bid, []).append((t, st, d))
            return [_board_summary(b, by_board.get(b.id, [])) for b in boards]
        return boards


@router.post("")
def create_board(body: BoardCreate):
    with get_session() as s:
        board = Board(name=body.name, data=body.data or {})
        s.add(board)
        s.commit()
        s.refresh(board)
        return board


@router.get("/{board_id}")
def get_board(board_id: int):
    with get_session() as s:
        board = s.get(Board, board_id)
        if not board:
            raise HTTPException(404, "board not found")
        nodes = s.exec(select(Node).where(Node.board_id == board_id)).all()
        edges = s.exec(select(Edge).where(Edge.board_id == board_id)).all()
        return {"board": board, "nodes": nodes, "edges": edges}


@router.get("/{board_id}/requests")
def list_board_requests(
    board_id: int,
    active: bool = Query(
        False, description="Only return in-flight (queued / running) rows"
    ),
    kinds: str = Query(
        DEFAULT_REQUEST_KINDS,
        description=(
            "Comma-separated request kinds to include when active=true: "
            "`worker` (media-producing generations) and/or `sidecar` "
            "(synchronous LLM activities). Ignored when active=false."
        ),
    ),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """Requests belonging to this board, newest first.

    Exists so a freshly-loaded board can find the work that is still in
    flight and re-attach a poll to it. The backend keeps `Node.status` and
    `Node.data` current on its own — the worker for generations, the
    service itself for the sidecar activities — but nothing tells a
    reloaded page WHICH requests are still moving, and a node parked on
    `running` (or on "Analyzing…") with nobody watching it never picks up
    its result.

    `/api/activity` answers almost the same question and is not reusable
    here: it has no board filter, so a board-scoped resume would re-attach
    polls for nodes that aren't on screen.

    `params` rides along because the frontend rebuilds the poll's options
    (prompt, aspect ratio) from it — the dispatch call that originally held
    them died with the old page.

    Requests reach a board only through their Node, so rows with a NULL
    `node_id` — standalone `proxy` / `create_project` calls, and rows
    detached by a node delete — are not board-scoped and never listed here.

    `active=true` narrows by type as well as status, to the kinds the
    caller asked for (see `REQUEST_KINDS`); `active=false` deliberately
    does not narrow at all. The full listing is a debugging view and
    should stay honest about every row the board carries, including the
    types no caller resumes (`planner`, and anything added since).

    `kinds` is validated either way, even though `active=false` ignores
    its value. A misspelled kind is a caller bug, and answering 400 says
    so; accepting it silently would let `?kinds=sidcar` look like it
    worked right up until someone set `active=true` and wondered why the
    rows they expected never arrived.
    """
    selected: list[str] = []
    for raw in kinds.split(","):
        kind = raw.strip()
        if not kind:
            continue
        if kind not in REQUEST_KINDS:
            raise HTTPException(
                400,
                f"unknown request kind {kind!r}; expected one of "
                f"{', '.join(sorted(REQUEST_KINDS))}",
            )
        selected.extend(REQUEST_KINDS[kind])
    if not selected:
        # `kinds=` / `kinds=,` is a caller bug, not a request for
        # everything. Falling back to the default keeps the unsafe
        # reading ("no filter") unreachable.
        selected = list(REQUEST_KINDS[DEFAULT_REQUEST_KINDS])

    with get_session() as s:
        if not s.get(Board, board_id):
            raise HTTPException(404, "board not found")
        # Join rather than a second query: `node_short_id` is what the
        # activity feed labels rows with, and the frontend uses it for the
        # same purpose when reporting a resumed generation.
        stmt = (
            select(Request, Node.short_id)
            .join(Node, Request.node_id == Node.id)
            .where(Node.board_id == board_id)
        )
        if active:
            stmt = stmt.where(Request.status.in_(ACTIVE_REQUEST_STATUSES))
            stmt = stmt.where(Request.type.in_(selected))
        stmt = stmt.order_by(Request.id.desc()).limit(limit)
        rows = s.exec(stmt).all()

        return {
            "items": [
                {
                    "id": req.id,
                    "type": req.type,
                    "status": req.status,
                    "node_id": req.node_id,
                    "node_short_id": short_id,
                    "created_at": utc_iso(req.created_at),
                    "params": req.params,
                }
                for req, short_id in rows
            ]
        }


@router.patch("/{board_id}")
def update_board(board_id: int, body: BoardUpdate):
    with get_session() as s:
        board = s.get(Board, board_id)
        if not board:
            raise HTTPException(404, "board not found")
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise HTTPException(400, "name must not be empty")
            board.name = name
        if body.data is not None:
            merged = dict(board.data or {})
            for key, value in body.data.items():
                if value is None:
                    merged.pop(key, None)
                elif isinstance(value, dict) and isinstance(merged.get(key), dict):
                    # One level deep: a caller that only knows `{"quicktool": {"step": 3}}`
                    # must not erase the template / product the board was made from.
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
            board.data = merged
        s.add(board)
        s.commit()
        s.refresh(board)
        return board


class ModelModeBody(BaseModel):
    mode: str  # person | hands
    gender: str = "female"
    country: str = "vn"
    vibe: str = "casual"
    hand_look: str = ""


@router.post("/{board_id}/model-mode")
def set_board_model_mode(board_id: int, body: ModelModeBody):
    """Step 1 of the wizard: show a person, or only hands. Rewrites the scene
    prompts and adds / removes the character node (see services.model_mode)."""
    from flowboard.services import model_mode

    with get_session() as s:
        if s.get(Board, board_id) is None:
            raise HTTPException(404, "board not found")
    try:
        # any product: a person or only hands is the seller's choice (no "clothes need a model" refusal since 18/11)
        return model_mode.set_model_mode(
            board_id, mode=body.mode, gender=body.gender, country=body.country,
            vibe=body.vibe, hand_look=body.hand_look[:200],
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# Node.data keys that describe a render (or an upload) rather than the
# user's intent. Clearing them leaves prompt / title / character picks /
# aspect / 60 fps toggle in place, so the board can be regenerated as-is.
_MEDIA_KEYS = (
    "mediaId", "mediaIds", "thumbnailUrl", "renderedAt", "slotErrors",
    "error", "imageModel", "videoQuality", "aiBrief", "aiBriefStatus",
    "autoPromptStatus",
)
_GENERATED_TYPES = {"image", "video", "Storyboard", "export", "merge"}
_REFERENCE_TYPES = {"character", "visual_asset"}


class ClearMediaBody(BaseModel):
    """``include_refs``: also strip character / visual-asset media (uploads
    and generated headshots). Off by default — those are usually the
    expensive-to-redo inputs, not the outputs."""
    include_refs: bool = False


@router.post("/{board_id}/clear-media")
def clear_board_media(board_id: int, body: ClearMediaBody | None = None):
    """Drop every rendered image / video on the board, keep the nodes and
    their prompts. Local only: Flow keeps its copies, the media cache is
    untouched (the ids simply stop being referenced)."""
    include_refs = bool(body and body.include_refs)
    types = _GENERATED_TYPES | (_REFERENCE_TYPES if include_refs else set())
    cleared = 0
    with get_session() as s:
        if not s.get(Board, board_id):
            raise HTTPException(404, "board not found")
        for node in s.exec(select(Node).where(Node.board_id == board_id)).all():
            if node.type not in types:
                continue
            data = dict(node.data or {})
            if not any(k in data for k in _MEDIA_KEYS) and node.status == "idle":
                continue
            for k in _MEDIA_KEYS:
                data.pop(k, None)
            node.data = data
            node.status = "idle"
            s.add(node)
            cleared += 1
        # A pinned variant points at media that no longer exists on the node.
        node_ids = [n.id for n in s.exec(select(Node).where(Node.board_id == board_id)).all()]
        for edge in s.exec(select(Edge).where(Edge.board_id == board_id)).all():
            if edge.source_variant_idx is not None and edge.source_id in node_ids:
                edge.source_variant_idx = None
                s.add(edge)
        s.commit()
    return {"board_id": board_id, "cleared": cleared, "include_refs": include_refs}


@router.delete("/{board_id}")
def delete_board(board_id: int):
    """Cascade-delete a board and everything that hangs off it.

    SQLite enforces FK constraints, so we have to clear children before
    the parent. Order:
      Asset(node_id) → Request(node_id) → Node
      PipelineRun(plan_id) → PlanRevision(plan_id) → Plan
      Edge → ChatRun / ChatAttachment → ChatMessage → BoardFlowProject → Board.
    A saved Reference is cross-board by design, so it survives: only its
    ``source_board_id`` is cleared (it was a FK to this board and made the
    delete fail with 500 once anything had been ★ Saved).

    Note: this only removes the *local* mapping to a Google Flow project.
    The Flow project itself is NOT deleted — Flow exposes no delete-project
    RPC on the transport we use. Since the September 2026 migration it also
    exposes no create-project RPC, so boards share one pinned Flow project
    and deleting it by hand in the Flow UI would affect every board.
    """
    with get_session() as s:
        board = s.get(Board, board_id)
        if not board:
            raise HTTPException(404, "board not found")

        # Children-of-children first.
        node_ids = [
            n.id for n in s.exec(select(Node).where(Node.board_id == board_id)).all()
        ]
        if node_ids:
            s.exec(sql_delete(Asset).where(Asset.node_id.in_(node_ids)))
            s.exec(sql_delete(Request).where(Request.node_id.in_(node_ids)))

        plan_ids = [
            p.id for p in s.exec(select(Plan).where(Plan.board_id == board_id)).all()
        ]
        if plan_ids:
            s.exec(sql_delete(PipelineRun).where(PipelineRun.plan_id.in_(plan_ids)))
            s.exec(sql_delete(PlanRevision).where(PlanRevision.plan_id.in_(plan_ids)))

        # Edge has FK on Node (source_id, target_id) — must clear before Node.
        s.exec(sql_delete(Edge).where(Edge.board_id == board_id))
        s.exec(sql_delete(Node).where(Node.board_id == board_id))
        s.exec(sql_delete(Plan).where(Plan.board_id == board_id))
        message_ids = [
            m.id for m in s.exec(
                select(ChatMessage).where(ChatMessage.board_id == board_id)
            ).all()
        ]
        if message_ids:
            s.exec(sql_delete(ChatAttachment).where(ChatAttachment.message_id.in_(message_ids)))
        s.exec(sql_delete(ChatRun).where(ChatRun.board_id == board_id))
        s.exec(sql_delete(ChatMessage).where(ChatMessage.board_id == board_id))
        for ref in s.exec(select(Reference).where(Reference.source_board_id == board_id)).all():
            ref.source_board_id = None
            s.add(ref)
        s.exec(sql_delete(BoardFlowProject).where(BoardFlowProject.board_id == board_id))
        s.delete(board)
        s.commit()
        return {"deleted": board_id}
