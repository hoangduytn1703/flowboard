"""Clip from a product link: the agent downloads the product page
(Shopee, Lazada, TikTok Shop, a shop's own site …), pulls out the text
that describes the item, and Gemini writes the same scene plan the
reference-video flow produces — no ad video needed. The result goes
through ``reference_video.normalize`` / ``build_board`` unchanged.
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import logging
import re
import socket
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from flowboard.services import reference_video
from flowboard.services.llm import gemini_api
from flowboard.services.templates import CATEGORIES

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_S = 25.0
MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_PAGE_TEXT = 9000
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/126.0 Safari/537.36")


class ProductLinkError(RuntimeError):
    pass


def _check_public(url: str) -> None:
    """Refuse anything that is not a public http(s) host — the agent sits
    on the user's machine, so a pasted link must not reach localhost or
    the LAN."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ProductLinkError("Link phải bắt đầu bằng http:// hoặc https://")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise ProductLinkError(f"Không phân giải được tên miền {parsed.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ProductLinkError("Link trỏ vào địa chỉ nội bộ, không hỗ trợ")


def _meta(page: str, *names: str) -> str:
    for name in names:
        for pat in (
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)["\']',
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{re.escape(name)}["\']',
        ):
            m = re.search(pat, page, re.I)
            if m and m.group(1).strip():
                return html.unescape(m.group(1)).strip()
    return ""


def _json_ld(page: str) -> list[str]:
    """schema.org Product blocks, flattened to ``key: value`` lines."""
    out: list[str] = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.I | re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and "Product" in str(node.get("@type", "")):
                offers = node.get("offers") if isinstance(node.get("offers"), dict) else {}
                for key, val in (("name", node.get("name")), ("description", node.get("description")),
                                 ("brand", (node.get("brand") or {}).get("name") if isinstance(node.get("brand"), dict) else node.get("brand")),
                                 ("price", offers.get("price")), ("currency", offers.get("priceCurrency"))):
                    if val:
                        out.append(f"{key}: {val}")
    return out


def _visible_text(page: str) -> str:
    page = re.sub(r"<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", page, flags=re.I | re.S)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    return re.sub(r"\s+", " ", text).strip()


#: Pages a shop serves instead of the product when it decides the request is
#: a bot (TikTok's "Security Check", Shopee's captcha…). Seen live: the same
#: TikTok link answered with the product page, then with this, then the
#: product again, so one retry after a pause is worth it.
_BLOCK_PAGE = re.compile(
    r"security check|captcha|verify (?:you are|that you are) (?:a )?human|access denied|"
    r"are you a robot|unusual traffic|xác minh (?:bạn|rằng)|kiểm tra bảo mật",
    re.I,
)
BLOCK_RETRY_DELAY_S = 3.0


def _looks_blocked(title: str, text: str) -> bool:
    """A challenge page: its title says so, or the whole page is a short
    challenge text (a real product page is thousands of characters)."""
    return bool(_BLOCK_PAGE.search(title or "")) or (len(text) < 1500 and bool(_BLOCK_PAGE.search(text)))


# ── shops that only render in a signed-in browser (Shopee) ─────────────────

#: Hosts whose product pages are JavaScript-only and behind a login wall:
#: a plain fetch gets an empty shell, the API answers 403, a headless browser
#: is sent to "Cần đăng nhập". They are read by the Chrome extension instead,
#: in the user's own signed-in browser (``read_page``, extension >= 0.4.0).
BROWSER_ONLY_HOSTS = ("shopee.vn", "shp.ee")
#: hosts of tracked affiliate short links (what the seller copies from Shopee /
#: TikTok affiliate tools) — kept on the product as ``aff_link``
AFF_LINK_HOSTS = ("s.shopee.vn", "shp.ee", "shope.ee", "vt.tiktok.com", "vn.shp.ee", "s.lazada.vn", "c.lazada.vn")


def affiliate_link(url: str) -> str:
    """``url`` when it is an affiliate short link, else ``""``."""
    from urllib.parse import urlparse

    host = (urlparse((url or "").strip()).hostname or "").lower()
    return url.strip() if any(host == h or host.endswith("." + h) for h in AFF_LINK_HOSTS) else ""
MIN_READ_PAGE_VERSION = (0, 4, 0)
READ_PAGE_TIMEOUT_S = 45.0
_LOGIN_WALL = re.compile(r"cần đăng nhập|đăng nhập để tiếp tục|chưa đăng nhập", re.I)


def needs_browser(url: str) -> bool:
    host = (urlparse(url.strip()).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in BROWSER_ONLY_HOSTS)


def _version_tuple(v: Optional[str]) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in (v or "0").split("."))
    except ValueError:
        return (0,)


def _ld_products(ld: list) -> list[dict]:
    """schema.org Product objects anywhere in the page's JSON-LD."""
    out: list[dict] = []
    stack = list(ld)
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            if "Product" in str(node.get("@type", "")):
                out.append(node)
            stack.extend(v for k, v in node.items() if k == "@graph")
    return out


def page_from_browser(data: dict[str, Any]) -> dict[str, Any]:
    """Turn what the extension read into the dict :func:`fetch_page` returns."""
    products = _ld_products(data.get("ld") or [])
    prod = products[0] if products else {}
    title = str(prod.get("name") or data.get("title") or "").strip()
    title = re.sub(r"\s*[|–-]\s*Shopee Việt Nam.*$", "", title).strip()
    description = str(prod.get("description") or data.get("description") or "").strip()
    image = prod.get("image")
    if isinstance(image, list):
        image = image[0] if image else ""
    image = str(image or data.get("ogImage") or ((data.get("images") or [{}])[0].get("src")) or "")
    offers = prod.get("offers") if isinstance(prod.get("offers"), dict) else {}
    lines = [f"title: {title}", f"description: {description[:1500]}"]
    for key in ("price", "lowPrice", "highPrice", "priceCurrency"):
        if offers.get(key):
            lines.append(f"{key}: {offers[key]}")
    if prod.get("brand"):
        brand = prod["brand"]
        lines.append(f"brand: {brand.get('name') if isinstance(brand, dict) else brand}")
    lines += ["", str(data.get("text") or "")]
    return {"url": str(data.get("url") or ""), "title": title, "description": description,
            "image_url": image, "text": "\n".join(lines)[:MAX_PAGE_TEXT]}


async def read_via_extension(url: str) -> dict[str, Any]:
    """Read a browser-only product page through the Chrome extension."""
    from flowboard.services.flow_client import get_flow_client

    client = get_flow_client()
    if not client.connected:
        raise ProductLinkError("Link Shopee cần đọc qua Chrome, nhưng extension chưa kết nối. Mở Chrome và kiểm tra badge extension.")
    if _version_tuple(client.extension_version) < MIN_READ_PAGE_VERSION:
        have = client.extension_version or "cũ"
        raise ProductLinkError(
            f"Extension đang là bản {have}, chưa biết đọc Shopee. Mở chrome://extensions, bấm ↻ Reload ở "
            "Flowboard extension (bản 0.4.0 trở lên), rồi thử lại."
        )
    resp = await client._send("read_page", {"url": url.strip()}, timeout=READ_PAGE_TIMEOUT_S)
    err = resp.get("error")
    if err == "timeout":
        raise ProductLinkError("Chrome không trả lời kịp khi mở trang Shopee. Thử lại, hoặc reload extension.")
    if err:
        raise ProductLinkError(f"Extension không đọc được trang Shopee: {err}")
    try:
        raw = resp.get("data")
        data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (TypeError, ValueError) as exc:
        raise ProductLinkError("Extension trả về dữ liệu không đọc được") from exc
    if data.get("blocked") or _LOGIN_WALL.search(str(data.get("text") or "")[:600]):
        raise ProductLinkError(
            "Shopee yêu cầu đăng nhập (hoặc đang bắt xác minh). Mở shopee.vn trong Chrome, đăng nhập "
            "(và giải xác minh nếu có), rồi thử lại."
        )
    if data.get("timeout") or not data.get("text"):
        raise ProductLinkError("Trang Shopee chưa hiện xong sau 25 giây. Thử lại, mạng chậm thì đợi thêm.")
    page = page_from_browser(data)
    if _looks_blocked(page["title"], page["text"]):
        raise ProductLinkError("Shopee đang bắt xác minh (captcha). Mở shopee.vn trong Chrome, giải xác minh rồi thử lại.")
    if not page["title"]:
        raise ProductLinkError("Không đọc được tên sản phẩm trên trang Shopee này.")
    return page


#: A Shopee product page address: ".../<slug>-i.<shop>.<item>" or "/product/<shop>/<item>"
#: (``tab_import`` tells product tabs from search / shop tabs by it).
_SHOPEE_PRODUCT_URL = re.compile(r"-i\.\d+\.\d+|/product/\d+/\d+", re.I)


async def get_page(url: str) -> dict[str, Any]:
    """The product page, read by the agent or — for browser-only shops — by Chrome."""
    return await read_via_extension(url) if needs_browser(url) else await fetch_page(url)


async def fetch_page(url: str) -> dict[str, Any]:
    """``{url, title, description, image_url, text}`` for a product page.
    Raises :class:`ProductLinkError` on an anti-bot page instead of handing
    it on: Gemini would otherwise read "Security Check" as the product."""
    page = await _fetch_page_once(url)
    if _looks_blocked(page["title"], page["text"]):
        logger.info("product link: anti-bot page for %s, retrying once", url[:80])
        await asyncio.sleep(BLOCK_RETRY_DELAY_S)
        page = await _fetch_page_once(url)
        if _looks_blocked(page["title"], page["text"]):
            raise ProductLinkError(
                "Trang đang chặn đọc tự động (trang kiểm tra bảo mật / captcha). Thử lại sau ít phút, "
                "hoặc thêm sản phẩm bằng tay ở trang Sản phẩm đang bán."
            )
    return page


async def _fetch_page_once(url: str) -> dict[str, Any]:
    url = url.strip()
    _check_public(url)
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, follow_redirects=True, max_redirects=5,
                                     headers={"User-Agent": _UA, "Accept-Language": "vi,en;q=0.8"}) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise ProductLinkError(f"Không mở được link: {exc}") from exc
    _check_public(str(resp.url))  # a redirect must not slip past the check
    if resp.status_code >= 400:
        raise ProductLinkError(f"Trang trả về HTTP {resp.status_code} (có thể trang chặn bot — hãy tạo sản phẩm và dán mô tả vào)")
    page = resp.text[:MAX_PAGE_BYTES]
    title = _meta(page, "og:title", "twitter:title") or (
        html.unescape(m.group(1)).strip() if (m := re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)) else "")
    description = _meta(page, "og:description", "description", "twitter:description")
    image = _meta(page, "og:image", "twitter:image")
    lines = [f"title: {title}", f"description: {description}", *_json_ld(page), "", _visible_text(page)]
    text = "\n".join(l for l in lines if l is not None)[:MAX_PAGE_TEXT]
    if len(title) + len(description) < 8 and len(text) < 200:
        raise ProductLinkError("Trang không có nội dung đọc được (cần đăng nhập hoặc chặn bot) — hãy tạo sản phẩm và dán mô tả vào")
    return {"url": str(resp.url), "title": title, "description": description, "image_url": image, "text": text}


_SYSTEM = (
    "You are a director for short TikTok Shop / affiliate product videos in Vietnam. "
    "You get the text of a product page and, optionally, the product the user has chosen in "
    "their library. Work out what is being sold, its strongest selling points and its real "
    "details, then write a plan for a short ad video of that product. hook: one line, the "
    "opening claim. style/tone: how the ad should feel. Every scene becomes one AI-generated "
    "still image (image_prompt_en, English, photoreal, <= 480 chars, describe shot size, "
    "subject, action, setting, light; refer to 'the product from the reference photo' and "
    "'the model' instead of describing their looks) animated into an 8-second clip "
    "(motion_prompt_en, English, 2-3 beats like '0-3s … 3-6s … 6-8s', locked-off camera) with "
    "one spoken Vietnamese line (narration_vi, natural spoken Vietnamese, ngôi 'mình', <= 24 "
    "words, first line hooks and names the product, last line is a call to action). Use only "
    "facts from the page — never invent specs, prices, discounts or certifications. Use "
    "between 3 and 5 scenes. If a person suits the product, describe a character to generate "
    "(gender, country, vibe, extras_en); otherwise character is null. product_seen: the "
    "product's name as the page states it. scenes: leave empty. match: whether the user's "
    "chosen product is the same kind of thing the page sells; score 1.0 = same kind, 0.0 = "
    "unrelated; explain reason_vi in Vietnamese. Output ONLY the JSON object."
)

# Same shape as the video analysis, minus the beat-by-beat breakdown there is
# no video to read it from.
_SCHEMA = {**reference_video._SCHEMA,
           "required": [r for r in reference_video._SCHEMA["required"] if r != "scenes"]}


#: The ad plan needs more judgement than the card extraction below, but the
#: default gemini-3.8-flash took ~115 s on a long page (apple.com/vn/iphone)
#: while the button promised 10–40 s; 3.5-flash answers the same ask in
#: ~20 s. The route passes the generic default when the user picked no
#: model, so that value means "no pick" here and resolves to this one.
PLAN_MODEL = "gemini-3.5-flash"


async def analyze(url: str, product: Optional[dict], *, scenes: Optional[int] = None,
                  model: Optional[str] = None) -> dict[str, Any]:
    """The adapted plan for the product at ``url``; the fetched page's
    ``title`` / ``image_url`` ride along as ``page``."""
    if not model or model == gemini_api.DEFAULT_MODEL:
        model = PLAN_MODEL
    page = await get_page(url)
    ask = [
        "Write the video plan for the product on this page.",
        reference_video._product_brief(product) if product else
        "No product chosen in the library: plan for the product the page sells; the user will "
        "upload its photo later. match.score = 1.0, relevant = true.",
        f"PRODUCT PAGE ({page['url']}):\n{page['text']}",
    ]
    if scenes:
        n = max(reference_video.MIN_SCENES, min(reference_video.MAX_SCENES, scenes))
        ask.append(f"Use exactly {n} scenes in the plan.")
    try:
        text = await gemini_api.generate_text(
            "\n\n".join(ask), system=_SYSTEM, model=model, response_schema=_SCHEMA, timeout=180.0,
        )
        data = gemini_api.parse_json(text)
    except gemini_api.GeminiAPIError as exc:
        raise ProductLinkError(str(exc)) from exc
    except ValueError as exc:
        raise ProductLinkError(f"Gemini returned invalid JSON: {exc}") from exc
    try:
        analysis = reference_video.normalize(data, product)
    except reference_video.ReferenceVideoError as exc:
        raise ProductLinkError(str(exc)) from exc
    analysis["page"] = {"url": page["url"], "title": page["title"], "image_url": page["image_url"]}
    return analysis


# ── one product, for the product library ───────────────────────────────────

_PRODUCT_SYSTEM = (
    "You fill in a product-library card for a Vietnamese TikTok Shop affiliate from the text of "
    "a product page. Use only facts stated on the page — never invent specs, materials, prices "
    "or promises. name: the product's name in Vietnamese, tidied (drop keyword stuffing, "
    "hashtags and repeated words), <= 80 chars. description: ENGLISH, <= 300 chars, what the "
    "item physically looks like (type, colour, material, shape, distinctive details, size cues) "
    "so an image model can draw it; no marketing words. category: fashion for clothing, shoes, "
    "bags and wearable accessories; cosmetics for beauty and skincare; food for food and drink; "
    "grocery for small everyday goods and phone accessories (phone cases, acrylic stands, cables, "
    "chargers, earphones, hooks, boxes, organisers); home for household appliances and kitchen "
    "gear (pots, pans, blenders, vacuums, fans, cookers, water filters, lamps); else other. price: the current selling price exactly as the page shows it (e.g. '79.434đ'), "
    "empty if absent. selling_points: 3-5 short Vietnamese lines, one per line, the real "
    "benefits and facts from the page, each <= 90 chars. gender: who the product is for — male "
    "(men's / boys'), female (women's / girls'), unisex (both, or the page says nam nữ / unisex), "
    "unknown when it does not matter or is not said (food, phone stands, kitchen gear…). details: up to 10 short "
    "Vietnamese lines, one per line starting with '- ', the other concrete facts the page states that the selling points "
    "do not already cover — ingredients or materials, how it is made, sizes / weights / variants / flavours, how to use, "
    "storage, origin; each <= 120 chars; empty if the page has nothing more. Output ONLY the JSON object."
)

_PRODUCT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "name": {"type": "STRING"},
        "description": {"type": "STRING"},
        "category": {"type": "STRING", "enum": list(CATEGORIES)},
        "price": {"type": "STRING"},
        "selling_points": {"type": "STRING"},
        "gender": {"type": "STRING", "enum": ["male", "female", "unisex", "unknown"]},
        "details": {"type": "STRING"},
    },
    "required": ["name", "description", "category", "price", "selling_points", "gender"],
}

def page_details_note(details: object) -> str:
    """``details`` from the page as the product's notes block ("" if none)."""
    lines = [ln.strip() for ln in str(details or "").splitlines() if ln.strip().strip("-• ")]
    lines = [ln if ln.startswith("- ") else "- " + ln.lstrip("-• ") for ln in lines][:10]
    return ("Chi tiết từ trang sản phẩm:\n" + "\n".join(lines))[:1800] if lines else ""


_PDP_RE = re.compile(r"^(https?://[^/]*tiktok\.com/[a-z]{2}/pdp/\d+)", re.I)


def clean_link(url: str) -> str:
    """The link worth keeping on a product: a TikTok share link carries a
    page of tracking parameters (and ids that identify the sharer), so it
    is cut down to the product page itself."""
    m = _PDP_RE.match(url.strip())
    if m:
        return m.group(1)
    if needs_browser(url):
        # Shopee links carry share / tracking query parameters only.
        return url.strip().split("?", 1)[0].split("#", 1)[0][:500]
    return url.strip().split("#", 1)[0][:500]


def _bigger_image(url: str) -> str:
    """TikTok's og:image is a 260 px thumbnail; the same asset at 800 px is
    served from the same path with the size in the template suffix (no
    signature on it), which is what an image model should be shown."""
    if "susercontent.com" in url:
        # Shopee: "<id>_tn" is the thumbnail of "<id>".
        return re.sub(r"_tn(?=$|[?#])", "", url)
    if "ibyteimg.com" in url:
        return re.sub(r"(resize-(?:webp|jpeg)):\d+:\d+", r"\1:800:800", url)
    return url


#: Filling a product card is plain extraction, so it runs on the light model:
#: measured on the same page, gemini-3.1-flash-lite answered in ~4 s while
#: gemini-3.7/3.8-flash timed out past 40 s (and 3.5-flash took ~21 s, mostly
#: thinking tokens). The ad plan above runs on :data:`PLAN_MODEL`.
EXTRACT_MODEL = "gemini-3.1-flash-lite"


async def extract_product(url: str, *, model: str = EXTRACT_MODEL) -> dict[str, Any]:
    """A product-library draft read from the page at ``url``:
    ``{draft: {name, description, category, price, selling_points, link},
    image_url}``."""
    out = await extract_from_page(await get_page(url), model=model)
    # a pasted affiliate short link (s.shopee.vn/…) is kept on the product: it
    # goes in the first comment of the posts written for it
    out["draft"]["aff_link"] = affiliate_link(url)
    return out


def _gender_guess(*texts: str) -> str:
    from flowboard.services.product_gender import guess

    return guess(*texts)


async def extract_from_page(page: dict[str, Any], *, model: str = EXTRACT_MODEL) -> dict[str, Any]:
    """:func:`extract_product` for a page already read (e.g. an open tab)."""
    try:
        text = await gemini_api.generate_text(
            f"PRODUCT PAGE ({clean_link(page['url'])}):\n{page['text']}",
            system=_PRODUCT_SYSTEM, model=model, response_schema=_PRODUCT_SCHEMA, timeout=120.0,
        )
        data = gemini_api.parse_json(text)
    except gemini_api.GeminiAPIError as exc:
        raise ProductLinkError(str(exc)) from exc
    except ValueError as exc:
        raise ProductLinkError(f"Gemini returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or not str(data.get("name") or "").strip():
        raise ProductLinkError("Không đọc được tên sản phẩm từ trang này")
    category = data.get("category") if data.get("category") in CATEGORIES else "other"
    return {
        "draft": {
            "name": str(data["name"]).strip()[:120],
            "description": str(data.get("description") or "").strip()[:600],
            "category": category,
            "price": str(data.get("price") or "").strip()[:60],
            "selling_points": str(data.get("selling_points") or "").strip()[:2000],
            "gender": (data.get("gender") if data.get("gender") in ("male", "female", "unisex")
                       else _gender_guess(str(data.get("name") or ""), page.get("title") or "")),
            "link": clean_link(page["url"]),
            "aff_link": "",
            # The rest of the page's facts (process, sizes, flavours…): the
            # script writer reads the product's notes too (script_tailor).
            "notes": page_details_note(data.get("details")),
        },
        "image_url": _bigger_image(page["image_url"]),
    }
