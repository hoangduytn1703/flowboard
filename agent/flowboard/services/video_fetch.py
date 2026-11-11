"""Download a short video from a pasted link (or a whole "share" blurb).

Douyin's share button copies a sentence with the link inside
("6.10 … 合集:… https://v.douyin.com/xxxx/ 复制此链接…"); :func:`extract_url`
digs the URL out. Douyin itself refuses yt-dlp without fresh cookies, so
Douyin links go through the mobile share page the way VieDub does: follow
the short link, read ``window._ROUTER_DATA`` for the item (title, no-
watermark play url) and download that file directly. Everything else is
yt-dlp (``routes.reference_video._run_ytdlp``).
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/17.0 Mobile/15E148 Safari/604.1")
DOUYIN_HOSTS = ("douyin.com", "iesdouyin.com")
MAX_DIRECT_BYTES = 300 << 20
_URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")


class FetchError(RuntimeError):
    pass


def extract_url(text: str) -> Optional[str]:
    """The first http(s) URL in ``text`` (trailing punctuation dropped), or None."""
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(".,;:!?)'\"") if m else None


def is_douyin(url: str) -> bool:
    host = (httpx.URL(url).host or "").lower() if url else ""
    return any(host == h or host.endswith("." + h) for h in DOUYIN_HOSTS)


def douyin_item(page: str) -> Optional[dict[str, Any]]:
    """The video item from a share page's ``window._ROUTER_DATA``."""
    m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", page, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    for v in (data.get("loaderData") or {}).values():
        try:
            return v["videoInfoRes"]["item_list"][0]
        except (KeyError, IndexError, TypeError):
            continue
    return None


def douyin_info(url: str, *, client: Optional[httpx.Client] = None) -> dict[str, Any]:
    """``{id, title, duration, direct_url}`` for a Douyin link via the mobile share page."""
    own = client is None
    c = client or httpx.Client(headers={"User-Agent": MOBILE_UA}, follow_redirects=True, timeout=20)
    try:
        r = c.get(url)
        final = str(r.url)
        m = re.search(r"/(?:video|note|slides)/(\d+)", final) or re.search(r"(\d{15,})", final)
        if not m:
            raise FetchError(f"không đọc được ID video Douyin từ link ({final[:80]})")
        vid = m.group(1)
        # The first hit of a session often only sets cookies; ask again in the same session.
        item, page = None, r.text
        for attempt in range(4):
            if attempt:
                time.sleep(1)
                page = c.get(f"https://www.iesdouyin.com/share/video/{vid}/").text
            item = douyin_item(page)
            if item:
                break
        if not item:
            if "_ROUTER_DATA" not in page:
                raise FetchError("Douyin đang chặn tạm thời (trang kiểm tra chống bot) — đợi 10–30 phút rồi thử lại")
            raise FetchError("Douyin không trả dữ liệu: video đã xoá, riêng tư, hoặc cần đăng nhập")
        video = item.get("video") or {}
        urls = (video.get("play_addr") or {}).get("url_list") or []
        if not urls:
            raise FetchError("link này không phải video (bài đăng ảnh?)")
        return {"id": vid, "title": str(item.get("desc") or vid), "duration": (video.get("duration") or 0) / 1000,
                "direct_url": urls[0].replace("playwm", "play")}
    except httpx.HTTPError as exc:
        raise FetchError(f"không mở được trang Douyin: {exc}") from exc
    finally:
        if own:
            c.close()


def download_direct(url: str, dest: Path, *, referer: str = "https://www.douyin.com/", timeout: float = 300,
                    stop: Optional[Any] = None) -> None:
    tmp = dest.with_suffix(".part")
    try:
        with httpx.Client(headers={"User-Agent": MOBILE_UA, "Referer": referer}, follow_redirects=True,
                          timeout=httpx.Timeout(30, read=timeout)) as c, c.stream("GET", url) as r:
            r.raise_for_status()
            got = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 18):
                    if stop is not None and stop():
                        raise FetchError(STOPPED)
                    f.write(chunk)
                    got += len(chunk)
                    if got > MAX_DIRECT_BYTES:
                        raise FetchError("video quá 300 MB")
        tmp.replace(dest)
    except httpx.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        raise FetchError(f"tải video Douyin lỗi: {exc}") from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


#: what a download stopped by the seller says (callers show it as it is)
STOPPED = "Đã dừng theo yêu cầu"


def fetch_video(text: str, media_id: str, out_dir: Path, *, max_duration_s: Optional[float] = None,
                stop: Optional[Any] = None) -> tuple[Path, str]:
    """Download the video linked in ``text`` as ``out_dir/<media_id>.mp4``. ``stop()`` turning true ends the
    download at once (:class:`FetchError` saying :data:`STOPPED`).
    Returns ``(path, title)``; raises :class:`FetchError`. Douyin tells the
    duration before the download, so an over-long video (``max_duration_s``)
    is refused without fetching it."""
    url = extract_url(text)
    if not url:
        raise FetchError("Không thấy link (http/https) trong nội dung đã dán")
    from flowboard.routes.reference_video import _host_allowed, _run_ytdlp

    if not _host_allowed(url):
        raise FetchError("Link phải là TikTok, Douyin, YouTube, Instagram, Facebook hoặc X")
    out_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    if is_douyin(url):
        try:
            info = douyin_info(url)
            if max_duration_s and info["duration"] > max_duration_s:
                # Far past the limit: almost always a 合集 (compilation) link, not one clip.
                hint = " (link này là một tuyển tập/合集; chọn một video lẻ)" if info["duration"] > 2 * max_duration_s else ""
                raise FetchError(f"video dài {info['duration'] / 60:.0f} phút — tối đa {max_duration_s / 60:.0f} phút{hint}") from None
            dest = out_dir / f"{media_id}.mp4"
            download_direct(info["direct_url"], dest, **({"stop": stop} if stop is not None else {}))
            logger.info("video_fetch: douyin %s → %s (%.0fs)", info["id"], media_id, info["duration"])
            return dest, info["title"]
        except FetchError as exc:
            if "tối đa" in str(exc) or str(exc) == STOPPED:
                raise
            errors.append(f"Douyin: {exc}")
    path, title, err = _run_ytdlp(url, media_id, max_duration_s, **({"stop": stop} if stop is not None else {}))
    if path is None:
        if err == STOPPED:
            raise FetchError(STOPPED)
        errors.append(f"yt-dlp: {err}")
        raise FetchError(" · ".join(errors))
    return path, title
