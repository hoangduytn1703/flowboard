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
