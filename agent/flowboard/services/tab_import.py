"""Import products from the TikTok / Shopee tabs the user has open in Chrome.

One button for both shops ("Nhập từ tab đang mở"): the extension lists the
open tabs (``list_shop_tabs``), each one is classified here by its address —
a product page (one product, read in place and filled by Gemini) or a TikTok
showcase / shop page (the product cards on it) — and the user picks which to
import. Tabs are read in the user's own signed-in Chrome, so nothing here
fetches a shop page itself.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

from flowboard.services import product_link, tiktok_import
from flowboard.services.flow_client import get_flow_client

logger = logging.getLogger(__name__)

#: First extension build that answers ``list_shop_tabs`` / ``read_tab``.
MIN_EXTENSION_VERSION = (0, 5, 0)
MAX_TABS = 30
#: Tabs read at once: each product page is a Gemini call, each showcase a
#: scroll-through of the page.
PARALLEL = 3
READ_TAB_TIMEOUT_S = 40.0

#: TikTok addresses that are lists of products (showcase, shop, store pages).
_TIKTOK_LIST = re.compile(r"showcase|/shop|/store|/collection|/product|affiliate|seller", re.I)


class TabImportError(RuntimeError):
    """The message is written for the person in front of the screen."""


def _client():
    client = get_flow_client()
    if not client.connected:
        raise TabImportError("Extension Chrome chưa kết nối. Mở Chrome và kiểm tra badge extension.")
    if product_link._version_tuple(client.extension_version) < MIN_EXTENSION_VERSION:
        raise TabImportError(
            f"Extension đang là bản {client.extension_version or 'cũ'}, chưa biết đọc nhiều tab. Mở "
            "chrome://extensions, bấm ↻ Reload ở Flowboard extension (bản 0.5.0 trở lên), rồi bấm lại."
        )
    return client


def _data(resp: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = resp.get("data")
        return json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (TypeError, ValueError) as exc:
        raise TabImportError("Extension trả về dữ liệu không đọc được") from exc


def classify(url: str) -> dict[str, Any]:
    """``{platform, kind, importable}`` for a tab address. ``kind``:
    ``product`` (one product page), ``list`` (a TikTok page of product
    cards), ``other`` (a TikTok page that does not look like a shop —
    still importable, it may hold cards — or a Shopee page that is not a
    product, which is not)."""
    host = (urlparse(url).hostname or "").lower()
    if host == "shopee.vn" or host.endswith(".shopee.vn"):
        is_product = bool(product_link._SHOPEE_PRODUCT_URL.search(url))
        return {"platform": "shopee", "kind": "product" if is_product else "other", "importable": is_product}
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        if tiktok_import.pdp_url(url):
            kind = "product"
        elif _TIKTOK_LIST.search(urlparse(url).path) or host.startswith(("shop.", "affiliate.", "seller")):
            kind = "list"
        else:
            kind = "other"
        return {"platform": "tiktok", "kind": kind, "importable": True}
    return {"platform": "", "kind": "other", "importable": False}


async def list_open_tabs() -> list[dict[str, Any]]:
    """The open TikTok / Shopee tabs, the one in view first, then by last use."""
    resp = await _client()._send("list_shop_tabs", {}, timeout=10.0)
    if resp.get("error") == "timeout":
        raise TabImportError("Chrome không trả lời. Reload extension ở chrome://extensions rồi thử lại.")
    if resp.get("error"):
        raise TabImportError(f"Extension không liệt kê được tab: {resp['error']}")
    tabs = []
    for t in _data(resp).get("tabs") or []:
        url = str(t.get("url") or "")
        info = classify(url)
        if not info["platform"]:
            continue
        tabs.append({
            "id": int(t["id"]), "url": url, "title": str(t.get("title") or "")[:200],
            "active": bool(t.get("active")), "last_accessed": float(t.get("lastAccessed") or 0),
            **info, "suggested": info["importable"] and info["kind"] != "other",
        })
    tabs.sort(key=lambda t: (not t["active"], -t["last_accessed"]))
    return tabs


async def _read_tab(tab_id: int) -> dict[str, Any]:
    resp = await _client()._send("read_tab", {"tabId": tab_id}, timeout=READ_TAB_TIMEOUT_S)
    err = resp.get("error")
    if err == "TAB_CLOSED":
        raise TabImportError("Tab này đã đóng.")
    if err == "timeout":
        raise TabImportError("Chrome không trả lời kịp khi đọc tab này.")
    if err:
        raise TabImportError(f"Extension không đọc được tab: {err}")
    return _data(resp)


async def _product_page(tab: dict[str, Any]) -> dict[str, Any]:
    """The page dict :func:`product_link.extract_from_page` reads, from the tab."""
    data = await _read_tab(tab["id"])
    tab_url = str(data.get("tabUrl") or data.get("url") or tab["url"])
    head = str(data.get("text") or "")[:600]
    if tab["platform"] == "shopee":
        if "/verify/" in tab_url or "/buyer/login" in tab_url or product_link._LOGIN_WALL.search(head):
            raise TabImportError("Tab đang ở trang đăng nhập / xác minh Shopee. Đăng nhập Shopee trong Chrome rồi bấm lại.")
    page = product_link.page_from_browser(data)
    page["title"] = re.sub(r"\s*[|–-]\s*TikTok(?: Shop)?\s*$", "", page["title"]).strip()
    if product_link._looks_blocked(page["title"], page["text"]):
        if tab["platform"] == "tiktok":
            # TikTok's anti-bot page in the tab: the agent's own read may still get through.
            return await product_link.fetch_page(tiktok_import.pdp_url(tab_url) or tab_url)
        raise TabImportError("Trang đang bắt xác minh (captcha). Giải xác minh trong Chrome rồi bấm lại.")
    if len(page["text"]) < 300 or not page["title"]:
        if tab["platform"] == "tiktok":
            return await product_link.fetch_page(tiktok_import.pdp_url(tab_url) or tab_url)
        raise TabImportError("Trang sản phẩm chưa hiện xong. Đợi trang tải hết rồi bấm lại.")
    page["tab_url"] = tab_url
    return page


async def import_tab(tab: dict[str, Any]) -> dict[str, Any]:
    """Import one tab; never raises — a tab that fails is reported as such."""
    out: dict[str, Any] = {"tab_id": tab["id"], "platform": tab["platform"], "kind": tab["kind"],
                           "title": tab["title"], "url": tab["url"], "ok": False, "found": 0,
                           "created": 0, "skipped": 0, "names": [], "error": None, "_created": []}
    source = "Shopee" if tab["platform"] == "shopee" else "TikTok"
    try:
        if tab["kind"] == "product":
            page = await _product_page(tab)
            read = await product_link.extract_from_page(page)
            created, skipped = tiktok_import.save_draft(read["draft"], read["image_url"] or "",
                                                        page.get("tab_url") or tab["url"], source=source)
            out.update(found=1, names=[read["draft"]["name"]])
        else:
            scraped = await tiktok_import.scrape(tab_id=tab["id"])
            items = scraped.get("items") or []
            created, skipped = tiktok_import.save_products(items, str(scraped.get("tabUrl") or tab["url"]))
            out.update(found=len(items), names=[c["name"] for c in created][:5])
            if not items:
                out["error"] = "Không thấy thẻ sản phẩm nào trên trang này (mở trang showcase / shop, kéo xuống cho hiện thẻ)."
        out.update(ok=out["error"] is None, created=len(created), skipped=skipped, _created=created)
    except (TabImportError, tiktok_import.TikTokImportError, product_link.ProductLinkError) as exc:
        out["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 — one bad tab must not stop the rest
        logger.exception("tab import: tab %s failed", tab["id"])
        out["error"] = f"Lỗi khi đọc tab: {exc}"
    return out


async def import_tabs(tab_ids: list[int]) -> dict[str, Any]:
    """Import the chosen tabs (looked up again, so a stale id from the page
    cannot point at anything else). Photos upload afterwards in one queue."""
    tabs = {t["id"]: t for t in await list_open_tabs()}
    chosen = [tabs[i] for i in dict.fromkeys(tab_ids) if i in tabs and tabs[i]["importable"]][:MAX_TABS]
    if not chosen:
        raise TabImportError("Các tab đã chọn không còn mở (hoặc không phải trang sản phẩm). Bấm quét lại.")
    if any(t["kind"] == "product" for t in chosen) and not product_link.gemini_api.configured():
        raise TabImportError("Chưa có Gemini API key — thêm trong Cài đặt → Gemini API keys.")
    gate = asyncio.Semaphore(PARALLEL)

    async def one(tab: dict[str, Any]) -> dict[str, Any]:
        async with gate:
            return await import_tab(tab)

    results = await asyncio.gather(*(one(t) for t in chosen))
    created = [c for r in results for c in r.pop("_created")]
    if created:
        tiktok_import.start_photo_task(created)
    return {
        "results": results,
        "tabs": len(results),
        "found": sum(r["found"] for r in results),
        "created": len(created),
        "skipped": sum(r["skipped"] for r in results),
        "failed": sum(1 for r in results if not r["ok"]),
        "photos_pending": len([c for c in created if c.get("image")]),
    }
