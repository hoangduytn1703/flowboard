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
from flowboard.services import product_gender, product_link, tiktok_import
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


class TikTokImportBody(BaseModel):
    max_items: int = Field(default=100, ge=1, le=300)
    with_photos: bool = True


@router.post("/import-tiktok")
async def import_from_tiktok(body: TikTokImportBody) -> dict:
    """Read the products off the TikTok tab the user has open (affiliate
    showcase / shop) through the extension and add the new ones to the
    library. Photos are fetched and uploaded to Flow in the background, so
    the response lists products before they have one.

    ``diag`` is the extension's own account of what it saw; it is what makes
    a zero-result run debuggable, since TikTok's markup is not stable.
    """
    try:
        scraped = await tiktok_import.scrape(body.max_items)
    except tiktok_import.TikTokImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    tab_url = str(scraped.get("tabUrl") or "")
    items = scraped.get("items") or []
    page_url = tiktok_import.pdp_url(tab_url)
    if page_url:
        # A product page: take that one product, not the related-products grid.
        if not gemini_api.configured():
            raise HTTPException(400, "Chưa có Gemini API key — thêm trong Settings → Gemini API keys.")
        try:
            read = await product_link.extract_product(page_url)
        except product_link.ProductLinkError as exc:
            raise HTTPException(502, str(exc))
        items = [{"title": read["draft"]["name"]}]
        created, skipped = tiktok_import.save_draft(read["draft"], read["image_url"] or "", tab_url)
    else:
        created, skipped = tiktok_import.save_products(items, tab_url)
    if created and body.with_photos:
        tiktok_import.start_photo_task(created)
    return {
        "single_product": bool(page_url),
        "found": len(items),
        "created": len(created),
        "skipped": skipped,
        "photos_pending": len([c for c in created if c.get("image")]) if body.with_photos else 0,
        "tab_url": scraped.get("tabUrl"),
        "tab_title": scraped.get("tabTitle"),
        "diag": scraped.get("diag"),
    }


@router.post("/import-shopee")
async def import_from_shopee() -> dict:
    """Read the Shopee product page open in the user's Chrome (extension
    ``read_open_tab``) and add that product. Same answer shape as
    ``/import-tiktok``; the photo is uploaded to Flow in the background."""
    if not gemini_api.configured():
        raise HTTPException(400, "Chưa có Gemini API key — thêm trong Settings → Gemini API keys.")
    try:
        page = await product_link.read_open_shopee_tab()
        read = await product_link.extract_from_page(page)
    except product_link.ProductLinkError as exc:
        raise HTTPException(400, str(exc))
    created, skipped = tiktok_import.save_draft(read["draft"], read["image_url"] or "", page["tab_url"], source="Shopee")
    if created:
        tiktok_import.start_photo_task(created)
    return {
        "single_product": True, "found": 1, "created": len(created), "skipped": skipped,
        "photos_pending": len([c for c in created if c.get("image")]),
        "tab_url": page["tab_url"], "tab_title": page["tab_title"], "diag": None,
        "name": read["draft"]["name"],
    }


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
