"""Board templates: list them, and create a board from one."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from flowboard.db import get_session
from flowboard.db.models import Board
from flowboard.services.board_builder import BoardSpecError, build_board
from flowboard.services.products import TemplateBuildError, template_board_spec
from flowboard.services.templates import list_templates

router = APIRouter(prefix="/api", tags=["templates"])


class FromTemplateBody(BaseModel):
    template_id: str = Field(min_length=1, max_length=64)
    name: Optional[str] = Field(default=None, max_length=80)
    inputs: dict[str, str] = Field(default_factory=dict)
    # A saved product: its photo lands on the product node, its description
    # and selling points fill the prompts and the script note.
    product_id: Optional[int] = None


@router.get("/templates")
def get_templates() -> list[dict]:
    return list_templates()


@router.post("/boards/from-template")
def create_board_from_template(body: FromTemplateBody) -> dict:
    """A new board with the template's nodes, prompts and edges already on it."""
    try:
        template, spec, product = template_board_spec(body.template_id, body.inputs, body.product_id)
    except TemplateBuildError as exc:
        raise HTTPException(404, str(exc))
    default_name = template["title"] if product is None else f"{product['name']} — {template['title']}"
    with get_session() as s:
        # The Quicktool wizard reopens the clip from this: which template it
        # follows, which product it sells, and where the user left off.
        board = Board(
            name=(body.name or "").strip() or default_name,
            data={"quicktool": {"template_id": template["id"], "product_id": body.product_id,
                                "inputs": body.inputs, "step": 1}},
        )
        s.add(board)
        s.commit()
        s.refresh(board)
        board_id, name, created_at, data = board.id, board.name, board.created_at, board.data
    try:
        created = build_board(board_id, spec)
    except BoardSpecError as exc:
        # The template file itself is broken; take the empty board back.
        with get_session() as s:
            b = s.get(Board, board_id)
            if b is not None:
                s.delete(b)
                s.commit()
        raise HTTPException(500, f"template {body.template_id!r} is invalid: {exc}")
    return {"id": board_id, "name": name, "created_at": created_at, "data": data, "nodes": created}
