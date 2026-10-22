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
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError
from flowboard.services.prompt_synth import restore_product_guard
from flowboard.services.templates import HANDS_MARKER, strip_hands

logger = logging.getLogger(__name__)

#: ~8 s of natural Vietnamese speech.
MAX_WORDS = 24

_SYSTEM = (
    "You adapt the script of a short TikTok Shop / affiliate ad (scenes of ~8 seconds) to ONE specific "
    "product. You get the product facts and the template's scenes. For every scene return an image prompt, "
    "a motion prompt and a voice line, rewritten so they fit THIS product.\n"
    "Rules:\n"
    "- Keep each scene's beat and purpose (hook, detail, tasting/demo, call to action) and keep exactly who "
    "is in the shot: a 'no people' scene stays without people, a scene with the model keeps the model.\n"
    "- Describe only what is true for this product, taken from its description and selling points. Remove "
    "template details that do not apply (e.g. cheese, buns, sauces, ingredients or features the product "
    "does not have). Use concrete details of this product instead.\n"
    "- image_prompt and video_prompt are in English. Copy the product's name/description words verbatim, "
    "never shorten them to 'the product'. Keep every constraint sentence of the template prompt (lighting, "
    "framing, 'The product must match the reference photo…', 'Locked-off camera…', empty space for a "
    "logo) word for word. The video_prompt keeps the '0-3s: … 3-6s: … 6-8s: …' timeline with small, "
    "physically plausible motions of THIS product; no on-screen text.\n"
    f"- voice is natural spoken Vietnamese, at most {MAX_WORDS} words, like a seller talking to camera "
    "(xưng 'mình', gọi 'mọi người'), warm and specific: each line names a concrete selling point of this "
    "product (texture, taste, ingredient, how it is made, size, use…). The first line hooks and names the "
    "product, the last ends with a short call to action. Mention the price only if it is given. No "
    "hashtags, no emoji, no quotation marks, no made-up claims (no health/medical promises, no discounts "
    "that are not given).\n"
    "Output ONLY a JSON array, one object per scene in the given order: "
    '[{"image_prompt": "...", "video_prompt": "...", "voice": "..."}] — no prose, no code fences.'
)


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


async def tailor_spec(spec: dict, product: dict, *, variant: int = 0, of: int = 1,
                      template_title: str = "", shown_as: Optional[str] = None,
                      timeout: float = 120.0) -> dict:
    """``spec`` with every scene rewritten for ``product`` (see module doc).
    Raises :class:`TailorError` on any failure; the caller keeps ``spec``."""
    nodes = [dict(n) for n in spec["nodes"]]
    pairs = _scene_keys(nodes)
    if not pairs:
        raise TailorError("template has no scenes")
    scenes = []
    for i, (img, vid) in enumerate(pairs, start=1):
        idata, vdata = img.get("data") or {}, (vid or {}).get("data") or {}
        scenes.append({
            "scene": i,
            "title": idata.get("title") or f"Cảnh {i}",
            "image_prompt": strip_hands(str(idata.get("prompt") or "")),
            "video_prompt": strip_hands(str(vdata.get("prompt") or "")),
            "voice": str(vdata.get("narration") or ""),
        })
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
    user = (f"PRODUCT\n{_product_facts(product)}{shown}\n\nTEMPLATE: {template_title}\n"
            f"SCENES (template version, adapt each):\n{json.dumps(scenes, ensure_ascii=False, indent=1)}{variation}")
    try:
        text = await run_llm("auto_prompt", user, system_prompt=_SYSTEM, timeout=timeout)
    except LLMError as exc:
        raise TailorError(f"LLM failed: {exc}") from exc
    rewritten = _parse(text, len(pairs))

    for (img, vid), new in zip(pairs, rewritten):
        idata = dict(img.get("data") or {})
        old_img = str(idata.get("prompt") or "")
        if new["image_prompt"]:
            prompt = restore_product_guard(new["image_prompt"], old_img, image_with_product=True)
            idata["prompt"] = prompt.rstrip() + _hands_tail(old_img)
            img["data"] = idata
        if vid is not None:
            vdata = dict(vid.get("data") or {})
            old_vid = str(vdata.get("prompt") or "")
            if new["video_prompt"]:
                vdata["prompt"] = new["video_prompt"].rstrip() + _hands_tail(old_vid)
            if new["voice"]:
                vdata["narration"] = _clip_words(new["voice"])
            vid["data"] = vdata
    return {**spec, "nodes": nodes}
