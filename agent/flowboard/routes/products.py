"""CRUD for the product library: items the user sells, reused across boards.

Photos are uploaded through ``/api/upload`` first; this route only stores
the resulting media ids. Deleting a product leaves the cached image files
alone — the Asset table owns their lifetime, as with references.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Product, _utcnow
from flowboard.services import media as media_service
from flowboard.services.products import list_products, product_dict
from flowboard.services import product_gender, product_link, tab_import
from flowboard.services.llm import gemini_api
from flowboard.services.templates import CATEGORIES

router = APIRouter(prefix="/api/products", tags=["products"])


class ProductBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=600)
    category: Optional[str] = None
    price: Optional[str] = Field(default=None, max_length=60)
    selling_points: Optional[str] = Field(default=None, max_length=2000)
    gender: Optional[str] = None  # male / female / unisex / "" (unknown)
    link: Optional[str] = Field(default=None, max_length=500)
    aff_link: Optional[str] = Field(default=None, max_length=500)
    shop: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=2000)
    media_ids: Optional[list[str]] = Field(default=None, max_length=12)
    aspect_ratio: Optional[str] = None


_TEXT_FIELDS = ("name", "description", "price", "selling_points", "link", "aff_link", "shop", "notes")


def _norm_link(value: str) -> str:
    from flowboard.services.video_fetch import extract_url

    value = (value or "").strip()
    return (extract_url(value) or value).rstrip("/") if value else ""


def _check_duplicate_links(s, row: Product) -> None:
    """409 when another product already carries this affiliate link — the same
    product saved twice would get two sets of posts. The page ``link`` is not
    checked: several products legitimately share a shop/listing page."""
    value = row.aff_link or ""
    if not value:
        return
    other = s.exec(select(Product).where(Product.aff_link == value)).first()
    if other is not None and other.id != row.id:
        raise HTTPException(409, f"Sản phẩm \"{other.name}\" đã dùng link tiếp thị này rồi — không thêm trùng.")


def _apply(row: Product, body: ProductBody) -> None:
    fields = body.model_fields_set
    for key in _TEXT_FIELDS:
        if key in fields and getattr(body, key) is not None:
            value = getattr(body, key).strip()
            if key in ("link", "aff_link"):
                value = _norm_link(value)
            setattr(row, key, value)
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
    if "gender" in fields and body.gender is not None:
        if body.gender not in ("", *product_gender.GENDERS):
            raise HTTPException(400, f"invalid gender {body.gender!r}; must be male / female / unisex or empty")
        row.gender = body.gender
    if not row.name:
        raise HTTPException(400, "name is required")


@router.get("")
def get_products() -> list[dict]:
    return list_products(limit=500)


@router.post("")
def create_product(body: ProductBody) -> dict:
    row = Product(name="")
    _apply(row, body)
    # Not given: guess it from the words ("áo thun nam", "váy", "unisex"…).
    if "gender" not in body.model_fields_set:
        row.gender = product_gender.guess(row.name, row.description)
    with get_session() as s:
        _check_duplicate_links(s, row)
        s.add(row)
        s.commit()
        s.refresh(row)
        return product_dict(row)


@router.get("/shops")
def list_shops() -> list[dict]:
    """Shops the seller works with (from the products), most products first —
    for the shop field's suggestions. Declared before ``/{product_id}``."""
    with get_session() as s:
        rows = s.exec(select(Product.shop, Product.aff_link).where(Product.shop != "")).all()
    out: dict[str, dict] = {}
    for shop, aff in rows:
        row = out.setdefault(shop, {"shop": shop, "products": 0, "with_aff": 0})
        row["products"] += 1
        row["with_aff"] += 1 if aff else 0
    return sorted(out.values(), key=lambda r: (-r["products"], r["shop"]))


@router.get("/open-tabs")
async def get_open_tabs() -> dict:
    """The TikTok / Shopee tabs open in the user's Chrome, each classified
    (shop, product page / list of products, importable) for the picker of
    "Nhập từ tab đang mở". Declared before ``/{product_id}`` so it is not read as an id."""
    try:
        return {"tabs": await tab_import.list_open_tabs()}
    except tab_import.TabImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
        _check_duplicate_links(s, row)
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


class BulkDeleteBody(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


@router.post("/bulk-delete")
def bulk_delete_products(body: BulkDeleteBody) -> dict:
    """Delete several products at once; ids that no longer exist are ignored."""
    deleted = 0
    with get_session() as s:
        for pid in set(body.ids):
            row = s.get(Product, pid)
            if row is not None:
                s.delete(row)
                deleted += 1
        s.commit()
    return {"deleted": deleted}


class ImportTabsBody(BaseModel):
    tab_ids: list[int] = Field(min_length=1, max_length=tab_import.MAX_TABS)


@router.post("/import-tabs")
async def import_from_tabs(body: ImportTabsBody) -> dict:
    """Import the chosen open tabs: a product page becomes one product (read
    in the tab, filled by Gemini), a TikTok showcase / shop page its product
    cards. One result per tab; a tab that fails does not stop the others.
    Photos are uploaded to Flow in the background afterwards."""
    try:
        return await tab_import.import_tabs(body.tab_ids)
    except tab_import.TabImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class FromLinkBody(BaseModel):
    url: str = Field(min_length=8, max_length=4000)


@router.post("/from-link")
async def product_from_link(body: FromLinkBody) -> dict:
    """A product-library draft read from a product page (TikTok Shop, Shopee,
    a shop's own site …). Nothing is saved: the caller shows the draft, the
    user checks it and saves through the normal create route."""
    if not gemini_api.configured():
        raise HTTPException(400, "Chưa có Gemini API key — thêm trong Settings → Gemini API keys.")
    try:
        return await product_link.extract_product(body.url)
    except product_link.ProductLinkError as exc:
        raise HTTPException(502, str(exc))
