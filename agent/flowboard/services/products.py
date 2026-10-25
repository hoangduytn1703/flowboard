"""Product library reads shared by the products route, the template route
and the chat agent."""
from __future__ import annotations

from typing import Any, Optional

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Product
from flowboard.services.templates import (
    apply_product,
    get_template,
    product_inputs,
    render,
    template_for_category,
)


def product_dict(row: Product) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "price": row.price,
        "selling_points": row.selling_points,
        "gender": row.gender or "",
        "link": row.link,
        "aff_link": row.aff_link or "",
        "shop": row.shop or "",
        "notes": row.notes,
        "media_ids": list(row.media_ids or []),
        "aspect_ratio": row.aspect_ratio,
        "template_id": template_for_category(row.category),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def get_product(product_id: int) -> Optional[dict[str, Any]]:
    with get_session() as s:
        row = s.get(Product, product_id)
        return product_dict(row) if row is not None else None


def list_products(limit: int = 50) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.exec(select(Product).order_by(Product.updated_at.desc()).limit(limit)).all()
        return [product_dict(r) for r in rows]


class TemplateBuildError(LookupError):
    """Unknown template or product; the message is meant for the caller."""


def _template_default_gender(template: dict) -> Optional[str]:
    return next((str(i.get("default") or "") for i in template.get("inputs", []) if i.get("key") == "charGender"), None)


def template_board_spec(
    template_id: Optional[str],
    inputs: Optional[dict[str, str]] = None,
    product_id: Optional[int] = None,
) -> tuple[dict, dict, Optional[dict]]:
    """``(template, board spec, product)`` for a template, optionally made
    for a saved product. ``template_id`` may be left out when a product is
    given: the product's category picks the template."""
    product = None
    if product_id is not None:
        product = get_product(product_id)
        if product is None:
            raise TemplateBuildError(f"unknown product {product_id}")
        template_id = template_id or product["template_id"]
    template = get_template(template_id or "")
    if template is None:
        raise TemplateBuildError(f"unknown template {template_id!r}")
    if product is None:
        return template, render(template, inputs), None
    # A men's / women's product cannot be shown on a model of the other gender.
    from flowboard.services.product_gender import check

    check(product, (inputs or {}).get("charGender") or _template_default_gender(template))
    spec = apply_product(render(template, product_inputs(template, product, inputs)), product)
    return template, spec, product
