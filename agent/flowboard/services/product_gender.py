"""Who a product is for — men, women, or both — and the check that keeps a
clip's model from contradicting it (a men's shirt worn by a woman).

``Product.gender`` is one of ``male`` / ``female`` / ``unisex`` / ``""``
(unknown: nothing is enforced). It is guessed from the name and
description when the user leaves it empty, filled by Gemini when a product
is read from a link, and can always be set by hand.
"""
from __future__ import annotations

import re
from typing import Optional

GENDERS = ("male", "female", "unisex")
LABEL = {"male": "nam", "female": "nữ", "unisex": "nam và nữ"}

# "nam" is also the second half of "Việt Nam" / "miền Nam": those go first.
_NOT_MALE = re.compile(r"việt\s*nam|viet\s*nam|miền\s*nam|mien\s*nam|hàng\s*vn|made\s+in\s+vietnam", re.I)
_UNISEX = re.compile(r"\bunisex\b|nam\s*(?:[/&,+-]|và|va|hoặc)?\s*nữ\b|nữ\s*(?:[/&,+-]|và)?\s*nam\b|\bcặp\s*đôi\b|\bcouple\b|\bmen\s*(?:&|and)\s*women\b", re.I)
_MALE = re.compile(r"\b(?:nam|men|man|male|mens|bé\s*trai|con\s*trai|bố|ba\s+mặc|for\s+him)\b", re.I)
_FEMALE = re.compile(r"\b(?:nữ|women|woman|female|womens|ladies|bé\s*gái|con\s*gái|mẹ\s*bầu|bầu|váy|đầm|bikini|for\s+her)\b", re.I)


def guess(*texts: Optional[str]) -> str:
    """Best guess from free text; ``""`` when the text says nothing."""
    text = _NOT_MALE.sub(" ", " ".join(t or "" for t in texts))
    if _UNISEX.search(text):
        return "unisex"
    male, female = bool(_MALE.search(text)), bool(_FEMALE.search(text))
    if male and female:
        return "unisex"
    return "male" if male else "female" if female else ""


class GenderMismatchError(ValueError):
    """The model's gender contradicts the product's; message is for the user."""


def model_gender(char_gender: Optional[str]) -> Optional[str]:
    """``female`` / ``male`` for a model pick, hands included; None = no person."""
    g = (char_gender or "").removeprefix("hands_")
    return g if g in ("female", "male") else None


def check(product: Optional[dict], char_gender: Optional[str]) -> None:
    """Refuse a model of the other gender for a men's / women's product."""
    target = (product or {}).get("gender") or ""
    picked = model_gender(char_gender)
    if target in ("male", "female") and picked and picked != target:
        name = (product or {}).get("name") or "Sản phẩm này"
        raise GenderMismatchError(
            f"\"{name}\" là đồ dành cho {LABEL[target]}, nên người mẫu phải là {LABEL[target]}. "
            "Đổi giới tính người mẫu, hoặc sửa mục \"Dành cho\" của sản phẩm nếu nó dùng được cho cả hai."
        )
