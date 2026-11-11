"""The product's "description for the AI", written for the seller.

Image and video prompts are English, and every scene prompt starts from ``Product.description`` — a line such as
"a white cotton t-shirt with a small red logo on the chest". A seller cannot be asked to write that. So when a product
is saved with the field empty, or with Vietnamese typed into it, one short call fills it from what the seller did give
(name, selling points, notes, their own Vietnamese description). Best effort: no AI, or an answer that does not look
like the sentence asked for, leaves the product as it was.
"""
from __future__ import annotations

import logging
import re
import unicodedata

from flowboard.db import get_session
from flowboard.db.models import Product

logger = logging.getLogger(__name__)

MAX_CHARS = 300
_SYSTEM = (
    "You write the visual description of a product for an image-generation model. Answer with ONE English sentence "
    "fragment, 8 to 30 words, lower case, no quotes, no price, no brand slogans, no sizes list: what the object is, "
    "its material, colour(s), shape and the details one would see in a photo. Use only what the notes say or what "
    "such a product obviously looks like; never invent a logo, text or colour that is not given. Output the "
    "description only."
)


def is_vietnamese(text: str) -> bool:
    """Has Vietnamese letters (đ, or a vowel with a tone / hat mark) — so it is not the English line prompts need."""
    for ch in text or "":
        if ch in "đĐ":
            return True
        if ord(ch) > 127 and unicodedata.decomposition(ch) and unicodedata.category(ch).startswith("L"):
            return True
    return False


def needs_writing(description: str) -> bool:
    return not (description or "").strip() or is_vietnamese(description)


def clean(answer: str) -> str:
    """The sentence out of the model's answer, or "" when it is not one (a refusal, JSON, Vietnamese, a paragraph)."""
    text = (answer or "").strip().strip("`").strip()
    text = text.splitlines()[0].strip().strip('"\'').strip() if text else ""
    text = re.sub(r"^(description|product)\s*:\s*", "", text, flags=re.I)
    words = text.split()
    if not (3 <= len(words) <= 60) or len(text) > MAX_CHARS or is_vietnamese(text) or text.startswith(("{", "[")):
        return ""
    return text.rstrip(".")


async def fill(product_id: int) -> str:
    """Write the description of this product when it has none in English. Returns what was stored ("" = untouched)."""
    from flowboard.services.llm import LLMError, run_llm

    with get_session() as s:
        row = s.get(Product, product_id)
        if row is None or not needs_writing(row.description or ""):
            return ""
        before = row.description or ""
        notes = "\n".join(x for x in (
            f"Name: {row.name}",
            f"Category: {row.category}" if row.category else "",
            f"Seller's own description: {before}" if before.strip() else "",
            f"Selling points: {row.selling_points}" if row.selling_points else "",
            f"Notes: {(row.notes or '')[:600]}" if row.notes else "",
        ) if x)
    try:
        answer = await run_llm("auto_prompt", notes, system_prompt=_SYSTEM, timeout=60.0)
    except LLMError as exc:
        logger.info("product %s: description not written (%s)", product_id, exc)
        return ""
    except Exception:  # noqa: BLE001 - a helper must never break saving a product
        logger.exception("product %s: description writer crashed", product_id)
        return ""
    text = clean(answer)
    if not text:
        return ""
    with get_session() as s:
        row = s.get(Product, product_id)
        if row is None or (row.description or "") != before:  # the seller edited it meanwhile: theirs wins
            return ""
        row.description = text
        s.add(row)
        s.commit()
    logger.info("product %s: description written by AI", product_id)
    return text
