"""Switch a clip that already exists between "a model" and "hands only".

The New-clip dialog decides this up front (``templates.render`` /
``reference_video.board_spec``); this is the same choice made later, from
step 1 of the wizard, on nodes that are already on the board:

- hands: the character node goes (it would be generated and fed to every
  scene as a reference), and every scene / clip prompt gets the hands-only
  sentence from :mod:`templates`.
- person: that sentence is removed again and a character node is created
  and wired to every scene image, unless one is still there.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Board, Edge, Node
from flowboard.services.board_builder import build_board
from flowboard.services.templates import (
    HANDS_GENDERS,
    PersonRequiredError,
    get_template,
    strip_hands,
    with_hands,
)


def _person_required(board: Board, product: Optional[dict]) -> bool:
    qt = (board.data or {}).get("quicktool") or {}
    template = get_template(str(qt.get("template_id") or ""))
    if template and template.get("person_required"):
        return True
    category = (product or {}).get("category") or (qt.get("reference") or {}).get("category")
    return category == "fashion"


def set_model_mode(board_id: int, *, mode: str, gender: str = "female", country: str = "vn",
                   vibe: str = "casual", hand_look: str = "", product: Optional[dict] = None) -> dict[str, Any]:
    """``mode`` is ``person`` or ``hands``. Returns the stored ``quicktool.hands``."""
    if mode not in ("person", "hands"):
        raise ValueError("mode must be 'person' or 'hands'")
    if gender not in ("female", "male"):
        raise ValueError("gender must be 'female' or 'male'")
    with get_session() as s:
        board = s.get(Board, board_id)
        if board is None:
            raise LookupError("board not found")
        from flowboard.services.product_gender import check

        check(product, gender)
        if mode == "hands" and _person_required(board, product):
            raise PersonRequiredError(
                "Quần áo cần người mẫu mặc để thấy form và độ vừa, nên không dùng được chế độ chỉ quay bàn tay."
            )
        nodes = s.exec(select(Node).where(Node.board_id == board_id)).all()
        characters = [n for n in nodes if n.type == "character"]
        shots = [n for n in nodes if n.type in ("image", "video")]
        hands = None
        if mode == "hands":
            hands = {"gender": f"hands_{gender}", "country": country, "look": hand_look.strip()}
            for n in characters:
                for e in s.exec(select(Edge).where((Edge.source_id == n.id) | (Edge.target_id == n.id))).all():
                    s.delete(e)
                s.delete(n)
            for n in shots:
                prompt = str((n.data or {}).get("prompt") or "")
                if prompt:
                    n.data = {**n.data, "prompt": with_hands(prompt, gender, country, hand_look)}
                    s.add(n)
        else:
            for n in shots:
                prompt = str((n.data or {}).get("prompt") or "")
                if prompt:
                    n.data = {**n.data, "prompt": strip_hands(prompt)}
                    s.add(n)
            for n in characters:
                n.data = {**n.data, "charGender": gender, "charCountry": country, "charVibe": vibe}
                s.add(n)
        data = dict(board.data or {})
        data["quicktool"] = {**(data.get("quicktool") or {}), "hands": hands}
        board.data = data
        s.add(board)
        s.commit()
        need_model = mode == "person" and not characters
        images = [n.short_id for n in shots if n.type == "image"]
    if need_model:
        build_board(board_id, {
            "nodes": [{"key": "model", "type": "character", "data": {
                "title": "Người mẫu", "charGender": gender, "charCountry": country, "charVibe": vibe}}],
            "edges": [["model", f"#{sid}"] for sid in images],
        })
    return {"hands": hands}


__all__ = ["set_model_mode", "HANDS_GENDERS"]
