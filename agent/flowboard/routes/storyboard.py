"""Cut a rendered Storyboard composite into scene nodes.

``POST /api/nodes/{node_id}/storyboard/split`` reads the node's composite
(rows × cols tiles, see ``services/storyboard_split.py``), uploads every
tile to the board's Flow project as its own image, and lands one
``image`` + one ``video`` node per tile on the board in a single
``build_board`` call: storyboard → scene i → video i. The nodes that fed
the storyboard (the model, the product) are wired into every video too,
so the clips keep them as ingredients.

Uploads are images, which Flow does not charge for. They run one after
another: Flow's uploadImage goes through the extension and is happier
with a serial stream than a burst.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import BoardFlowProject, Edge, Node
from flowboard.routes import upload as upload_route
from flowboard.services import media as media_service
from flowboard.services.activity import record_activity
from flowboard.services.board_builder import BoardSpecError, build_board
from flowboard.services.flow_project import effective_project_id
from flowboard.services.storyboard_split import split_composite

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nodes", tags=["storyboard"])

# Node types whose edge into the storyboard means "this is an ingredient"
# — carried over to the per-scene videos.
_INGREDIENT_TYPES = ("character", "visual_asset")


def resolve_layout(grid: object, aspect_ratio: object) -> tuple[int, int]:
    """``(rows, cols)`` the composite was rendered with — the Python twin of
    ``resolveStoryboardLayout`` in ``frontend/src/lib/storyboardPrompt.ts``.
    Unknown / legacy grid values fall back to 2x2, like the frontend."""
    g = grid if grid in ("2x2", "2x3", "2x4") else "2x2"
    if g == "2x2":
        return 2, 2
    big = 3 if g == "2x3" else 4
    portrait = isinstance(aspect_ratio, str) and "PORTRAIT" in aspect_ratio
    return (big, 2) if portrait else (2, big)


def _flow_project_id(board_id: int) -> str:
    """The board's bound Flow project, else the pinned one (same resolution
    as the chat agent's uploads)."""
    with get_session() as s:
        row = s.get(BoardFlowProject, board_id)
    return (row.flow_project_id if row is not None else "") or effective_project_id()


@router.post("/{node_id}/storyboard/split")
async def split_storyboard(node_id: int) -> dict:
    with get_session() as s:
        node = s.get(Node, node_id)
        if node is None:
            raise HTTPException(404, "node not found")
        if node.type != "Storyboard":
            raise HTTPException(400, "node is not a Storyboard")
        data = node.data or {}
        media_id = data.get("mediaId")
        if not isinstance(media_id, str) or not media_service.is_valid_media_id(media_id):
            raise HTTPException(400, "storyboard has no rendered composite yet")
        board_id, sb_short = node.board_id, node.short_id
        feeders = [
            src.short_id
            for src, _e in s.exec(
                select(Node, Edge)
                .join(Edge, Edge.source_id == Node.id)
                .where(Edge.target_id == node.id, Node.type.in_(_INGREDIENT_TYPES))
            ).all()
        ]
    rows, cols = resolve_layout(data.get("storyboardGrid"), data.get("aspectRatio"))

    project_id = _flow_project_id(board_id)
    if not project_id:
        raise HTTPException(
            400,
            "no Flow project pinned — Settings → Google Flow project, or "
            "FLOWBOARD_FLOW_PROJECT_ID in .env",
        )

    async with record_activity(
        "storyboard_split",
        params={"media_id": media_id, "rows": rows, "cols": cols},
        node_id=node_id,
    ) as activity:
        path = media_service.cached_path(media_id)
        if path is None:
            fetched = await media_service.fetch_and_cache(media_id)
            if fetched is None:
                raise HTTPException(502, "composite not cached and could not be fetched")
            path = fetched[2]

        try:
            panels = await asyncio.to_thread(split_composite, path, rows, cols)
        except Exception as exc:  # noqa: BLE001 — unreadable / truncated file
            raise HTTPException(500, f"could not cut composite: {exc}") from exc

        nodes: list[dict] = []
        edges: list[list[str]] = []
        for i, raw in enumerate(panels, start=1):
            # Module attribute lookup on purpose: tests monkeypatch
            # `routes.upload._ingest_image_bytes` to skip the extension.
            try:
                out = await upload_route._ingest_image_bytes(
                    raw, "image/png", project_id, f"scene{i}.png", None
                )
            except Exception as exc:  # noqa: BLE001 — HTTPException or SDK error
                detail = getattr(exc, "detail", None)
                msg = detail.get("message") if isinstance(detail, dict) else str(detail or exc)
                raise HTTPException(502, f"upload of scene {i} to Flow failed: {msg}") from exc
            mid = out["media_id"]
            dims = upload_route._sniff_image_dimensions(raw) or (0, 0)
            nodes.append({
                "key": f"s{i}", "type": "image", "status": "done",
                "data": {
                    "title": f"Cảnh {i}",
                    "mediaId": mid, "mediaIds": [mid], "variantCount": 1,
                    "aspectRatio": upload_route._classify_aspect(*dims),
                    "fromStoryboard": sb_short, "panelIndex": i,
                },
            })
            nodes.append({
                "key": f"v{i}", "type": "video",
                "data": {"title": f"Video {i}", "prompt": ""},
            })
            edges.append([f"#{sb_short}", f"s{i}"])
            edges.append([f"s{i}", f"v{i}"])
            for feeder in feeders:
                edges.append([f"#{feeder}", f"v{i}"])

        try:
            created = build_board(board_id, {"nodes": nodes, "edges": edges})
        except BoardSpecError as exc:
            raise HTTPException(409, str(exc)) from exc

        result = {
            "storyboard": sb_short,
            "panels": len(panels),
            "rows": rows,
            "cols": cols,
            "nodes": created,
        }
        activity.set_result(result)
    return result
