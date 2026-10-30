"""Read a channel's own page and review it ("🔎 Xem & đánh giá kênh").

The seller may give a channel its link (Facebook page, TikTok, Instagram,
YouTube, Threads, Zalo OA). :func:`read_page` opens it in the seller's
Chrome through the extension (``read_channel``, extension ≥ 0.6.0 — the
browser is logged in, which a Facebook page needs to show its posts) and
falls back to a plain fetch for public pages. :func:`review` hands the text
to the LLM, which scores the page, lists strengths / what to fix / concrete
suggestions, and — the part the writer uses — describes the style its real
posts already have (``house_style``) with a few sample openings.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError

logger = logging.getLogger(__name__)

MIN_EXTENSION = (0, 6, 0)
READ_TIMEOUT_S = 75.0
MAX_TEXT = 24000
_HOST_RE = re.compile(
    r"^https://([a-z0-9-]+\.)*(facebook\.com|fb\.com|instagram\.com|tiktok\.com|youtube\.com|threads\.net|threads\.com|zalo\.me)/",
    re.I,
)
_LOGIN_RE = re.compile(r"log in to facebook|đăng nhập facebook|log into facebook|bạn phải đăng nhập|you must log in", re.I)

_SYSTEM = (
    "You review a Vietnamese seller's social media page from the raw text of its page (menus, buttons and other UI "
    "noise included — ignore them). Judge only what the text shows; if posts are not visible say so instead of "
    "guessing. Write in Vietnamese, concise and concrete.\n"
    "Output ONLY one JSON object:\n"
    "- page_name: str, followers: str (as shown, or \"\")\n"
    "- summary: 2-3 sentences — what the page is, who it seems to be for, how active it looks\n"
    "- score: integer 1-10 for how well the page is set up to win engagement and sales for this seller's goal\n"
    "- criteria: 4-6 items {name, score 1-10, note} (e.g. nhận diện thương hiệu, độ đều đặn, chất lượng nội dung, "
    "khả năng tương tác, kêu gọi mua hàng)\n"
    "- strengths: 2-5 short items\n"
    "- weaknesses: 2-5 short items\n"
    "- suggestions: 4-6 concrete actions for the next posts\n"
    "- house_style: 2-4 sentences describing how the page's posts are actually written (length, tone, xưng hô, "
    "emoji, hooks, hashtags, formats such as video with yellow subtitles) so new posts can match it\n"
    "- sample_hooks: up to 5 opening lines copied from real posts (verbatim, short)\n"
    "- posts_seen: integer, how many posts you could make out\n"
    "No prose outside the JSON, no code fences."
)


class ChannelPageError(RuntimeError):
    pass


def normalize_link(raw: str) -> str:
    """What the seller pasted → ``https://host/path`` (no trailing slash):
    plain ``tiktok.com/@x`` gets a scheme, ``http://`` becomes ``https://``,
    a share blurb is reduced to its URL."""
    from flowboard.services.video_fetch import extract_url

    text = (raw or "").strip()
    if not text:
        return ""
    url = extract_url(text) or text.split()[0]
    if not re.match(r"^[a-z]+://", url, re.I):
        url = "https://" + url.lstrip("/")
    url = re.sub(r"^http://", "https://", url, flags=re.I)
    return url.rstrip("/")


def link_allowed(url: str) -> bool:
    return bool(_HOST_RE.match((url or "").strip().rstrip("/") + "/"))


def _version(v: Optional[str]) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in (v or "0").split("."))
    except ValueError:
        return (0,)


async def read_page(url: str) -> dict[str, Any]:
    """``{url, title, description, text, via}`` for the channel page."""
    url = (url or "").strip()
    if not link_allowed(url):
        raise ChannelPageError("Link kênh phải là Facebook, TikTok, Instagram, YouTube, Threads hoặc Zalo (https://…)")
    from flowboard.services.flow_client import get_flow_client

    client = get_flow_client()
    ext_error = ""
    if client.connected and _version(client.extension_version) >= MIN_EXTENSION:
        resp = await client._send("read_channel", {"url": url}, timeout=READ_TIMEOUT_S)
        if resp.get("error"):
            ext_error = str(resp["error"])
        else:
            try:
                raw = resp.get("data")
                data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except (TypeError, ValueError):
                data = {}
            text = str(data.get("text") or "")
            if _LOGIN_RE.search(text[:2000]) and len(text) < 4000:
                raise ChannelPageError("Trang yêu cầu đăng nhập — mở trang đó trong Chrome, đăng nhập rồi thử lại.")
            if len(text) >= 200:
                return {"url": data.get("url") or url, "title": data.get("title") or "", "via": "chrome",
                        "description": data.get("description") or "", "text": text[:MAX_TEXT]}
            ext_error = "trang chưa hiện nội dung"
    elif client.connected:
        ext_error = (f"extension đang là bản {client.extension_version or 'cũ'} — mở chrome://extensions, bấm ↻ Reload ở "
                     "DFlow extension (cần bản 0.6.0)")
    else:
        ext_error = "extension chưa kết nối"
    # Public pages (YouTube, TikTok…) can still be read without the browser.
    try:
        from flowboard.services.product_link import fetch_page

        page = await fetch_page(url)
        text = str(page.get("text") or "")
        if len(text) >= 300 and not _LOGIN_RE.search(text[:2000]):
            return {"url": url, "title": page.get("title") or "", "description": page.get("description") or "",
                    "text": text[:MAX_TEXT], "via": "fetch"}
    except Exception as exc:  # noqa: BLE001 — the fallback is best effort
        logger.info("channel_page: plain fetch of %s failed: %s", url[:80], exc)
    raise ChannelPageError(f"Không đọc được trang kênh qua Chrome ({ext_error}).")


_NOISE_LINE = re.compile(r"^(facebook|instagram|tiktok|·|…)?$", re.I)


def clean_text(text: str) -> str:
    """Page text without the UI noise that would crowd out the posts:
    Facebook renders hundreds of hidden "Facebook" spans, blank separators
    and the same line twice in a row."""
    out: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if _NOISE_LINE.match(line):
            continue
        if out and out[-1] == line:
            continue
        out.append(line)
    return "\n".join(out)


def _parse(text: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ChannelPageError("AI không trả về đánh giá dạng JSON")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise ChannelPageError(f"đánh giá JSON hỏng: {exc}") from exc

    def clamp(v: Any) -> int:
        try:
            return max(1, min(10, int(round(float(v)))))
        except (TypeError, ValueError):
            return 0

    def strs(key: str, n: int) -> list[str]:
        return [str(x).strip() for x in (data.get(key) or []) if str(x).strip()][:n]

    out: dict[str, Any] = {
        "page_name": str(data.get("page_name") or "").strip()[:120],
        "followers": str(data.get("followers") or "").strip()[:40],
        "summary": str(data.get("summary") or "").strip(),
        "score": clamp(data.get("score")),
        "criteria": [{"name": str(c.get("name") or "").strip(), "score": clamp(c.get("score")), "note": str(c.get("note") or "").strip()}
                     for c in (data.get("criteria") or []) if isinstance(c, dict) and c.get("name")][:6],
        "strengths": strs("strengths", 6),
        "weaknesses": strs("weaknesses", 6),
        "suggestions": strs("suggestions", 8),
        "house_style": str(data.get("house_style") or "").strip(),
        "sample_hooks": strs("sample_hooks", 5),
    }
    try:
        out["posts_seen"] = max(0, int(data.get("posts_seen") or 0))
    except (TypeError, ValueError):
        out["posts_seen"] = 0
    if not out["summary"]:
        raise ChannelPageError("AI trả về đánh giá rỗng")
    return out


async def review(channel: dict, page: dict, *, timeout: float = 150.0) -> dict[str, Any]:
    """The LLM's review of ``page`` for ``channel`` (fields from the form give it the goal)."""
    from flowboard.services.channels import channel_block

    prompt = "\n\n".join(filter(None, [
        "SELLER'S CHANNEL (as they describe it):\n" + channel_block({**channel, "brainstorm": None, "page_review": None}),
        f"PAGE URL: {page.get('url')}\nPAGE TITLE: {page.get('title') or '-'}\nMETA DESCRIPTION: {page.get('description') or '-'}",
        "PAGE TEXT (raw, includes UI noise):\n" + clean_text(str(page.get("text") or ""))[:MAX_TEXT],
        "Review the page now.",
    ]))
    try:
        text = await run_llm("auto_prompt", prompt, system_prompt=_SYSTEM, timeout=timeout)
    except LLMError as exc:
        raise ChannelPageError(f"AI chưa đánh giá được: {exc}") from exc
    out = _parse(text)
    out["at"] = datetime.now(timezone.utc).isoformat()
    out["url"] = page.get("url") or channel.get("link")
    out["via"] = page.get("via")
    return out
