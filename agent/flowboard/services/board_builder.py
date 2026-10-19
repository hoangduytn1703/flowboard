"""Create a set of nodes and the edges between them on a board, in one go.

Shared by the chat agent's ``build_board`` tool and ``POST
/api/boards/from-template``: both hand over the same spec —

    {"nodes": [{"key": "model", "type": "character", "data": {...}}, ...],
     "edges": [["model", "s1"], {"from": "s1", "to": "v1"}, ...]}

— and get back ``{key: short_id}``. Layout is one column per graph depth
(references → scene images → videos), rows in the order given, placed to
the right of anything already on the board. Nothing is written unless
every node and edge validates. An edge end may name an existing node as
``"#abcd"``.
"""
from __future__ import annotations

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Edge, Node
from flowboard.short_id import generate_unique_short_id

NODE_TYPES = {"character", "visual_asset", "image", "video", "Storyboard", "prompt", "note", "merge", "export"}

COL_W, ROW_H = 340.0, 320.0


class BoardSpecError(ValueError):
    """The spec is malformed; the message is meant for the caller."""


def _parse(spec: dict) -> tuple[dict[str, dict], list[tuple[str, str]]]:
    raw_nodes = spec.get("nodes")
    raw_edges = spec.get("edges") or []
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise BoardSpecError("nodes must be a non-empty list")
    if not isinstance(raw_edges, list):
        raise BoardSpecError("edges must be a list")

    specs: dict[str, dict] = {}
    for i, n in enumerate(raw_nodes):
        if not isinstance(n, dict):
            raise BoardSpecError(f"nodes[{i}] must be an object")
        key = str(n.get("key") or f"n{i}")
        if key in specs or key.startswith("#"):
            raise BoardSpecError(f"node key {key!r} is duplicated or starts with '#'")
        ntype = n.get("type")
        if ntype not in NODE_TYPES:
            raise BoardSpecError(f"nodes[{i}]: unknown type {ntype!r}; valid: {sorted(NODE_TYPES)}")
        data = n.get("data") or {}
        if not isinstance(data, dict):
            raise BoardSpecError(f"nodes[{i}].data must be an object")
        if n.get("title") and "title" not in data:
            data = {**data, "title": str(n["title"])}
        # "done" lets a template land a node that already holds media
        # (a saved product photo); everything else starts idle.
        status = n.get("status") or "idle"
        if status not in ("idle", "done"):
            raise BoardSpecError(f"nodes[{i}]: status must be 'idle' or 'done'")
        specs[key] = {"type": ntype, "data": data, "status": status}

    edges: list[tuple[str, str]] = []
    for i, e in enumerate(raw_edges):
        if isinstance(e, dict):
            pair = (e.get("from"), e.get("to"))
        elif isinstance(e, (list, tuple)) and len(e) == 2:
            pair = (e[0], e[1])
        else:
            raise BoardSpecError(f"edges[{i}] must be [from, to] or {{from, to}}")
        a, b = (str(p or "") for p in pair)
        for end in (a, b):
            if end not in specs and not end.startswith("#"):
                raise BoardSpecError(f"edges[{i}]: unknown node {end!r}")
        edges.append((a, b))
    return specs, edges


def build_board(board_id: int, spec: dict) -> dict[str, str]:
    """Write the spec's nodes and edges to ``board_id``; return key → short_id."""
    specs, edges = _parse(spec)
    with get_session() as s:
        existing = {n.short_id: n for n in s.exec(select(Node).where(Node.board_id == board_id)).all()}
        for a, b in edges:
            for end in (a, b):
                if end.startswith("#") and end[1:] not in existing:
                    raise BoardSpecError(f"node {end} not found on this board")

        # Column = longest path from a source among the new nodes.
        depth = {k: 0 for k in specs}
        for _ in range(len(specs)):
            for a, b in edges:
                if a in specs and b in specs and depth[b] < depth[a] + 1:
                    depth[b] = depth[a] + 1
        x0 = max((n.x for n in existing.values()), default=-COL_W - 60.0) + COL_W + 60.0
        rows: dict[int, int] = {}
        created: dict[str, Node] = {}
        for key, node_spec in specs.items():
            col = depth[key]
            row = rows.get(col, 0)
            rows[col] = row + 1
            node = Node(
                board_id=board_id,
                short_id=generate_unique_short_id(s, board_id),
                type=node_spec["type"],
                x=x0 + col * COL_W,
                y=row * ROW_H,
                data=node_spec["data"],
                status=node_spec["status"],
            )
            s.add(node)
            s.flush()  # short ids must stay unique within this batch
            created[key] = node

        def node_of(end: str) -> Node:
            return existing[end[1:]] if end.startswith("#") else created[end]

        for a, b in edges:
            s.add(Edge(board_id=board_id, source_id=node_of(a).id,
                       target_id=node_of(b).id, kind="ref"))
        s.commit()
        return {k: n.short_id for k, n in created.items()}
