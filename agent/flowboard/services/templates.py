"""Board templates: a ready-made flow (nodes + prompts + edges) per ad type.

Each ``templates/<id>.json`` is a ``board_builder`` spec plus the fields the
user fills in before it is created::

    {"id": "fashion_ad", "title": "...", "blurb": "...", "scenes": 4,
     "inputs": [{"key": "product", "label": "...", "placeholder": "...",
                 "default": "..."}],
     "character": {"charGender": "female", "charCountry": "vn", ...},
     "nodes": [...], "edges": [...]}

Every ``{{key}}`` inside node data is replaced by that input (or its
default). ``character`` is applied on top of every character node, and the
form may override it (``inputs`` whose key starts with ``char``).

``category`` ties a template to the product categories of the product
library; ``apply_product`` puts a saved product's photos and selling points
on a rendered spec.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
_CHAR_KEYS = ("charGender", "charCountry", "charVibe", "charExtras")

#: Product categories, in the order the product form lists them.
CATEGORIES = ("fashion", "cosmetics", "food", "other")
#: Key of the template node that holds the product photo.
PRODUCT_NODE = "product"
#: Extra product photos beyond the main one that become their own nodes.
MAX_EXTRA_PHOTOS = 2


@lru_cache(maxsize=1)
def _load_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.setdefault("id", path.stem)
        out[doc["id"]] = doc
    return out


def list_templates() -> list[dict]:
    """What the New-project dialog shows: everything but the node graph."""
    return [
        {k: v for k, v in t.items() if k not in ("nodes", "edges")}
        for t in _load_all().values()
    ]


def get_template(template_id: str) -> dict | None:
    return _load_all().get(template_id)


def _fill(value: Any, inputs: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda m: inputs.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_fill(v, inputs) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, inputs) for k, v in value.items()}
    return value


def render(template: dict, inputs: dict[str, str] | None) -> dict:
    """The template's board spec with placeholders and character picks applied."""
    given = {k: str(v).strip() for k, v in (inputs or {}).items() if v is not None}
    values = {i["key"]: given.get(i["key"]) or str(i.get("default") or "")
              for i in template.get("inputs", [])}
    values.update({k: v for k, v in given.items() if k not in values})

    character = dict(template.get("character") or {})
    for key in _CHAR_KEYS:
        if values.get(key):
            character[key] = values[key]

    nodes = []
    for n in template.get("nodes", []):
        data = _fill(dict(n.get("data") or {}), values)
        if n.get("type") == "character":
            data = {**character, **data}
        nodes.append({**n, "data": data})
    return {"nodes": nodes, "edges": list(template.get("edges", []))}


def template_for_category(category: str) -> str | None:
    """The template a product of ``category`` starts from by default."""
    for t in _load_all().values():
        if t.get("category") == category:
            return t["id"]
    return None


def product_inputs(template: dict, product: dict, inputs: dict[str, str] | None) -> dict[str, str]:
    """``inputs`` with the product's text filled in where the user left a gap.

    The product description replaces the ``product`` field only while that
    field is empty or still the template default — a phrase the user typed
    in the dialog wins.
    """
    out = {k: v for k, v in (inputs or {}).items() if v is not None}
    default = next((str(i.get("default") or "") for i in template.get("inputs", [])
                    if i["key"] == "product"), "")
    typed = str(out.get("product") or "").strip()
    if not typed or typed == default:
        out["product"] = product.get("description") or product.get("name") or default
    out.setdefault("product_name", product.get("name") or "")
    out.setdefault("price", product.get("price") or "")
    out.setdefault("selling_points", product.get("selling_points") or "")
    return out


def _script_footer(product: dict) -> str:
    lines = [f"Sản phẩm: {product.get('name') or ''}"
             + (f" — {product['price']}" if product.get("price") else "")]
    points = [p.strip(" -•\t") for p in (product.get("selling_points") or "").splitlines()]
    points = [p for p in points if p]
    if points:
        lines.append("Điểm bán:")
        lines.extend(f"- {p}" for p in points)
    if product.get("link"):
        lines.append(f"Link: {product['link']}")
    return "\n".join(lines)


def apply_product(spec: dict, product: dict) -> dict:
    """Put ``product``'s photos on the spec's product node(s) and its selling
    points under the script note.

    The main photo fills the ``product`` node (status done, so the board
    opens ready to Generate scenes); up to ``MAX_EXTRA_PHOTOS`` more photos
    become extra visual_asset nodes wired to the same scenes, so Flow sees
    the item from every angle the user saved. ``aiBrief`` carries the
    description, which auto-prompt reads instead of running vision.
    """
    nodes = [dict(n) for n in spec["nodes"]]
    edges = list(spec["edges"])
    media_ids = [m for m in (product.get("media_ids") or []) if m]
    name = product.get("name") or ""
    brief = product.get("description") or name
    by_key = {n["key"]: n for n in nodes}

    def photo_data(media_id: str, title: str) -> dict:
        data = {"title": title, "mediaId": media_id, "mediaIds": [media_id],
                "variantCount": 1, "aiBrief": brief, "productId": product.get("id")}
        if product.get("aspect_ratio"):
            data["aspectRatio"] = product["aspect_ratio"]
        return data

    main = by_key.get(PRODUCT_NODE)
    if main is not None and main.get("type") == "visual_asset":
        if media_ids:
            main["data"] = {**main["data"], **photo_data(media_ids[0], f"Sản phẩm — {name}")}
            main["status"] = "done"
        else:
            main["data"] = {**main["data"], "title": f"Sản phẩm — {name} (upload ảnh thật)",
                            "aiBrief": brief, "productId": product.get("id")}
        targets = [b for a, b in (_edge_pair(e) for e in edges) if a == PRODUCT_NODE]
        for i, media_id in enumerate(media_ids[1:1 + MAX_EXTRA_PHOTOS], start=2):
            key = f"{PRODUCT_NODE}_{i}"
            nodes.append({"key": key, "type": "visual_asset", "status": "done",
                          "data": photo_data(media_id, f"Sản phẩm — {name} (ảnh {i})")})
            edges.extend([key, t] for t in targets)

    script = by_key.get("script")
    if script is not None and script.get("type") == "note":
        prompt = str(script["data"].get("prompt") or "").rstrip()
        script["data"] = {**script["data"], "prompt": f"{prompt}\n\n{_script_footer(product)}".strip()}
    return {"nodes": nodes, "edges": edges}


def _edge_pair(edge: Any) -> tuple[str, str]:
    if isinstance(edge, dict):
        return str(edge.get("from")), str(edge.get("to"))
    return str(edge[0]), str(edge[1])
