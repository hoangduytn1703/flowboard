"""Import the products on a TikTok page (an affiliate showcase, a shop) into
the product library.

The page is read by the Chrome extension, from a tab the user already has
open and signed in to — TikTok offers affiliates no API for this, and the
agent has no session of its own. This module turns what the extension found
into ``Product`` rows and attaches each product's photo afterwards, because
the photo has to go through Flow's upload (a captcha-gated RPC, a few seconds
each) and the user should not wait on that to see their list.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

import httpx
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Product, _utcnow
from flowboard.services.flow_client import get_flow_client
from flowboard.services.flow_project import effective_project_id

logger = logging.getLogger(__name__)

SCRAPE_TIMEOUT_S = 180.0
PHOTO_TIMEOUT_S = 20.0
MAX_PHOTO_BYTES = 10 * 1024 * 1024

_CATEGORY_WORDS = {
    "cosmetics": ("son ", "kem ", "serum", "sữa rửa mặt", "mặt nạ", "nước hoa", "dưỡng", "makeup",
                  "trang điểm", "tẩy trang", "chống nắng", "phấn", "mascara", "toner", "lipstick"),
    "fashion": ("áo", "quần", "váy", "đầm", "giày", "dép", "túi", "balo", "mũ", "nón", "kính",
                "thời trang", "len", "hoodie", "jeans", "sandal", "sneaker"),
    "food": ("bánh", "kẹo", "trà", "cà phê", "snack", "mì ", "gia vị", "nước mắm", "hạt", "khô ",
             "thực phẩm", "đồ ăn", "ăn vặt", "sữa", "nước ép"),
}

#: Strong references so a fire-and-forget photo task is not collected midway.
_tasks: set[asyncio.Task] = set()


class TikTokImportError(RuntimeError):
    """The message is written for the person in front of the screen."""


def guess_category(title: str) -> str:
    low = f" {title.lower()} "
    for category, words in _CATEGORY_WORDS.items():
        if any(w in low for w in words):
            return category
    return "other"


async def scrape(max_items: int = 100) -> dict[str, Any]:
    """Ask the extension to read the open TikTok tab."""
    resp = await get_flow_client()._send(
        "scrape_page", {"maxItems": max_items, "scrolls": 14}, timeout=SCRAPE_TIMEOUT_S,
    )
    err = resp.get("error")
    if err == "extension_disconnected":
        raise TikTokImportError("Extension Chrome chưa kết nối. Mở lại Chrome và kiểm tra badge extension.")
    if err == "NO_TIKTOK_TAB":
        raise TikTokImportError(
            "Chưa thấy tab TikTok nào. Mở trang showcase / shop của bạn trên TikTok (đã đăng nhập), "
            "rồi bấm nhập lại. Nếu vừa cập nhật extension, hãy reload extension ở chrome://extensions."
        )
    if err:
        raise TikTokImportError(f"Extension không đọc được trang: {err}")
    try:
        data = resp.get("data")
        return json.loads(data) if isinstance(data, str) else dict(data or {})
    except (TypeError, ValueError) as exc:
        raise TikTokImportError("Extension trả về dữ liệu không đọc được") from exc


#: A product detail page: the one product the page is about, with a grid of
#: related ones under it. Reading the cards there would import every "you may
#: also like" item, so the page's own product is read instead.
_PDP_RE = re.compile(r"^(https?://[^/]*tiktok\.com/(?:[a-z]{2}/pdp/|view/product/|product/)\d+)", re.I)


def pdp_url(tab_url: Optional[str]) -> Optional[str]:
    m = _PDP_RE.match((tab_url or "").strip())
    return m.group(1) if m else None


def save_draft(draft: dict[str, Any], image_url: str, source_url: str) -> tuple[list[dict[str, Any]], int]:
    """Save one fully-read product (name, English description, selling
    points …). Returns ``(created, skipped)`` like :func:`save_products`;
    a product already in the library under the same link is skipped."""
    with get_session() as s:
        link = str(draft.get("link") or "")
        if link and s.exec(select(Product).where(Product.link == link)).first() is not None:
            return [], 1
        row = Product(
            name=str(draft.get("name") or "")[:120],
            description=str(draft.get("description") or ""),
            category=str(draft.get("category") or "other"),
            price=str(draft.get("price") or ""),
            selling_points=str(draft.get("selling_points") or ""),
            link=link,
            notes=f"Nhập từ TikTok ({source_url[:200]})",
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return [{"id": row.id, "name": row.name, "image": image_url}], 0


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()[:120]


def save_products(items: list[dict[str, Any]], source_url: str) -> tuple[list[dict[str, Any]], int]:
    """Create a ``Product`` per new item. Returns ``(created, skipped)``;
    an item is skipped when a product with the same link, or the same name
    and price, is already in the library."""
    created: list[dict[str, Any]] = []
    skipped = 0
    with get_session() as s:
        existing = s.exec(select(Product)).all()
        links = {p.link for p in existing if p.link}
        names = {(p.name.lower(), p.price) for p in existing}
        for it in items:
            name = _clean_title(str(it.get("title") or ""))
            link = str(it.get("url") or "")[:500]
            price = str(it.get("price") or "")[:60]
            if not name or (link and link in links) or (name.lower(), price) in names:
                skipped += 1
                continue
            row = Product(
                name=name, price=price, link=link,
                category=guess_category(name),
                notes=f"Nhập từ TikTok ({source_url[:200]})",
            )
            s.add(row)
            s.flush()
            links.add(link)
            names.add((name.lower(), price))
            created.append({"id": row.id, "name": name, "image": str(it.get("image") or "")})
        s.commit()
    return created, skipped


async def _attach_photo(product_id: int, image_url: str, project_id: str) -> bool:
    # Imported here: routes.upload pulls in the FastAPI app layer.
    from flowboard.routes.upload import _ingest_image_bytes, _is_public_host, _sniff_image_mime
    from urllib.parse import urlparse

    parsed = urlparse(image_url)
    if parsed.scheme not in ("http", "https") or not _is_public_host(parsed.hostname or ""):
        return False
    try:
        async with httpx.AsyncClient(timeout=PHOTO_TIMEOUT_S, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
            "Referer": "https://www.tiktok.com/",
        }) as client:
            resp = await client.get(image_url)
    except httpx.HTTPError as exc:
        logger.warning("tiktok import: photo fetch failed for product %s: %s", product_id, exc)
        return False
    raw = resp.content
    mime = _sniff_image_mime(raw) if resp.status_code == 200 else None
    if mime is None or len(raw) > MAX_PHOTO_BYTES:
        logger.warning("tiktok import: product %s photo unusable (HTTP %s, %d bytes)",
                       product_id, resp.status_code, len(raw))
        return False
    try:
        out = await _ingest_image_bytes(raw, mime, project_id, f"product-{product_id}", None)
    except Exception as exc:  # noqa: BLE001 — one bad photo must not stop the rest
        logger.warning("tiktok import: photo upload failed for product %s: %s", product_id, exc)
        return False
    with get_session() as s:
        row = s.get(Product, product_id)
        if row is None:
            return False
        row.media_ids = [out["media_id"]]
        row.aspect_ratio = out.get("aspect_ratio")
        row.updated_at = _utcnow()
        s.add(row)
        s.commit()
    return True


async def attach_photos(created: list[dict[str, Any]]) -> None:
    project_id = effective_project_id()
    if not project_id:
        logger.warning("tiktok import: no Flow project pinned, photos skipped")
        return
    done = 0
    for item in created:
        if item.get("image") and await _attach_photo(item["id"], item["image"], project_id):
            done += 1
    logger.info("tiktok import: %d/%d photos attached", done, len(created))


def start_photo_task(created: list[dict[str, Any]]) -> None:
    task = asyncio.create_task(attach_photos(created))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
