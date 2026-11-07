"""Rewrite a template clip's script for the product it sells.

A template's scenes are written once per category, around a typical item:
the fast-food template's hero shot says "melted cheese" and its first clip
"a hand lifts the top bun", its voice lines are stock phrases with only the
name and price swapped in. Applied to a bag of cơm cháy chà bông that gave
a burger's motion and lines that say nothing about the product (2026-10-22).

So when a clip is made for a saved product, one LLM call rewrites every
scene — image prompt, motion prompt, voice line — from the product's own
description and selling points, keeping the template's beats (hook, detail,
demo, call to action), who is in each shot and every constraint sentence.
``variant`` asks for a different angle when one product gets several clips.
Any failure leaves the template text as it was.

7/11: the scenes are written as phone footage of a real buyer (see
``clip_style``), the model's gender is given (a male model was written as
"she"), the template's studio place moves to where the product is really
used unless the seller picked the place, and a ``voiceless`` clip gets no
voice lines — the pictures and the real sounds carry it.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from flowboard.services import clip_style
from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError
from flowboard.services.prompt_synth import restore_product_guard
from flowboard.services.templates import HANDS_MARKER, strip_hands

logger = logging.getLogger(__name__)

#: ~8 s of natural Vietnamese speech.
MAX_WORDS = 24

_BASE = (
    "You adapt the script of a short TikTok Shop / affiliate clip (scenes of ~8 seconds) to ONE specific "
    "product, so that it looks like a real buyer filmed it on a phone. You get the product facts and the "
    "template's scenes. For every scene return an image prompt, a motion prompt and a voice line.\n"
    "Rules:\n"
    "- Keep each scene's beat and purpose (hook, detail, demo, call to action) and exactly who is in the shot: a "
    "'no people' scene stays without people, a scene with the model keeps the model, hands stay hands.\n"
    "- Describe only what is true for this product, taken from its description and selling points; drop template "
    "details that do not apply (e.g. cheese, buns, features the product does not have). Show the product doing its "
    "real job.\n"
    "- image_prompt and video_prompt are in English. Name the product by its concrete visual words (what it is, "
    "colour, material, the parts that matter, e.g. 'grey long-sleeved work jacket with two small fans on the lower "
    "back') — never just 'the product' — and leave out sizes, colour options, prices and marketing claims. An "
    "image_prompt is ONE still moment (where the motion starts) described as a phone photo: where the phone is, "
    "framing, the person and what they are doing, the place with one or two details, the light, the texture — "
    "at most about 550 characters (the product sentence is added after it); a video_prompt at most about 450.\n"
    "- Scenes with the model: the product and the hands lead — waist-up or medium framing, three-quarter or side "
    "angles, the face partly turned away, small in frame, or half hidden by the phone in a mirror selfie. No tight "
    "face close-ups, and never words like celebrity, idol, K-pop, influencer, famous or flawless (Flow drops clips "
    "of faces it reads as famous).\n"
)

_OUTPUT = (
    "Output ONLY a JSON array, one object per scene in the given order: "
    '[{"image_prompt": "...", "video_prompt": "...", "voice": "..."}] — no prose, no code fences.'
)


def system_prompt(voiceless: bool = False) -> str:
    return _BASE + clip_style.scene_rules(voiceless=voiceless, words=MAX_WORDS) + _OUTPUT


#: The voice-over version, kept under its old name for callers and tests.
_SYSTEM = system_prompt(False)


class TailorError(RuntimeError):
    pass


def _scene_keys(nodes: list[dict]) -> list[tuple[dict, Optional[dict]]]:
    """(image node, its video node) pairs in scene order: s1/v1, s2/v2, …"""
    by_key = {str(n.get("key")): n for n in nodes}
    pairs = []
    i = 1
    while f"s{i}" in by_key:
        img = by_key[f"s{i}"]
        vid = by_key.get(f"v{i}")
        if img.get("type") == "image":
            pairs.append((img, vid if vid is not None and vid.get("type") == "video" else None))
        i += 1
    return pairs


def _product_facts(product: dict) -> str:
    lines = [f"Name: {product.get('name') or ''}"]
    if product.get("category"):
        lines.append(f"Category: {product['category']}")
    if product.get("price"):
        lines.append(f"Price: {product['price']}")
    if product.get("description"):
        lines.append(f"Description: {product['description']}")
    points = [p.strip(" -•\t") for p in (product.get("selling_points") or "").splitlines() if p.strip(" -•\t")]
    if points:
        lines.append("Selling points (Vietnamese):\n" + "\n".join(f"- {p}" for p in points))
    if product.get("notes"):
        lines.append(f"Seller notes: {product['notes']}")
    return "\n".join(lines)


def _parse(text: str, count: int) -> list[dict[str, str]]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise TailorError("no JSON array in the answer")
    try:
        items = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise TailorError(f"bad JSON: {exc}") from exc
    if not isinstance(items, list) or len(items) != count:
        raise TailorError(f"expected {count} scenes, got {len(items) if isinstance(items, list) else '?'}")
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise TailorError("scene is not an object")
        out.append({k: str(it.get(k) or "").strip() for k in ("image_prompt", "video_prompt", "voice")})
    return out


def _clip_words(line: str) -> str:
    words = line.replace('"', "").split()
    return " ".join(words[:MAX_WORDS + 4])  # a little slack; the TTS speeds up long lines anyway


def _hands_tail(prompt: str) -> str:
    i = prompt.find(HANDS_MARKER)
    return "" if i < 0 else " " + prompt[i:].strip()


def _place_note(place: Optional[str], fixed: bool) -> str:
    place = (place or "").strip()
    if not place:
        return ""
    if fixed:
        return f"\nPLACE (the seller picked it — use it in every scene, it wins over the rules): {place}"
    return (f"\nPLACE (the template's suggestion): {place} — keep it only if a real buyer would use this product "
            "there; otherwise move the scenes to the place where it is really used.")


async def tailor_scenes(scenes: list[dict[str, str]], product: dict, *, variant: int = 0, of: int = 1,
                        template_title: str = "", shown_as: Optional[str] = None,
                        instructions: Optional[str] = None, timeout: float = 120.0,
                        voiceless: bool = False, person: Optional[str] = None,
                        place: Optional[str] = None, place_fixed: bool = False) -> list[dict[str, str]]:
    """Rewrite ``scenes`` (each ``{title, image_prompt, video_prompt, voice}``,
    in order) for ``product``. Returns, per scene, the final
    ``{image_prompt, video_prompt, voice}`` with the product guard and any
    hands-mode sentence of the old prompts put back; an empty string means
    "keep the old text" (a ``voiceless`` clip always gets an empty voice).
    ``person`` is :func:`clip_style.person_line` of who is in the shots;
    ``place`` the clip's setting, which the seller chose when ``place_fixed``.
    Raises :class:`TailorError`."""
    if not scenes:
        raise TailorError("no scenes")
    brief = [{
        "scene": i,
        "title": sc.get("title") or f"Cảnh {i}",
        "image_prompt": strip_hands(sc.get("image_prompt") or ""),
        "video_prompt": strip_hands(sc.get("video_prompt") or ""),
        "voice": sc.get("voice") or "",
    } for i, sc in enumerate(scenes, start=1)]
    variation = ""
    if of > 1:
        variation = (f"\n\nThis is clip {variant + 1} of {of} for the same product: pick a different hook, "
                     "different selling points to lead with and different small motions than the other clips "
                     "would (vary by clip number), still following the rules.")
    shown = ""
    if shown_as and shown_as.strip() and shown_as.strip() != (product.get("description") or "").strip():
        # The user typed how the product should look in this clip: it wins.
        shown = (f"\nShow the product in the images exactly as: {shown_as.strip()} "
                 "(copy these words verbatim into every image_prompt).")
    wish = ""
    if instructions and instructions.strip():
        wish = f"\n\nTHE SELLER ALSO ASKS (Vietnamese, follow it within the rules): {instructions.strip()}"
    who = f"\n{person}" if person else ""
    user = (f"PRODUCT\n{_product_facts(product)}{shown}\n\nTEMPLATE: {template_title}{who}"
            f"{_place_note(place, place_fixed)}\n"
            f"SCENES (current version, adapt each):\n{json.dumps(brief, ensure_ascii=False, indent=1)}{variation}{wish}")
    try:
        text = await run_llm("auto_prompt", user, system_prompt=system_prompt(voiceless), timeout=timeout)
    except LLMError as exc:
        raise TailorError(f"LLM failed: {exc}") from exc
    rewritten = _parse(text, len(scenes))
    out = []
    for sc, new in zip(scenes, rewritten):
        old_img, old_vid = sc.get("image_prompt") or "", sc.get("video_prompt") or ""
        img = ""
        if new["image_prompt"]:
            img = restore_product_guard(new["image_prompt"], old_img, image_with_product=True).rstrip()
            img += _hands_tail(old_img)
        vid = ""
        if new["video_prompt"] and old_vid:
            vid = new["video_prompt"].rstrip() + _hands_tail(old_vid)
        out.append({"image_prompt": img, "video_prompt": vid,
                    "voice": _clip_words(new["voice"]) if new["voice"] and not voiceless else ""})
    return out


async def tailor_spec(spec: dict, product: dict, *, variant: int = 0, of: int = 1,
                      template_title: str = "", shown_as: Optional[str] = None,
                      timeout: float = 120.0, voiceless: bool = False, person: Optional[str] = None,
                      place: Optional[str] = None, place_fixed: bool = False) -> dict:
    """``spec`` with every scene rewritten for ``product`` (see module doc).
    Raises :class:`TailorError` on any failure; the caller keeps ``spec``."""
    nodes = [dict(n) for n in spec["nodes"]]
    pairs = _scene_keys(nodes)
    if not pairs:
        raise TailorError("template has no scenes")
    scenes = []
    for img, vid in pairs:
        idata, vdata = img.get("data") or {}, (vid or {}).get("data") or {}
        scenes.append({"title": str(idata.get("title") or ""), "image_prompt": str(idata.get("prompt") or ""),
                       "video_prompt": str(vdata.get("prompt") or ""), "voice": str(vdata.get("narration") or "")})
    rewritten = await tailor_scenes(scenes, product, variant=variant, of=of, template_title=template_title,
                                    shown_as=shown_as, timeout=timeout, voiceless=voiceless, person=person,
                                    place=place, place_fixed=place_fixed)
    for (img, vid), new in zip(pairs, rewritten):
        if new["image_prompt"]:
            img["data"] = {**(img.get("data") or {}), "prompt": new["image_prompt"]}
        if vid is not None:
            vdata = dict(vid.get("data") or {})
            if new["video_prompt"]:
                vdata["prompt"] = new["video_prompt"]
            if new["voice"]:
                vdata["narration"] = new["voice"]
            vid["data"] = vdata
    return {**spec, "nodes": nodes}


def setting_choice(template: dict, inputs: Optional[dict]) -> tuple[str, bool]:
    """``(the clip's setting, whether the seller picked it)``: a setting that
    differs from the template's default was typed / chosen in the dialog."""
    default = next((str(i.get("default") or "") for i in template.get("inputs") or [] if i.get("key") == "setting"), "")
    typed = str((inputs or {}).get("setting") or "").strip()
    return (typed or default), bool(typed) and typed != default


#: Shown as "Lần trước đã yêu cầu …" in the scene's "Tạo lại…" box, whose
#: "↺ Về prompt trước đó" then undoes the rewrite scene by scene.
TAILOR_REQUEST_LABEL = "Viết lại kịch bản theo sản phẩm"


async def tailor_board(board_id: int, scene_ids: list[tuple[int, Optional[int]]], *,
                       instructions: Optional[str] = None) -> dict[str, Any]:
    """Rewrite an existing clip's scenes for its product, in place.

    ``scene_ids`` are ``(image node id, video node id or None)`` in scene
    order (the wizard knows the order). The old prompts are kept as
    ``prevPrompt`` on each node. Returns ``{"updated": n, "nodes": {...}}``."""
    from sqlmodel import select

    from flowboard.db import get_session
    from flowboard.db.models import Board, Node
    from flowboard.node_mirror import apply_node_patch
    from flowboard.services.products import get_product
    from flowboard.services.templates import get_template

    with get_session() as s:
        board = s.get(Board, board_id)
        if board is None:
            raise TailorError("clip not found")
        qt = dict((board.data or {}).get("quicktool") or {})
        all_nodes = s.exec(select(Node).where(Node.board_id == board_id)).all()
        rows = {n.id: dict(n.data or {}) for n in all_nodes}
        model = next((dict(n.data or {}) for n in all_nodes if n.type == "character"), None)
    product = get_product(int(qt["product_id"])) if qt.get("product_id") else None
    if product is None:
        raise TailorError("Clip này không gắn với sản phẩm đã lưu, AI không có mô tả để viết.")
    template = get_template(qt.get("template_id") or "") or {}
    scenes = []
    for img_id, vid_id in scene_ids:
        if img_id not in rows or (vid_id is not None and vid_id not in rows):
            raise TailorError(f"node {img_id}/{vid_id} is not on this clip")
        idata = rows[img_id]
        vdata = rows[vid_id] if vid_id is not None else {}
        scenes.append({"title": str(idata.get("title") or ""), "image_prompt": str(idata.get("prompt") or ""),
                       "video_prompt": str(vdata.get("prompt") or ""), "voice": str(vdata.get("narration") or "")})
    inputs = qt.get("inputs") or {}
    hands = qt.get("hands") or {}
    if hands.get("gender"):
        person = clip_style.person_line(hands["gender"], hands.get("country"))
    elif model is not None:
        person = clip_style.person_line(model.get("charGender"), model.get("charCountry"))
    else:
        person = clip_style.person_line(inputs.get("charGender"), inputs.get("charCountry"))
    place, fixed = setting_choice(template, inputs)
    rewritten = await tailor_scenes(scenes, product, template_title=template.get("title") or "",
                                    shown_as=inputs.get("product"), instructions=instructions,
                                    voiceless=bool(qt.get("voiceless")), person=person,
                                    place=place, place_fixed=fixed)
    updated: dict[str, dict] = {}
    for (img_id, vid_id), sc, new in zip(scene_ids, scenes, rewritten):
        if new["image_prompt"]:
            patch = {"prompt": new["image_prompt"], "prevPrompt": sc["image_prompt"],
                     "lastRequest": TAILOR_REQUEST_LABEL}
            apply_node_patch(img_id, data_patch=patch)
            updated[str(img_id)] = patch
        if vid_id is not None:
            vpatch: dict[str, Any] = {}
            if new["video_prompt"]:
                vpatch.update(prompt=new["video_prompt"], prevPrompt=sc["video_prompt"],
                              lastRequest=TAILOR_REQUEST_LABEL)
            if new["voice"]:
                vpatch["narration"] = new["voice"]
            if vpatch:
                apply_node_patch(vid_id, data_patch=vpatch)
                updated[str(vid_id)] = vpatch
    return {"updated": len(updated), "nodes": updated}
