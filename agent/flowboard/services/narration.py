"""Vietnamese voice-over lines for the video nodes of a board, written by
the auto-prompt LLM from the script note, the product and each clip's own
scene prompt. One call covers every clip so the lines read as one piece:
a hook on the first clip, a call to action on the last.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Edge, Node
from flowboard.node_mirror import apply_node_patch
from flowboard.services import clip_style
from flowboard.services.activity import record_activity
from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError

logger = logging.getLogger(__name__)

#: About 8 s of Vietnamese at a natural pace.
MAX_WORDS = 24

_SYSTEM = (
    "You write voice-over lines in Vietnamese for short TikTok Shop / affiliate "
    "product videos that look like a real buyer filmed them on a phone. The video is a "
    "sequence of clips (about 8 seconds each); you get the script, the product and a "
    "description of every clip, in order. Write ONE spoken line per clip that fits what "
    "that clip shows. Mention the price only if the script gives one. No English "
    "marketing words.\n"
    + clip_style.voice_rules(MAX_WORDS)
    + "Output ONLY a JSON array of strings, one per clip, in the same "
    "order as given — no prose, no code fences."
)


class NarrationError(RuntimeError):
    pass


def _board_context(board_id: int, node_ids: list[int]) -> tuple[str, list[dict[str, Any]]]:
    with get_session() as s:
        nodes = s.exec(select(Node).where(Node.board_id == board_id).order_by(Node.id)).all()
        edges = s.exec(select(Edge).where(Edge.board_id == board_id)).all()
    by_id = {n.id: n for n in nodes}
    script = "\n".join(
        str(n.data.get("prompt") or "") for n in nodes if n.type == "note" and n.data.get("prompt")
    ).strip()
    product = "\n".join(
        f"- {n.data.get('title') or 'product'}: {n.data.get('aiBrief') or n.data.get('prompt') or ''}"
        for n in nodes if n.type == "visual_asset" and (n.data.get("aiBrief") or n.data.get("prompt"))
    ).strip()
    clips: list[dict[str, Any]] = []
    for nid in node_ids:
        node = by_id.get(nid)
        if node is None or node.type != "video":
            raise NarrationError(f"node {nid} is not a video node on board {board_id}")
        sources = [by_id[e.source_id] for e in edges if e.target_id == nid and e.source_id in by_id]
        scene = next((n for n in sources if n.type in ("image", "Storyboard")), None)
        clips.append({
            "node_id": nid,
            "title": node.data.get("title") or "",
            "scene": (scene.data.get("prompt") or scene.data.get("aiBrief") or scene.data.get("title") or "")
            if scene else "",
            "motion": node.data.get("prompt") or "",
            "current": node.data.get("narration") or "",
        })
    parts = []
    if script:
        parts.append(f"SCRIPT (from the board's note):\n{script}")
    if product:
        parts.append(f"PRODUCT:\n{product}")
    parts.append("CLIPS, in order:")
    for i, c in enumerate(clips, start=1):
        parts.append(
            f"{i}. {c['title']}\n   scene: {c['scene'][:400]}\n   motion: {c['motion'][:300]}"
            + (f"\n   current line (improve or keep): {c['current']}" if c["current"] else "")
        )
    parts.append(f"Return a JSON array of exactly {len(clips)} Vietnamese lines.")
    return "\n\n".join(parts), clips


def _parse_lines(text: str, count: int) -> list[str]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise NarrationError(f"narration provider returned no JSON array: {text[:120]!r}")
    try:
        lines = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise NarrationError(f"narration provider returned invalid JSON: {exc}") from exc
    if not isinstance(lines, list):
        raise NarrationError("narration provider returned a non-list")
    out = [re.sub(r"\s+", " ", str(x.get("line") if isinstance(x, dict) else x)).strip(' "\'') for x in lines]
    if len(out) < count:
        raise NarrationError(f"narration provider returned {len(out)} lines for {count} clips")
    return out[:count]


async def write_narrations(board_id: int, node_ids: list[int], *, instructions: Optional[str] = None) -> dict[int, str]:
    """Voice lines for ``node_ids`` (video nodes, in clip order), written onto
    each node's ``data.narration``. Returns ``{node_id: line}``."""
    if not node_ids:
        raise NarrationError("no video nodes given")
    user_msg, clips = _board_context(board_id, node_ids)
    if instructions and instructions.strip():
        user_msg += f"\n\nEXTRA INSTRUCTIONS FROM THE USER:\n{instructions.strip()[:500]}"
    async with record_activity(
        "auto_prompt", params={"board_id": board_id, "mode": "narration", "node_ids": node_ids},
    ) as activity:
        try:
            text = await run_llm("auto_prompt", user_msg, system_prompt=_SYSTEM, timeout=120.0)
        except LLMError as exc:
            raise NarrationError(f"narration provider failed: {exc}") from exc
        lines = _parse_lines(text, len(clips))
        result = {c["node_id"]: line for c, line in zip(clips, lines)}
        for nid, line in result.items():
            apply_node_patch(nid, data_patch={"narration": line})
        activity.set_result({"narrations": {str(k): v for k, v in result.items()}})
        return result
