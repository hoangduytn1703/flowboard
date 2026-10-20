"""Server-side ReAct agent for the bottom-dock chat (E2E video builder).

``POST /api/chat`` persists the user message and schedules
:func:`run_chat_agent` as a FastAPI BackgroundTask. The loop runs HERE,
not in the worker. Reasoning goes through the provider pinned for the
**Planner** feature in Settings → AI Providers (``run_llm("planner")``);
image / video tools enqueue the same ``gen_image`` / ``gen_video``
Requests the Generate button does, so they render on Google Flow through
the worker and the extension, and ffmpeg joins clips locally.

:func:`run_chat_agent` never raises — any failure marks the ChatRun
``failed`` and writes an assistant message carrying the error.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple, Optional

from sqlmodel import select

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
    Request,
)
from flowboard.services import media as media_service
from flowboard.services import video_concat
from flowboard.services.activity import record_activity
from flowboard.services.board_builder import BoardSpecError, build_board
from flowboard.services.flow_project import effective_project_id
from flowboard.services.products import TemplateBuildError, list_products, template_board_spec
from flowboard.services.templates import PersonRequiredError
from flowboard.services.llm.base import LLMError
from flowboard.services.llm.registry import run_llm
from flowboard.short_id import generate_unique_short_id

logger = logging.getLogger(__name__)

MAX_TURNS = 12
_LLM_TIMEOUT_S = 120.0
# One Flow render through the worker: an image lands in ~30 s, a video
# polls for up to 5 min inside the handler, plus queue time behind other
# requests (the worker is single-consumer).
_MEDIA_TIMEOUT_S = 900.0
_MEDIA_POLL_S = 2.0
_TERMINAL = ("done", "failed", "timeout", "canceled")

_IMAGE_ASPECTS = {
    "portrait": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "landscape": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "square": "IMAGE_ASPECT_RATIO_SQUARE",
}
_VIDEO_ASPECTS = {
    "portrait": "VIDEO_ASPECT_RATIO_PORTRAIT",
    "landscape": "VIDEO_ASPECT_RATIO_LANDSCAPE",
}
_VIDEO_QUALITIES = ("lite", "fast", "quality", "lite_relaxed", "fast_relaxed")

_NODE_TYPES = {"character", "visual_asset", "image", "video", "prompt", "note", "merge", "export"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChatAgentError(Exception):
    """Expected tool failure — fed back to the LLM as an observation."""


class ToolCall(NamedTuple):
    tool: str = ""
    args: dict = {}
    done: bool = False
    reply: str = ""


# ── system prompt ─────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are the Flowboard build agent. You do not execute anything
yourself: you answer with JSON tool calls, and the Flowboard server runs
them on an infinite canvas (nodes for the model, the product, scene images,
videos; edges = "use as reference").

RULES
- Respond with EXACTLY ONE JSON object per turn, no prose outside it.
- Either a tool call: {"tool": "<name>", "args": {...}}
- Or finish: {"done": true, "reply": "<summary for the user>"}
- The reply must be in the same language as the user's message.
- DEFAULT IS DRAFT MODE. Build the board — nodes with titles and prompts,
  wired with edges — and stop. The user reviews the prompts and presses
  Generate on each node themselves. Do NOT call gen_image, gen_video or
  concat_videos unless the user explicitly asks you to render now
  ("tạo ảnh luôn", "render luôn", "gen luôn", "làm video luôn", "generate").
  Rendering spends the user's Google Flow credits.
- Build a whole board in ONE build_board call; only use create_node /
  add_edge / update_node for small follow-up edits.
- Prefer reusing existing nodes on follow-up turns ("sửa", "đổi prompt"):
  update_node their data instead of creating duplicates.
- If a tool returns an error, adapt (fix args, try another tool) instead
  of repeating the identical call.

NODE DATA (what the Generate button reads)
- character (the model): {"title": "...", "charGender": "male|female",
  "charCountry": "vn|jp|kr|cn|th|us|fr", "charVibe":
  "clean|douyin|oldmoney|coldgirl|kpop|casual", "charExtras": "English,
  <=200 chars: hair, face, age, expression — no clothing"}
- visual_asset (the product): {"title": "Sản phẩm — upload ảnh thật"}.
  Leave it empty for the user to upload the real product photo; only add a
  "prompt" if the user wants the product generated.
- image (one per scene): {"title": "Cảnh 1 - ...", "prompt": "English,
  <=500 chars: shot size + action + setting + lighting + camera. Refer to
  'the model' and 'the product shown in the reference photo' (never name
  a product type the user did not give — it may be clothing, food, a
  gadget, cosmetics) — never re-describe their looks,
  the reference nodes carry that."}
- video (one per scene image): {"title": "...", "prompt": "English motion
  for 8 s in 2-3 beats (e.g. 0-3s / 3-6s / 6-8s). Locked-off camera unless
  the user asks for movement. Natural real-time pace — do not write
  'slowly' / 'slow motion' unless the user asks for a slow-motion effect."}
- note (the script): {"title": "Kịch bản", "prompt": "<the script, in the
  user's language>"}
- Edges: every reference (character, product) → every scene image; each
  scene image → exactly ONE video (a video uses only its first image).

TOOLS
- build_from_template: {"product_id": 3 (optional: a saved product from
  "Saved products"), "template_id": "fashion_ad|cosmetics_ad|fast_food_ad|food_review|grocery_ad|home_appliance_review|affiliate_reel|
  unboxing_review" (optional when product_id is given — the product's
  category picks it), "inputs": {"setting": "English scene setting",
  "charGender": "female|male", "charCountry": "vn|kr|jp|cn|th|us|fr"}
  (optional)}  Builds a ready-made ad flow on this board. With a product,
  its real photo(s) are already on the product node and its description
  is in every scene prompt, so the user can Generate right away.
  → {"ok": true, "nodes": {"product": "abcd", "s1": ...}}
- build_board: {"nodes": [{"key": "model", "type": "character",
  "data": {...}}, {"key": "s1", "type": "image", "data": {...}}, ...],
  "edges": [["model", "s1"], ["product", "s1"], ["s1", "v1"], ...]}
  Creates every node and edge at once and lays them out left to right
  (references → scene images → videos). An edge end may also be an
  existing node as "#abcd". → {"ok": true, "nodes": {"model": "abcd", ...}}
- create_node: {"type": "character|visual_asset|image|video|prompt|note|merge",
  "x": float, "y": float, "data": {optional dict}}
  → {"ok": true, "short_id": "abcd", "id": 7}
- add_edge: {"from_short_id": "abcd", "to_short_id": "efgh",
  "kind": "ref"}  (kind: "ref" = use as reference)
- gen_image: {"prompt": "... (English, visual)",
  "node_short_id": "abcd" (optional: render into this image node),
  "reference_node_short_ids": ["ab12", "cd34"] (optional: character /
  visual_asset / image nodes whose media is used as reference, e.g. to
  keep the same person and the same product),
  "reference_asset_ids": [1, 2] (optional: images attached to the chat),
  "aspect": "portrait|landscape|square" (optional, default portrait)}
  Renders on Google Flow (~30 s) and binds the image to the node
  (creates an image node if none given). Returns media_ids.
- gen_video: {"prompt": "... (English: motion, camera, lighting)",
  "source_node_short_id": "abcd" (an image node with media — its first
  image is the start frame) OR "source_asset_id": 3 (an attached image),
  "node_short_id": "efgh" (optional), "aspect": "portrait|landscape"
  (optional, default portrait), "model": "omni_flash|veo" (optional,
  default omni_flash — Veo is currently dropped by Flow on most
  accounts), "duration_s": 4|6|8|10 (Omni only, default 8),
  "quality": "lite|fast|quality" (Veo only, default lite)}
  Renders an 8 s clip on Google Flow (1-5 min) and binds it to a video
  node. Each call spends the user's Flow credits, so do not repeat one
  that succeeded.
- concat_videos: {"video_node_short_ids": ["ab12", "cd34"] (video nodes
  with media, in order) OR "video_asset_ids": [4, 5],
  "node_short_id": "abcd" (optional)}  Joins clips with ffmpeg; binds the
  result to a video node (created if none given).
- update_node: {"short_id": "abcd", "data_patch": {...}}  Shallow-merges
  data (a null value deletes the key).
- refresh: {}  Re-reads the board (nodes/edges) after many mutations.

When the user names an item from "Saved products" (or says "sản phẩm
#3"), use build_from_template with its product_id, then update_node the
scene prompts only if the user asked for a different story. A custom
build_board does not carry the product's photos.

Typical ad request ("tạo kịch bản quảng cáo …"): ONE build_board call
with a note (the script), a character, a visual_asset (product), 3-4
scene images and one video per image, edges as above → done, with a
reply that lists the scenes and says what to press: upload the product
photo, Generate the character, then each scene image, then each video.
Only when asked to render: gen_image per scene with
reference_node_short_ids=[model, product], then gen_video per image with
source_node_short_id, then concat_videos in order. Never re-render media
that already exists.
"""


# ── context builder ───────────────────────────────────────────────────

def _summarize_data(data: Optional[dict]) -> str:
    if not data:
        return ""
    bits: list[str] = []
    prompt = data.get("prompt")
    if isinstance(prompt, str) and prompt:
        bits.append(f"prompt={prompt[:120]!r}")
    mids = data.get("mediaIds")
    if isinstance(mids, list):
        bits.append(f"media={len(mids)}")
    title = data.get("title")
    if isinstance(title, str) and title:
        bits.append(f"title={title[:60]!r}")
    return " ".join(bits)


def build_board_context(
    board_id: int,
    message: str,
    attachment_asset_ids: list[int],
    mentions: list[str],
) -> str:
    """Static per-run context: history + current request + attachments."""
    with get_session() as s:
        board = s.get(Board, board_id)
        hist = s.exec(
            select(ChatMessage)
            .where(ChatMessage.board_id == board_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(20)
        ).all()
        hist = list(reversed(hist))
        att_counts: dict[int, int] = {}
        if hist:
            rows = s.exec(
                select(ChatAttachment).where(
                    ChatAttachment.message_id.in_([m.id for m in hist if m.id])
                )
            ).all()
            for r in rows:
                att_counts[r.message_id] = att_counts.get(r.message_id, 0) + 1
        nodes = s.exec(select(Node).where(Node.board_id == board_id)).all()
        node_by_short = {n.short_id: n for n in nodes}

    lines = [f"# Board: {board.name if board else board_id} (id={board_id})"]
    lines.append("## Recent chat (oldest → newest)")
    if not hist:
        lines.append("(no previous messages)")
    for m in hist:
        content = (m.content or "")[:600]
        suffix = ""
        n_att = att_counts.get(m.id or -1, 0)
        if n_att:
            suffix = f" [{n_att} image(s) attached]"
        lines.append(f"[{m.role}] {content}{suffix}")
    if mentions:
        lines.append("## Mentions")
        for men in mentions:
            n = node_by_short.get(men)
            if n is not None:
                lines.append(f"#{men} → {n.type} node {_summarize_data(n.data)}")
            else:
                lines.append(f"#{men} → (unknown node)")
    lines.append("## Current request")
    lines.append(message)
    if attachment_asset_ids:
        with get_session() as s:
            paths = []
            for aid in attachment_asset_ids:
                row = s.get(Asset, aid)
                if row is not None and row.local_path:
                    paths.append(f"asset {aid}: {row.local_path}")
        lines.append(
            "Attached images (asset id → absolute path, readable by your tools):\n"
            + "\n".join(paths)
        )
    lines.append(_products_context())
    lines.append(_dynamic_context(board_id))
    return "\n".join(lines)


def _products_context() -> str:
    """The product library, so "làm clip cho áo thun" can find the item."""
    lines = ["## Saved products (use with build_from_template)"]
    products = list_products(limit=30)
    if not products:
        lines.append("(none saved)")
    for p in products:
        points = "; ".join(x.strip(" -•\t") for x in p["selling_points"].splitlines() if x.strip())
        lines.append(
            f"product_id={p['id']} {p['name']!r} [{p['category']}]"
            + (f" price={p['price']!r}" if p["price"] else "")
            + f" photos={len(p['media_ids'])}"
            + (f" description={p['description'][:160]!r}" if p["description"] else "")
            + (f" selling_points={points[:200]!r}" if points else "")
        )
    return "\n".join(lines)


def _dynamic_context(board_id: int) -> str:
    """Fresh nodes/edges snapshot — rebuilt every turn."""
    with get_session() as s:
        nodes = s.exec(
            select(Node).where(Node.board_id == board_id).order_by(Node.id)
        ).all()
        edges = s.exec(
            select(Edge).where(Edge.board_id == board_id).order_by(Edge.id)
        ).all()
        by_id = {n.id: n for n in nodes}
    lines = ["## Nodes"]
    if not nodes:
        lines.append("(board is empty)")
    for n in nodes:
        lines.append(
            f"#{n.short_id} [{n.type}] status={n.status} "
            f"@({n.x:.0f},{n.y:.0f}) {_summarize_data(n.data)}".rstrip()
        )
    lines.append("## Edges")
    for e in edges:
        a = by_id.get(e.source_id)
        b = by_id.get(e.target_id)
        if a and b:
            lines.append(f"#{a.short_id} -> #{b.short_id} ({e.kind})")
    return "\n".join(lines)


# ── LLM call ──────────────────────────────────────────────────────────

async def _chat_llm(
    user_prompt: str,
    attachments: Optional[list[str]],
    turn: int,
) -> str:
    """The chat thinks with its own pin (Settings → AI Providers → Chat AI,
    or the picker on the dock), else with the Planner's.

    The planner is the fallback because it is the closest sibling — it
    writes pipeline plans for the same canvas — and because Chat AI is
    optional: an install configured before the row existed keeps working."""
    for feature in ("chat_agent", "planner"):
        try:
            return await run_llm(
                feature,
                user_prompt,
                system_prompt=_SYSTEM_PROMPT,
                attachments=attachments,
                timeout=_LLM_TIMEOUT_S,
            )
        except LLMError as exc:
            if f"No AI provider configured for {feature}" not in str(exc):
                raise
    raise LLMError(
        "Chưa chọn AI provider cho Chat AI / Planner — bấm chip provider trên "
        "khung chat, hoặc mở 🤖 Setup AI (Settings → AI Providers), rồi gửi lại."
    )


# ── tool-call parsing ─────────────────────────────────────────────────

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _parse_tool_call(raw: str) -> Optional[ToolCall]:
    text = (raw or "").strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    obj: Any = None
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                obj = json.loads(text[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                return None
        else:
            return None
    if not isinstance(obj, dict):
        return None
    if obj.get("done") is True:
        reply = obj.get("reply", "")
        return ToolCall(done=True, reply=reply if isinstance(reply, str) else "")
    tool = obj.get("tool")
    args = obj.get("args", {})
    if not isinstance(tool, str) or not tool or not isinstance(args, dict):
        return None
    return ToolCall(tool=tool, args=args)


# ── tool implementations ──────────────────────────────────────────────

def _node_by_short(s, board_id: int, short_id: str) -> Optional[Node]:
    return s.exec(
        select(Node).where(Node.board_id == board_id, Node.short_id == short_id)
    ).first()


def _auto_pos(s, board_id: int) -> tuple[float, float]:
    nodes = s.exec(select(Node).where(Node.board_id == board_id)).all()
    if not nodes:
        return 0.0, 0.0
    return max(n.x for n in nodes) + 300.0, 0.0


def _bind_media(node_id: int, media_ids: list[str]) -> None:
    """Mirror the pipeline executor's binding: data.mediaIds + mediaId,
    status → done."""
    with get_session() as s:
        node = s.get(Node, node_id)
        if node is None:
            return
        data = dict(node.data or {})
        existing = data.get("mediaIds")
        merged = list(existing) if isinstance(existing, list) else []
        for mid in media_ids:
            if mid and mid not in merged:
                merged.append(mid)
        data["mediaIds"] = merged
        if merged:
            data["mediaId"] = merged[0]
        node.data = data
        node.status = "done"
        s.add(node)
        s.commit()


def _get_or_create_media_node(
    s, board_id: int, short_id: Optional[str], node_type: str, prompt: str
) -> Node:
    if short_id:
        node = _node_by_short(s, board_id, short_id)
        if node is None:
            raise ChatAgentError(f"node #{short_id} not found on this board")
        return node
    x, y = _auto_pos(s, board_id)
    node = Node(
        board_id=board_id,
        short_id=generate_unique_short_id(s, board_id),
        type=node_type,
        x=x,
        y=y,
        data={"prompt": prompt} if prompt else {},
        status="idle",
    )
    s.add(node)
    s.commit()
    s.refresh(node)
    return node


# ── Flow dispatch ─────────────────────────────────────────────────────
#
# The tools below render exactly the way the Generate button does: a
# Request row the worker picks up, so the node shows "running", the
# worker mirrors the result onto Node.data when it lands, and the
# activity feed shows the render.

def _flow_project_id(board_id: int) -> str:
    with get_session() as s:
        row = s.get(BoardFlowProject, board_id)
    pid = row.flow_project_id if row is not None else effective_project_id()
    if not pid:
        raise ChatAgentError(
            "no Flow project pinned — Settings → Google Flow project, or "
            "FLOWBOARD_FLOW_PROJECT_ID in .env"
        )
    return pid


def _node_media_id(s, board_id: int, short_id: str, *, want: str) -> str:
    node = _node_by_short(s, board_id, short_id)
    if node is None:
        raise ChatAgentError(f"node #{short_id} not found on this board")
    mid = (node.data or {}).get("mediaId")
    if not isinstance(mid, str) or not mid:
        raise ChatAgentError(f"node #{short_id} has no {want} yet — generate it first")
    return mid


async def _attachment_to_flow(asset_id: int, project_id: str) -> str:
    """A chat attachment is a local file with a made-up id; Flow can only
    reference media inside the project, so upload it (images are free)."""
    with get_session() as s:
        row = s.get(Asset, asset_id)
        if row is None:
            raise ChatAgentError(f"asset {asset_id} not found")
        if (row.kind or "") != "image":
            raise ChatAgentError(f"asset {asset_id} is not an image")
        if row.uuid_media_id and media_service.is_valid_media_id(row.uuid_media_id):
            return row.uuid_media_id  # already a Flow media id
        path = Path(row.local_path) if row.local_path else None
        mime = row.mime or "image/png"
    if path is None or not path.is_file():
        raise ChatAgentError(f"asset {asset_id} has no local file")
    from flowboard.routes.upload import _ingest_image_bytes  # late: route module

    try:
        out = await _ingest_image_bytes(path.read_bytes(), mime, project_id, path.name, None)
    except Exception as exc:  # noqa: BLE001 — HTTPException or SDK error
        detail = getattr(exc, "detail", None)
        msg = detail.get("message") if isinstance(detail, dict) else str(exc)
        raise ChatAgentError(f"upload of asset {asset_id} to Flow failed: {msg}") from exc
    return out["media_id"]


def _stamp_running(node_id: int) -> None:
    with get_session() as s:
        node = s.get(Node, node_id)
        if node is not None:
            node.status = "running"
            s.add(node)
            s.commit()


async def _dispatch_flow(node_id: int, req_type: str, params: dict) -> list[str]:
    """Enqueue a worker Request for ``node_id`` and wait for it to settle.

    The worker writes the media onto the node itself (``_node_completion_patch``),
    so on success only the media ids come back. Raises ChatAgentError with
    the worker's error on failure, timeout or cancel."""
    from flowboard.worker.processor import get_worker  # late: avoids an import cycle

    _stamp_running(node_id)
    with get_session() as s:
        req = Request(node_id=node_id, type=req_type, params=dict(params), status="queued")
        s.add(req)
        s.commit()
        s.refresh(req)
        rid = req.id
    get_worker().enqueue(rid)

    waited = 0.0
    while waited < _MEDIA_TIMEOUT_S:
        await asyncio.sleep(_MEDIA_POLL_S)
        waited += _MEDIA_POLL_S
        with get_session() as s:
            row = s.get(Request, rid)
            if row is None:
                raise ChatAgentError(f"request {rid} disappeared")
            if row.status in _TERMINAL:
                status, error, result = row.status, row.error, dict(row.result or {})
                break
    else:
        raise ChatAgentError(
            f"{req_type} request {rid} still running after {int(_MEDIA_TIMEOUT_S)}s"
        )
    if status != "done":
        raise ChatAgentError(f"{req_type} {status}: {error or 'unknown error'}")
    media_ids = [m for m in (result.get("media_ids") or []) if isinstance(m, str) and m]
    if not media_ids:
        raise ChatAgentError(f"{req_type} returned no media")
    return media_ids


def _aspect(args: dict, table: dict, default: str) -> str:
    key = str(args.get("aspect") or default).strip().lower()
    if key not in table:
        raise ChatAgentError(f"aspect must be one of {sorted(table)}")
    return table[key]


async def _tool_create_node(board_id: int, args: dict) -> dict:
    ntype = args.get("type")
    if ntype not in _NODE_TYPES:
        raise ChatAgentError(
            f"unknown node type {ntype!r}; valid: {sorted(_NODE_TYPES)}"
        )
    data = args.get("data") or {}
    if not isinstance(data, dict):
        raise ChatAgentError("data must be an object")
    try:
        x = float(args.get("x", 0.0))
        y = float(args.get("y", 0.0))
    except (TypeError, ValueError):
        raise ChatAgentError("x/y must be numbers")
    with get_session() as s:
        if "x" not in args or "y" not in args:
            x, y = _auto_pos(s, board_id)
        node = Node(
            board_id=board_id,
            short_id=generate_unique_short_id(s, board_id),
            type=ntype,
            x=x,
            y=y,
            data=data,
            status="idle",
        )
        s.add(node)
        s.commit()
        s.refresh(node)
        return {
            "ok": True,
            "tool": "create_node",
            "id": node.id,
            "short_id": node.short_id,
            "type": ntype,
        }


async def _tool_build_board(board_id: int, args: dict) -> dict:
    """Create a set of nodes and the edges between them in one call.

    A board for one ad is ~8 nodes and ~9 edges; one tool call each would
    blow through MAX_TURNS before the agent could reply. The layout and
    validation live in services/board_builder, shared with the template
    route."""
    try:
        created = build_board(board_id, args)
    except BoardSpecError as exc:
        raise ChatAgentError(str(exc)) from exc
    return {"ok": True, "tool": "build_board", "nodes": created,
            "edges": len(args.get("edges") or [])}


async def _tool_build_from_template(board_id: int, args: dict) -> dict:
    """A shipped ad template on this board, optionally made for a saved
    product — the same spec ``POST /api/boards/from-template`` builds."""
    product_id = args.get("product_id")
    if product_id is not None:
        try:
            product_id = int(product_id)
        except (TypeError, ValueError) as exc:
            raise ChatAgentError(f"product_id must be an integer, got {product_id!r}") from exc
    inputs = args.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ChatAgentError("inputs must be an object")
    try:
        template, spec, product = template_board_spec(
            args.get("template_id"), {str(k): str(v) for k, v in inputs.items()}, product_id
        )
        created = build_board(board_id, spec)
    except (TemplateBuildError, BoardSpecError, PersonRequiredError) as exc:
        raise ChatAgentError(str(exc)) from exc
    return {"ok": True, "tool": "build_from_template", "template_id": template["id"],
            "product": product["name"] if product else None, "nodes": created}


async def _tool_add_edge(board_id: int, args: dict) -> dict:
    from_sid = args.get("from_short_id")
    to_sid = args.get("to_short_id")
    kind = args.get("kind", "ref")
    if not from_sid or not to_sid:
        raise ChatAgentError("from_short_id and to_short_id are required")
    with get_session() as s:
        a = _node_by_short(s, board_id, from_sid)
        b = _node_by_short(s, board_id, to_sid)
        if a is None:
            raise ChatAgentError(f"node #{from_sid} not found")
        if b is None:
            raise ChatAgentError(f"node #{to_sid} not found")
        edge = Edge(board_id=board_id, source_id=a.id, target_id=b.id, kind=kind)
        s.add(edge)
        s.commit()
        s.refresh(edge)
        return {
            "ok": True,
            "tool": "add_edge",
            "id": edge.id,
            "from": from_sid,
            "to": to_sid,
        }


async def _tool_gen_image(board_id: int, args: dict) -> dict:
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ChatAgentError("prompt is required")
    ref_shorts = args.get("reference_node_short_ids") or []
    ref_ids = args.get("reference_asset_ids") or []
    if not isinstance(ref_shorts, list) or not isinstance(ref_ids, list):
        raise ChatAgentError("reference_node_short_ids / reference_asset_ids must be lists")
    project_id = _flow_project_id(board_id)
    aspect = _aspect(args, _IMAGE_ASPECTS, "portrait")
    with get_session() as s:
        ref_mids = [_node_media_id(s, board_id, str(sid), want="image") for sid in ref_shorts]
    for aid in ref_ids:
        ref_mids.append(await _attachment_to_flow(int(aid), project_id))
    with get_session() as s:
        node = _get_or_create_media_node(
            s, board_id, args.get("node_short_id"), "image", prompt
        )
        node_id, short_id = node.id, node.short_id
    params: dict[str, Any] = {
        "prompt": prompt.strip(),
        "project_id": project_id,
        "aspect_ratio": aspect,
        "variant_count": 1,
    }
    if ref_mids:
        params["ref_media_ids"] = list(dict.fromkeys(ref_mids))
    out = await _dispatch_flow(node_id, "gen_image", params)
    _bind_media(node_id, out)  # the worker patches the node too; this never relies on it
    return {
        "ok": True,
        "tool": "gen_image",
        "node_short_id": short_id,
        "media_ids": out,
    }


async def _tool_gen_video(board_id: int, args: dict) -> dict:
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ChatAgentError("prompt is required")
    project_id = _flow_project_id(board_id)
    source_short = args.get("source_node_short_id")
    source_aid = args.get("source_asset_id")
    if source_short:
        with get_session() as s:
            src_mid = _node_media_id(s, board_id, str(source_short), want="image")
    elif source_aid is not None:
        src_mid = await _attachment_to_flow(int(source_aid), project_id)
    else:
        raise ChatAgentError(
            "source_node_short_id (an image node) or source_asset_id is required"
        )
    aspect = _aspect(args, _VIDEO_ASPECTS, "portrait")
    # Omni Flash unless Veo is asked for by name: Veo Lite is accepted and
    # then dropped on ordinary accounts (BUGLOG FB-025).
    model = str(args.get("model") or "omni_flash").strip().lower()
    if model not in ("omni_flash", "veo"):
        raise ChatAgentError("model must be omni_flash or veo")
    quality = str(args.get("quality") or "lite").strip().lower()
    if quality not in _VIDEO_QUALITIES:
        raise ChatAgentError(f"quality must be one of {_VIDEO_QUALITIES}")
    duration = args.get("duration_s", 8)
    if duration not in (4, 6, 8, 10):
        raise ChatAgentError("duration_s must be 4, 6, 8 or 10")
    with get_session() as s:
        node = _get_or_create_media_node(
            s, board_id, args.get("node_short_id"), "video", prompt
        )
        node_id, short_id = node.id, node.short_id
    params: dict[str, Any] = {
        "prompt": prompt.strip(),
        "project_id": project_id,
        "aspect_ratio": aspect,
    }
    if model == "omni_flash":
        params["ref_media_ids"] = [src_mid]
        params["duration_s"] = duration
        out = await _dispatch_flow(node_id, "gen_video_omni", params)
    else:
        params["start_media_id"] = src_mid
        params["video_quality"] = quality
        out = await _dispatch_flow(node_id, "gen_video", params)
    _bind_media(node_id, out)
    return {
        "ok": True,
        "tool": "gen_video",
        "node_short_id": short_id,
        "media_ids": out,
    }


async def _tool_concat_videos(board_id: int, args: dict) -> dict:
    shorts = args.get("video_node_short_ids") or []
    aids = list(args.get("video_asset_ids") or [])
    if not isinstance(shorts, list) or not isinstance(aids, list):
        raise ChatAgentError("video_node_short_ids / video_asset_ids must be lists")
    for sid in shorts:
        with get_session() as s:
            mid = _node_media_id(s, board_id, str(sid), want="video")
        # A Flow render is only a signed URL until something fetches it;
        # ffmpeg needs the file, so pull it into the cache now.
        if media_service.cached_path(mid) is None:
            await media_service.fetch_and_cache(mid)
        with get_session() as s:
            row = s.exec(select(Asset).where(Asset.uuid_media_id == mid)).first()
            if row is None or not row.local_path:
                raise ChatAgentError(f"video of #{sid} is not available locally")
            aids.append(row.id)
    if not aids:
        raise ChatAgentError("video_node_short_ids or video_asset_ids must be non-empty")
    new_id, error = await asyncio.to_thread(
        video_concat.concat_video_assets, [int(a) for a in aids]
    )
    if error or new_id is None:
        return {"ok": False, "tool": "concat_videos", "error": error or "unknown"}
    with get_session() as s:
        # A video node, not "merge": the canvas has no renderer for merge,
        # so the joined clip would have no preview and no download button.
        node = _get_or_create_media_node(
            s, board_id, args.get("node_short_id"), "video", "concat"
        )
        node_id, short_id = node.id, node.short_id
        row = s.get(Asset, new_id)
        out_mids = [row.uuid_media_id] if row and row.uuid_media_id else []
    if out_mids:
        _bind_media(node_id, out_mids)
    return {
        "ok": True,
        "tool": "concat_videos",
        "asset_id": new_id,
        "node_short_id": short_id,
    }


async def _tool_update_node(board_id: int, args: dict) -> dict:
    short_id = args.get("short_id")
    patch = args.get("data_patch") or {}
    if not short_id:
        raise ChatAgentError("short_id is required")
    if not isinstance(patch, dict):
        raise ChatAgentError("data_patch must be an object")
    with get_session() as s:
        node = _node_by_short(s, board_id, short_id)
        if node is None:
            raise ChatAgentError(f"node #{short_id} not found")
        # Same shallow-merge + null-deletes semantics as PATCH /api/nodes.
        merged = dict(node.data or {})
        for dk, dv in patch.items():
            if dv is None:
                merged.pop(dk, None)
            else:
                merged[dk] = dv
        node.data = merged
        s.add(node)
        s.commit()
        return {"ok": True, "tool": "update_node", "short_id": short_id}


async def _tool_refresh(board_id: int, args: dict) -> dict:
    return {"ok": True, "tool": "refresh", "board": _dynamic_context(board_id)}


_TOOLS = {
    "build_from_template": _tool_build_from_template,
    "build_board": _tool_build_board,
    "create_node": _tool_create_node,
    "add_edge": _tool_add_edge,
    "gen_image": _tool_gen_image,
    "gen_video": _tool_gen_video,
    "concat_videos": _tool_concat_videos,
    "update_node": _tool_update_node,
    "refresh": _tool_refresh,
}


async def _execute_tool(board_id: int, tool: str, args: dict) -> dict:
    handler = _TOOLS.get(tool)
    if handler is None:
        return {
            "ok": False,
            "tool": tool,
            "error": f"unknown tool {tool!r}; available: {sorted(_TOOLS)}",
        }
    try:
        obs = await handler(board_id, args)
    except ChatAgentError as exc:
        return {"ok": False, "tool": tool, "error": str(exc)}
    obs.setdefault("tool", tool)
    return obs


# ── run lifecycle ─────────────────────────────────────────────────────

def _finish_run(run_id: int, reply: str, *, failed: bool = False) -> None:
    with get_session() as s:
        run = s.get(ChatRun, run_id)
        if run is None:
            logger.error("chat_agent: ChatRun %s vanished", run_id)
            return
        content = reply.strip() or "(agent finished with no summary)"
        msg = ChatMessage(
            board_id=run.board_id, role="assistant", content=content, mentions=[]
        )
        s.add(msg)
        run.status = "failed" if failed else "done"
        if failed:
            run.error = content[:500]
        run.finished_at = _utcnow()
        s.add(run)
        s.commit()


async def _run_agent(
    board_id: int,
    run_id: int,
    message: str,
    attachment_asset_ids: list[int],
    mentions: list[str],
) -> None:
    static_ctx = build_board_context(board_id, message, attachment_asset_ids, mentions)

    attach_paths: Optional[list[str]] = None
    if attachment_asset_ids:
        with get_session() as s:
            paths = []
            for aid in attachment_asset_ids:
                row = s.get(Asset, aid)
                if row is not None and row.local_path and Path(row.local_path).is_file():
                    paths.append(str(Path(row.local_path).resolve()))
        attach_paths = paths or None

    observations: list[dict] = []
    for turn in range(MAX_TURNS):
        dynamic = _dynamic_context(board_id)
        obs_text = ""
        if observations:
            obs_text = "\n\n## Tool results so far\n" + json.dumps(
                observations, ensure_ascii=False, indent=1
            )[-6000:]
        user_prompt = (
            f"{static_ctx}\n\n{dynamic}{obs_text}\n\n"
            "Respond with exactly one JSON object: a tool call or "
                '{"done": true, "reply": "..."}.'
        )
        # Attachments go to the worker on the first turn only; later turns
        # reference them by asset id (already in context).
        raw = await _chat_llm(
            user_prompt,
            attachments=attach_paths if turn == 0 else None,
            turn=turn,
        )
        call = _parse_tool_call(raw)
        if call is None:
            async with record_activity(
                "chat_agent",
                params={"board_id": board_id, "run_id": run_id, "turn": turn,
                        "tool": "unparseable"},
            ) as act:
                act.set_result({"ok": False})
            observations.append(
                {
                    "ok": False,
                    "error": "could not parse a tool call from your reply; "
                    "reply with exactly one JSON object",
                    "raw": raw[:500],
                }
            )
            continue
        if call.done:
            _finish_run(run_id, call.reply or "Xong.")
            return
        # One activity row per turn so the feed shows live progress.
        redacted = {
            k: (str(v)[:200] if k != "data_patch" else "{...}")
            for k, v in call.args.items()
        }
        async with record_activity(
            "chat_agent",
            params={"board_id": board_id, "run_id": run_id, "turn": turn,
                    "tool": call.tool, "args": redacted},
        ) as act:
            obs = await _execute_tool(board_id, call.tool, call.args)
            act.set_result({"ok": bool(obs.get("ok")), "tool": call.tool})
        observations.append(obs)

    _finish_run(
        run_id,
        "Hết lượt suy nghĩ (12 turns) mà chưa xong. "
        "Các bước đã làm:\n"
        + "\n".join(
            f"- {o.get('tool')}: {'ok' if o.get('ok') else o.get('error', 'fail')}"
            for o in observations[-8:]
        ),
    )


async def run_chat_agent(
    board_id: int,
    run_id: int,
    message: str,
    attachment_asset_ids: list[int],
    mentions: list[str],
) -> None:
    """Background-task entry. Never raises."""
    try:
        await _run_agent(board_id, run_id, message, attachment_asset_ids, mentions)
    except LLMError as exc:
        logger.warning("chat_agent run %s: llm unavailable (%s)", run_id, exc)
        _finish_run(run_id, str(exc), failed=True)
    except Exception as exc:  # noqa: BLE001 — catch-all: run must settle
        logger.exception("chat_agent run %s crashed", run_id)
        _finish_run(run_id, f"Agent gặp lỗi: {exc}"[:500], failed=True)
