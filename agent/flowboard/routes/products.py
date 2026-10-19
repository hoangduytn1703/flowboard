"""CRUD for the product library: items the user sells, reused across boards.

Photos are uploaded through ``/api/upload`` first; this route only stores
the resulting media ids. Deleting a product leaves the cached image files
alone — the Asset table owns their lifetime, as with references.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from flowboard.db import get_session
from flowboard.db.models import Product, _utcnow
from flowboard.services import media as media_service
from flowboard.services.products import list_products, product_dict
from flowboard.services.templates import CATEGORIES

router = APIRouter(prefix="/api/products", tags=["products"])


class ProductBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=600)
    category: Optional[str] = None
    price: Optional[str] = Field(default=None, max_length=60)
    selling_points: Optional[str] = Field(default=None, max_length=2000)
    link: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=2000)
    media_ids: Optional[list[str]] = Field(default=None, max_length=12)
    aspect_ratio: Optional[str] = None


_TEXT_FIELDS = ("name", "description", "price", "selling_points", "link", "notes")


def _apply(row: Product, body: ProductBody) -> None:
    fields = body.model_fields_set
    for key in _TEXT_FIELDS:
        if key in fields and getattr(body, key) is not None:
            setattr(row, key, getattr(body, key).strip())
    if "category" in fields and body.category is not None:
        if body.category not in CATEGORIES:
            raise HTTPException(400, f"invalid category {body.category!r}; must be one of {list(CATEGORIES)}")
        row.category = body.category
    if "media_ids" in fields and body.media_ids is not None:
        ids = [m.removeprefix("media/") for m in body.media_ids]
        bad = [m for m in ids if not media_service.is_valid_media_id(m)]
        if bad:
            raise HTTPException(400, f"invalid media id(s): {bad}")
        row.media_ids = list(dict.fromkeys(ids))  # de-dupe, keep order
    if "aspect_ratio" in fields:
        row.aspect_ratio = body.aspect_ratio
    if not row.name:
        raise HTTPException(400, "name is required")


@router.get("")
def get_products() -> list[dict]:
    return list_products(limit=500)


@router.post("")
def create_product(body: ProductBody) -> dict:
    row = Product(name="")
    _apply(row, body)
    with get_session() as s:
        s.add(row)
        s.commit()
        s.refresh(row)
        return product_dict(row)


@router.get("/{product_id}")
def get_product(product_id: int) -> dict:
    with get_session() as s:
        row = s.get(Product, product_id)
        if row is None:
            raise HTTPException(404, "product not found")
        return product_dict(row)


@router.patch("/{product_id}")
def patch_product(product_id: int, body: ProductBody) -> dict:
    with get_session() as s:
        row = s.get(Product, product_id)
        if row is None:
            raise HTTPException(404, "product not found")
        _apply(row, body)
        row.updated_at = _utcnow()
        s.add(row)
        s.commit()
        s.refresh(row)
        return product_dict(row)


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int) -> Response:
    with get_session() as s:
        row = s.get(Product, product_id)
        if row is None:
            raise HTTPException(404, "product not found")
        s.delete(row)
        s.commit()
    return Response(status_code=204)
