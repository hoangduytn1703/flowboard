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
library (:data:`ANY_CATEGORY` = fits every product, never picked by
default); ``order`` sorts the list the dialog shows; ``apply_product`` puts
a saved product's photos and selling points on a rendered spec.
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
CATEGORIES = ("fashion", "cosmetics", "food", "grocery", "home", "other")
#: Template ``category`` meaning "any product": the template is offered for
#: every category but is never the default one a product starts from.
ANY_CATEGORY = "any"
#: Key of the template node that holds the product photo.
PRODUCT_NODE = "product"
#: Extra product photos beyond the main one that become their own nodes.
MAX_EXTRA_PHOTOS = 2


@lru_cache(maxsize=1)
def _load_all() -> dict[str, dict]:
    docs = []
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.setdefault("id", path.stem)
        docs.append(doc)
    # ``order`` is the position in the dialog (and which template a category
    # falls back to first); files without one go after those with it.
    docs.sort(key=lambda d: (int(d.get("order", 10**6)), d["id"]))
    return {d["id"]: d for d in docs}


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


#: ``charGender`` values that mean "no person, only hands". The model picker
#: offers them next to female / male, so every template can be shot hands-only.
HANDS_GENDERS = {"hands_female": "female", "hands_male": "male"}
DEFAULT_HAND_LOOK = "beautiful, well-groomed hands with smooth skin, slim fingers and clean natural nails"
_NATIONALITY = {"vn": "Vietnamese", "kr": "Korean", "jp": "Japanese", "cn": "Chinese",
                "th": "Thai", "us": "American", "fr": "French"}


class PersonRequiredError(ValueError):
    """The template needs a person (clothes are judged on a body), so the
    hands-only mode is refused. The message is meant for the user."""


def person_required_message(template: dict) -> str:
    """Why hands-only is refused for ``template``, for the user. The
    template's ``person_reason`` says what the person is there for (clothes
    are judged on a body, food on a face); without one, clothes are assumed."""
    reason = str(template.get("person_reason") or "").strip() or "cần người mẫu mặc để thấy form và độ vừa"
    if not reason.startswith("cần"):
        reason = f"cần người mẫu: {reason}"
    return (f"{template.get('title') or 'Kiểu clip này'} {reason}, "
            "nên không dùng được chế độ chỉ quay bàn tay. Hãy chọn Nữ hoặc Nam.")


#: The "tạo Người mẫu (bước 1) → " step of the note's how-to line.
_MODEL_STEP = re.compile(r"tạo Người [^→\n]*→ ")


#: Starts the sentence hands mode appends, so it can be found and removed again.
HANDS_MARKER = "HANDS-ONLY SHOT:"


def hands_instruction(gender: str, country: str | None = None, look: str | None = None) -> str:
    """Appended to every scene and clip prompt in hands mode. The prompts are
    written around a model, so rather than rewriting each one it overrides
    them: wherever a person appears, only their hands do. ``gender`` is
    ``female`` / ``male`` or one of :data:`HANDS_GENDERS`."""
    gender = HANDS_GENDERS.get(gender, gender)
    nationality = _NATIONALITY.get(country or "vn", "")
    look = (look or "").strip() or DEFAULT_HAND_LOOK
    return (f" {HANDS_MARKER} show only {nationality} {gender} hands and forearms ({look}) handling the product, "
            "shot straight-on at the product. No face and no other part of a person is visible; wherever "
            "this prompt describes a person or model, show just their hands instead.").replace("  ", " ")


def strip_hands(prompt: str) -> str:
    """``prompt`` without a hands-mode sentence, if one was appended."""
    i = prompt.find(HANDS_MARKER)
    return prompt if i < 0 else prompt[:i].rstrip()


def with_hands(prompt: str, gender: str, country: str | None = None, look: str | None = None) -> str:
    """``prompt`` ending in exactly one hands-mode sentence (replacing an older one)."""
    return strip_hands(prompt) + hands_instruction(gender, country, look)


def _hands_instruction(values: dict[str, str]) -> str:
    return hands_instruction(values["charGender"], values.get("charCountry"), values.get("handLook"))


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

    hands = values.get("charGender") in HANDS_GENDERS
    if hands and template.get("person_required"):
        raise PersonRequiredError(person_required_message(template))
    hands_text = _hands_instruction(values) if hands else ""
    nodes = []
    dropped: set[str] = set()
    for n in template.get("nodes", []):
        if hands and n.get("type") == "character":
            dropped.add(str(n.get("key")))  # no person: no model to generate or reference
            continue
        data = _fill(dict(n.get("data") or {}), values)
        if n.get("type") == "character":
            data = {**character, **data}
        elif hands and n.get("type") in ("image", "video") and data.get("prompt"):
            data["prompt"] = str(data["prompt"]).rstrip() + hands_text
        elif hands and n.get("type") == "note" and data.get("prompt"):
            # The how-to line names a model step that does not exist here.
            data["prompt"] = (_MODEL_STEP.sub("", str(data["prompt"])).rstrip()
                              + "\nChế độ chỉ quay bàn tay: không có người mẫu, không lộ mặt.")
        nodes.append({**n, "data": data})
    edges = [e for e in template.get("edges", []) if not (set(_edge_pair(e)) & dropped)]
    return {"nodes": nodes, "edges": edges}


def template_for_category(category: str) -> str | None:
    """The template a product of ``category`` starts from by default: the
    first (by ``order``) made for that category. Templates for
    :data:`ANY_CATEGORY` are never the default."""
    if not category or category == ANY_CATEGORY:
        return None
    for t in _load_all().values():
        if t.get("category") == category:
            return t["id"]
    return None


def templates_for_category(category: str | None) -> list[dict]:
    """The templates the dialog should put first for a product of
    ``category``: its own ones, then the ones for any category."""
    listed = list_templates()
    own = [t for t in listed if category and t.get("category") == category]
    return own + [t for t in listed if t.get("category") == ANY_CATEGORY]


def product_inputs(template: dict, product: dict, inputs: dict[str, str] | None) -> dict[str, str]:
    """``inputs`` with the product's text filled in where the user left a gap.

    The product description replaces the ``product`` field only while that
    field is empty or still the template default — a phrase the user typed
    in the dialog wins. The same goes for ``price`` (templates that read
    the price aloud default it to a filler like "hạt dẻ").
    """
    out = {k: v for k, v in (inputs or {}).items() if v is not None}
    defaults = {i["key"]: str(i.get("default") or "") for i in template.get("inputs", [])}
    default = defaults.get("product", "")
    typed = str(out.get("product") or "").strip()
    if not typed or typed == default:
        out["product"] = product.get("description") or product.get("name") or default
    out.setdefault("product_name", product.get("name") or "")
    typed_price = str(out.get("price") or "").strip()
    if product.get("price") and (not typed_price or typed_price == defaults.get("price", "")):
        out["price"] = product["price"]
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
        # The note is Vietnamese; its title took the English description that
        # filled {{product}} ("Quảng cáo a navy blue oversized t-shirt…"). The
        # product's name is what belongs there.
        if name and brief != name:
            prompt = prompt.replace(brief, name)
        script["data"] = {**script["data"], "prompt": f"{prompt}\n\n{_script_footer(product)}".strip()}
    return {"nodes": nodes, "edges": edges}


def voiceless_spec(spec: dict) -> dict:
    """``spec`` as a "🔇 Không lời" clip: no voice line on any scene, and the
    script note says so instead of explaining the voice-over."""
    from flowboard.services.clip_style import NOTE_VOICE, NOTE_VOICELESS

    nodes = []
    for n in spec["nodes"]:
        data = dict(n.get("data") or {})
        if n.get("type") == "video" and data.get("narration"):
            data["narration"] = ""
        elif n.get("type") == "note" and data.get("prompt"):
            note = str(data["prompt"])
            data["prompt"] = (note.replace(NOTE_VOICE, NOTE_VOICELESS) if NOTE_VOICE in note
                              else note.rstrip() + "\n" + NOTE_VOICELESS)
        nodes.append({**n, "data": data})
    return {**spec, "nodes": nodes}


def _edge_pair(edge: Any) -> tuple[str, str]:
    if isinstance(edge, dict):
        return str(edge.get("from")), str(edge.get("to"))
    return str(edge[0]), str(edge[1])
