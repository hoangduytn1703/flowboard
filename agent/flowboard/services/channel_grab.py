"""📡 Cào video kênh — the videos of a source channel, listed so the seller picks what to work on.

Paste a channel link (YouTube channel / playlist, TikTok account) → yt-dlp lists its newest videos without
downloading anything (title, views, likes, length, date, cover) → they are kept with the account
(:class:`GrabChannel` / :class:`GrabVideo`) and shown as a grid that sorts and filters by views / date / length, with
an optional AI pick from a request ("chỉ lấy video về vũ trụ, trên 100k view"). The ones picked are downloaded
(an Asset each, like any other video of the account) and go on to "✂️ Cắt video" / "🎙 Lồng tiếng" as files.

YouTube and TikTok are listed by yt-dlp, no login needed (tried 13/11). Douyin and Bilibili give an account's list
only to a real, signed-in browser (a plain request gets 403 "ArgusSecurityPlugin" / 412 — tried 13/11; yt-dlp has no
Douyin account extractor and its Bilibili one is refused with 352), so those two are read through the seller's own
Chrome: the extension (≥ 0.7.1, ``list_channel``) opens the page in a window, keeps what the page's own list
requests bring back while it scrolls / pages, and closes it. Nothing is signed or solved on the seller's behalf — a
login or a captcha the site asks for is theirs to answer in that window. Facebook and Instagram are not listed.

Scans and downloads run in threads and live in memory (``SCANS`` / ``DOWNLOADS``): a restart forgets the ones in
flight; what they finished is in the database.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

import httpx
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Asset, GrabChannel, GrabMark, GrabVideo
from flowboard.services import media as media_service
from flowboard.timestamps import utc_iso

logger = logging.getLogger(__name__)

PLATFORMS: dict[str, dict[str, str]] = {
    "youtube": {"label": "YouTube", "example": "https://www.youtube.com/@tenkenh", "via": "ytdlp"},
    "tiktok": {"label": "TikTok", "example": "https://www.tiktok.com/@tenkenh", "via": "ytdlp"},
    "douyin": {"label": "Douyin", "example": "https://www.douyin.com/user/MS4wLjABAAAA…", "via": "chrome"},
    # bilibili.com (the Chinese site) only — bilibili.tv, the international one, is another service (see parse_channel)
    "bilibili": {"label": "Bilibili", "example": "https://space.bilibili.com/123456", "via": "chrome", "beta": "1",
                 "note": "Chỉ bilibili.com (bản Trung Quốc, link space.bilibili.com/…) — chưa đọc được bilibili.tv (bản quốc tế)."},
}
#: read through the seller's own Chrome (the extension's ``list_channel``): the site wants a signed-in browser
BROWSER_PLATFORMS = ("douyin", "bilibili")
MIN_EXTENSION = (0, 7, 1)
BROWSER_TIMEOUT_S = 150
#: the agent's event loop (set at startup): scan threads reach the extension through it
LOOP: Any = None
#: how many of the newest videos one scan reads (per tab on YouTube: videos, shorts); any number up to MAX_LIMIT
LIMITS = [30, 60, 100, 200, 500, 1000]
MAX_LIMIT = 3000
DEFAULT_LIMIT = 60
LIST_TIMEOUT_S = 240
MAX_TAGS, TAG_MAX = 6, 24
#: the labels of one video, and the ready-made ones the page offers first (any other text works too)
MAX_MARKS = 10
MARK_PRESETS = ["Đã xử lý", "Đã đăng", "Để dành", "Bỏ qua"]
#: a download refuses a longer video (the tools after it take an hour at most)
MAX_DURATION_S = 60 * 60
DOWNLOAD_PARALLEL = 2
SCAN_PARALLEL = 2
THUMB_PARALLEL = 8
THUMB_MAX_BYTES = 3 * 1024 * 1024
PICK_MAX = 300
LLM_TIMEOUT_S = 180
VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov")

NOT_SUPPORTED = ("Hiện đọc được danh sách video của kênh YouTube, TikTok, Douyin và Bilibili. Facebook, Instagram không cho đọc "
                 "danh sách kênh — với các nền tảng đó, dán từng link video vào ✂️ Cắt video hoặc 🎙 Lồng tiếng.")
STOPPED = "Đã dừng theo yêu cầu"


class GrabError(RuntimeError):
    """Said to the person in front of the screen."""


# ── the channel a link points at ───────────────────────────────────────────

_SHORT_HOSTS = ("vt.tiktok.com", "vm.tiktok.com", "v.douyin.com", "b23.tv")


def _resolve(url: str) -> str:
    """Where a short share link ends up (vt.tiktok.com/…)."""
    try:
        with httpx.Client(follow_redirects=True, timeout=10.0, headers={"User-Agent": "Mozilla/5.0"}) as c:
            return str(c.head(url).url)
    except httpx.HTTPError:
        return url


def parse_channel(text: str) -> dict[str, str]:
    """``{platform, key, url, handle}`` of the channel a pasted link is about. Raises :class:`GrabError` with what to
    paste instead (a single video's link, an unsupported site)."""
    from flowboard.services.video_fetch import extract_url

    raw = (text or "").strip()
    url = extract_url(raw)
    if not url:
        if re.fullmatch(r"(www\.|space\.)?(youtube\.com|tiktok\.com|douyin\.com|bilibili\.com)/\S+", raw, re.I):
            url = "https://" + raw
        else:
            raise GrabError("Dán link kênh, ví dụ https://www.youtube.com/@tenkenh hoặc https://www.tiktok.com/@tenkenh")
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host in _SHORT_HOSTS:
        p = urlparse(_resolve(url))
        host = (p.hostname or "").lower()
    host = re.sub(r"^(www|m)\.", "", host)
    path = p.path.rstrip("/")
    if host == "youtube.com":
        m = re.match(r"^/(@[^/]+)", path)
        if m:
            handle = m.group(1)
            return {"platform": "youtube", "key": f"youtube:{handle.lower()}", "url": f"https://www.youtube.com/{handle}", "handle": handle}
        m = re.match(r"^/channel/(UC[\w-]{10,})", path)
        if m:
            return {"platform": "youtube", "key": f"youtube:{m.group(1)}", "url": f"https://www.youtube.com/channel/{m.group(1)}", "handle": ""}
        m = re.match(r"^/(c|user)/([^/]+)", path)
        if m:
            return {"platform": "youtube", "key": f"youtube:{m.group(1)}/{m.group(2).lower()}",
                    "url": f"https://www.youtube.com/{m.group(1)}/{m.group(2)}", "handle": m.group(2)}
        if path == "/playlist":
            lid = (parse_qs(p.query).get("list") or [""])[0]
            if re.fullmatch(r"[\w-]{10,}", lid):
                return {"platform": "youtube", "key": f"youtube:list:{lid}", "url": f"https://www.youtube.com/playlist?list={lid}", "handle": ""}
        raise GrabError("Đây là link một video YouTube — cần link kênh. Mở video, bấm vào tên kênh rồi copy link "
                        "(dạng youtube.com/@tenkenh), hoặc dán link một playlist.")
    if host == "youtu.be":
        raise GrabError("Đây là link một video YouTube — cần link kênh (dạng youtube.com/@tenkenh).")
    if host == "tiktok.com":
        m = re.match(r"^/(@[\w.-]+)", path)
        if m:
            handle = m.group(1)
            return {"platform": "tiktok", "key": f"tiktok:{handle.lower()}", "url": f"https://www.tiktok.com/{handle}", "handle": handle}
        raise GrabError("Không thấy tên kênh trong link TikTok — dán link dạng tiktok.com/@tenkenh.")
    if host in ("douyin.com", "iesdouyin.com"):
        m = re.match(r"^/(?:share/)?user/([\w.-]{20,})", path)
        if m:
            return {"platform": "douyin", "key": f"douyin:{m.group(1)}", "url": f"https://www.douyin.com/user/{m.group(1)}", "handle": ""}
        raise GrabError("Đây không phải link trang cá nhân Douyin — mở trang của kênh (dạng douyin.com/user/MS4w…) rồi copy link, "
                        "hoặc trong app Douyin bấm Chia sẻ trang cá nhân → Sao chép liên kết.")
    if host == "bilibili.tv":
        # the international site is another service: its API resets connections from anything but a browser on
        # Vietnamese networks (curl, httpx and yt-dlp all tried 13/11), so neither the list nor the videos can be fetched
        raise GrabError("Đây là Bilibili bản quốc tế (bilibili.tv) — tool mới đọc được bilibili.com (dạng space.bilibili.com/123456). "
                        "Máy chủ của bilibili.tv đang ngắt kết nối từ công cụ tải nên cả danh sách lẫn video đều chưa lấy được.")
    if host in ("space.bilibili.com", "bilibili.com"):
        # a visitor from abroad gets a language in front: space.bilibili.com/en/397490386, /zh-CN/…
        loc = r"(?:[a-z]{2}(?:-[A-Za-z]{2,4})?/)?"
        m = (re.match(rf"^/{loc}(\d{{1,20}})(?:/|$)", path) if host.startswith("space.")
             else re.match(rf"^/{loc}space/(\d{{1,20}})", path))
        if m:
            return {"platform": "bilibili", "key": f"bilibili:{m.group(1)}",
                    "url": f"https://space.bilibili.com/{m.group(1)}/upload/video", "handle": ""}
        raise GrabError("Đây là link một video Bilibili — cần link trang của kênh (dạng space.bilibili.com/123456): mở video, bấm vào tên người đăng.")
    raise GrabError(NOT_SUPPORTED)


def normalize_tags(raw: Any) -> list[str]:
    out: list[str] = []
    for t in raw if isinstance(raw, list) else []:
        tag = re.sub(r"\s+", " ", str(t or "")).strip().lstrip("#")[:TAG_MAX]
        if tag and tag.lower() not in (x.lower() for x in out):
            out.append(tag)
    return out[:MAX_TAGS]


def normalize_limit(n: Any) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return min(max(v, 5), MAX_LIMIT)


def list_timeout(limit: int) -> int:
    """A long list takes longer: ~a quarter second a video on top of the base (3000 videos ≈ 16 minutes)."""
    return LIST_TIMEOUT_S + max(0, limit) // 4


def browser_timeout_ms(limit: int) -> int:
    """How long the extension may scroll / page the channel (Douyin brings ~18 videos a page, ~2 s each)."""
    return min(60000 + max(0, limit) * 450, 30 * 60 * 1000)


def normalize_marks(raw: Any) -> list[str]:
    out: list[str] = []
    for t in raw if isinstance(raw, list) else []:
        tag = re.sub(r"\s+", " ", str(t or "")).strip().lstrip("#")[:TAG_MAX]
        if tag and tag.lower() not in (x.lower() for x in out):
            out.append(tag)
    return out[:MAX_MARKS]


# ── where this account's things are ────────────────────────────────────────

def _owner() -> str:
    """The account whose data folder is open — work started for another account is not written into this one."""
    return str(media_service.MEDIA_CACHE_DIR)


def _dir() -> Path:
    return media_service.MEDIA_CACHE_DIR.parent / "grab"


def thumb_file(video_id: int) -> Path:
    return _dir() / "thumbs" / f"{video_id}.img"


def avatar_file(channel_id: int) -> Path:
    return _dir() / "avatars" / f"{channel_id}.img"


def image_type(path: Path) -> str:
    try:
        head = path.open("rb").read(12)
    except OSError:
        return "image/jpeg"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _safe_image_url(url: str) -> bool:
    p = urlparse(url or "")
    host = (p.hostname or "").lower()
    return p.scheme == "https" and "." in host and not re.fullmatch(r"[\d.]+", host) and host != "localhost"


def fetch_image(url: str, dest: Path) -> bool:
    """A cover / avatar kept on this machine (TikTok's links expire in a couple of days)."""
    if not _safe_image_url(url):
        return False
    try:
        with httpx.Client(follow_redirects=True, timeout=15.0, headers={"User-Agent": "Mozilla/5.0"}) as c:
            r = c.get(url)
            if r.status_code != 200 or not r.content or len(r.content) > THUMB_MAX_BYTES:
                return False
            if not (r.headers.get("content-type") or "image/").startswith("image/"):
                return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(r.content)
        tmp.replace(dest)
        return True
    except (httpx.HTTPError, OSError):
        return False


def local_media(media_id: Optional[str]) -> Optional[Path]:
    """The downloaded file on this machine (the row may say downloaded from the other machine)."""
    if not media_id:
        return None
    for ext in VIDEO_EXTS:
        p = media_service.MEDIA_CACHE_DIR / f"{media_id}{ext}"
        if p.is_file():
            return p
    return None


# ── listing a channel (yt-dlp, nothing downloaded) ─────────────────────────

def listing_targets(platform: str, url: str, key: str) -> list[tuple[str, str]]:
    """``[(url to list, kind of its videos)]`` — a YouTube channel has two shelves."""
    if platform == "youtube" and ":list:" not in key:
        return [(url + "/videos", "video"), (url + "/shorts", "short")]
    return [(url, "video")]


def _list(url: str, limit: int, stop: Optional[Callable[[], bool]] = None) -> dict[str, Any]:
    """yt-dlp's flat listing of ``url`` as a dict. Raises :class:`GrabError`."""
    import json
    import subprocess

    from flowboard.services import ytdlp as ytdlp_tool
    from flowboard.services.proc import Stopped, run_stoppable

    try:
        ytdlp = ytdlp_tool.ensure()
    except ytdlp_tool.YtdlpError as exc:
        raise GrabError(f"Chưa có công cụ đọc kênh (yt-dlp): {exc}") from exc
    cmd = [ytdlp, "--no-plugin-dirs", "--flat-playlist", "-J", "--no-warnings", "--encoding", "utf-8",
           "--playlist-end", str(limit), "--extractor-args", "youtubetab:approximate_date", *ytdlp_tool.js_args(), url]
    try:
        proc = run_stoppable(cmd, list_timeout(limit), stop)
    except Stopped as exc:
        raise GrabError(STOPPED) from exc
    except subprocess.TimeoutExpired as exc:
        raise GrabError(f"Đọc kênh quá {list_timeout(limit) // 60} phút — thử lại với ít video hơn") from exc
    except OSError as exc:
        raise GrabError(f"Không chạy được yt-dlp: {exc}") from exc
    out = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not out:
        err = proc.stderr.decode("utf-8", "replace").strip()
        tail = [l for l in err.splitlines() if l.startswith("ERROR")] or err.splitlines()[-2:]
        raise GrabError(" ".join(tail)[-300:] or f"yt-dlp thoát mã {proc.returncode}")
    try:
        data = json.loads(out)
    except ValueError as exc:
        raise GrabError("yt-dlp trả dữ liệu không đọc được") from exc
    if not isinstance(data, dict):
        raise GrabError("yt-dlp trả dữ liệu không đọc được")
    return data


def _int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _aware(dt: datetime) -> datetime:
    """SQLite hands a stored UTC time back without its zone."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _when(e: dict[str, Any]) -> Optional[datetime]:
    ts = e.get("timestamp") or e.get("release_timestamp")
    try:
        if ts:
            return datetime.fromtimestamp(float(ts), timezone.utc)
        day = str(e.get("upload_date") or "")
        if re.fullmatch(r"\d{8}", day):
            return datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _cover(e: dict[str, Any], platform: str, vid: str) -> str:
    thumbs = [t for t in (e.get("thumbnails") or []) if isinstance(t, dict) and t.get("url")]
    sized = [t for t in thumbs if (_int(t.get("width")) or 0) > 0]
    if sized:
        fit = [t for t in sized if (t.get("width") or 0) <= 800] or sized
        return str(max(fit, key=lambda t: t.get("width") or 0)["url"])
    if thumbs:
        return str(thumbs[-1]["url"])
    if e.get("thumbnail"):
        return str(e["thumbnail"])
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if platform == "youtube" else ""


_HIDDEN = {"subscriber_only", "premium_only", "needs_auth", "private"}


def entry_rows(data: dict[str, Any], platform: str, kind: str) -> list[dict[str, Any]]:
    """The videos of one listing, in its own order (newest first). A channel root lists its shelves as nested
    playlists — those are opened too."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def walk(entries: Any, kind: str) -> None:
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            if e.get("_type") == "playlist" or isinstance(e.get("entries"), list):
                walk(e.get("entries"), "short" if "short" in str(e.get("title") or "").lower() else kind)
                continue
            vid = str(e.get("id") or "").strip()
            url = str(e.get("url") or e.get("webpage_url") or "").strip()
            if not vid or not url.startswith("http") or vid in seen:
                continue
            if e.get("live_status") in ("is_upcoming", "is_live") or e.get("availability") in _HIDDEN:
                continue
            seen.add(vid)
            dur = e.get("duration")
            rows.append({
                "key": f"{platform}:{vid}", "url": url[:500], "kind": "short" if "/shorts/" in url else kind,
                "title": re.sub(r"\s+", " ", str(e.get("title") or "")).strip()[:300],
                "duration_s": float(dur) if isinstance(dur, (int, float)) and dur > 0 else None,
                "views": _int(e.get("view_count")), "likes": _int(e.get("like_count")), "comments": _int(e.get("comment_count")),
                "published_at": _when(e), "thumb": _cover(e, platform, vid)[:1000], "position": len(rows),
            })

    walk(data.get("entries"), kind)
    return rows


def channel_meta(data: dict[str, Any]) -> dict[str, Any]:
    """Name, followers, description and avatar a listing says about its channel (what is missing stays out)."""
    first = next((e for e in (data.get("entries") or []) if isinstance(e, dict)), {})
    name = str(data.get("channel") or data.get("uploader") or first.get("channel") or first.get("uploader") or "").strip()
    out: dict[str, Any] = {}
    if name:
        out["name"] = name[:120]
    if _int(data.get("channel_follower_count")) is not None:
        out["followers"] = _int(data.get("channel_follower_count"))
    if data.get("description"):
        out["description"] = re.sub(r"\s+", " ", str(data["description"])).strip()[:400]
    thumbs = [t for t in (data.get("thumbnails") or []) if isinstance(t, dict) and t.get("url")]
    avatar = next((t for t in thumbs if "avatar" in str(t.get("id") or "")), None)
    if avatar:
        out["avatar"] = str(avatar["url"])[:1000]
    return out


# ── listing through the seller's Chrome (Douyin, Bilibili) ─────────────────

def _version(v: Optional[str]) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in (v or "0").split("."))
    except ValueError:
        return (0,)


def _list_via_chrome(url: str, limit: int, label: str, stop: Optional[Callable[[], bool]] = None) -> dict[str, Any]:
    """What the extension gathered on the channel's page in the seller's Chrome. Raises :class:`GrabError` saying
    what the seller has to do (connect / reload the extension, log in, answer a captcha)."""
    import asyncio
    import json

    from flowboard.services.flow_client import get_flow_client

    client = get_flow_client()
    if LOOP is None or not client.connected:
        raise GrabError(f"Kênh {label} được đọc qua Chrome của bạn — extension DFlow chưa kết nối. Mở Chrome có extension DFlow "
                        "(xem thẻ Thiết lập ở trang Hôm nay) rồi bấm Quét lại.")
    if _version(client.extension_version) < MIN_EXTENSION:
        raise GrabError(f"Extension DFlow đang là bản {client.extension_version or 'cũ'} — đọc kênh {label} cần bản "
                        f"{'.'.join(map(str, MIN_EXTENSION))}: mở chrome://extensions, bấm ↻ (Reload) ở DFlow Bridge rồi Quét lại.")
    wait_s = browser_timeout_ms(limit) / 1000 + BROWSER_TIMEOUT_S
    fut = asyncio.run_coroutine_threadsafe(
        client._send("list_channel", {"url": url, "limit": limit, "timeoutMs": browser_timeout_ms(limit)},
                     timeout=wait_s), LOOP)
    end = time.time() + wait_s + 5
    while True:
        try:
            resp = fut.result(timeout=0.3)
            break
        except TimeoutError:
            if stop is not None and stop():
                fut.cancel()
                raise GrabError(STOPPED) from None
            if time.time() > end:
                fut.cancel()
                raise GrabError(f"Chrome không trả lời khi đọc kênh {label} — thử Quét lại.") from None
        except Exception as exc:  # noqa: BLE001 — asyncio.TimeoutError of the send, a closed socket…
            raise GrabError(f"Chrome không trả lời khi đọc kênh {label} ({type(exc).__name__}) — thử Quét lại.") from exc
    err = str(resp.get("error") or "")
    if err:
        if err == "LIST_CHANNEL_BUSY":
            raise GrabError("Chrome đang đọc một kênh khác — đợi xong rồi Quét lại.")
        if err == "extension_disconnected":
            raise GrabError(f"Kênh {label} được đọc qua Chrome của bạn — extension DFlow chưa kết nối.")
        raise GrabError(f"Extension không đọc được kênh {label}: {err[:160]}")
    try:
        raw = resp.get("data")
        data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (TypeError, ValueError):
        data = {}
    return data


def browser_rows(data: dict[str, Any], platform: str, label: str) -> list[dict[str, Any]]:
    """The extension's answer as rows (newest first, as the page lists them). Raises :class:`GrabError` with what the
    page wanted when it gave nothing (a login, a captcha)."""
    rows: list[dict[str, Any]] = []
    for it in data.get("items") if isinstance(data.get("items"), list) else []:
        if not isinstance(it, dict) or it.get("images"):
            continue  # a photo post has no video to take
        vid = re.sub(r"[^\w-]", "", str(it.get("id") or ""))[:40]
        if not vid:
            continue
        dur = it.get("duration_s")
        if dur is None and _int(it.get("duration_ms")):
            dur = _int(it.get("duration_ms")) / 1000.0  # type: ignore[operator]
        cover = str(it.get("cover") or "")
        cover = "https:" + cover if cover.startswith("//") else cover.replace("http://", "https://", 1)
        created = _int(it.get("created"))
        rows.append({
            "key": f"{platform}:{vid}",
            "url": f"https://www.douyin.com/video/{vid}" if platform == "douyin" else f"https://www.bilibili.com/video/{vid}",
            "kind": "video", "title": re.sub(r"\s+", " ", str(it.get("title") or "")).strip()[:300],
            "duration_s": float(dur) if isinstance(dur, (int, float)) and dur > 0 else None,
            "views": _int(it.get("views")) or None, "likes": _int(it.get("likes")), "comments": _int(it.get("comments")),
            "published_at": datetime.fromtimestamp(created, timezone.utc) if created and created > 0 else None,
            "thumb": cover[:1000], "position": len(rows),
        })
    if rows:
        return rows
    site = "douyin.com" if platform == "douyin" else "bilibili.com"
    if data.get("captcha"):
        raise GrabError(f"{label} đang hỏi mã xác minh (captcha) — mở {site} trong Chrome, làm xong bước xác minh rồi bấm Quét lại.")
    if platform == "bilibili" and data.get("refused"):
        raise GrabError("Bilibili đang tạm từ chối máy này (quét nhiều lượt liền nhau khi chưa đăng nhập) — đăng nhập bilibili.com trong "
                        "Chrome có extension DFlow, hoặc đợi vài phút rồi bấm Quét lại.")
    if data.get("login") or data.get("refused"):
        # a visitor is shown a handful of links without views or dates — not worth saving as "the channel"
        raise GrabError(f"{label} chỉ cho xem danh sách video khi đã đăng nhập — mở {site} trong Chrome (cửa sổ có extension DFlow), "
                        "đăng nhập tài khoản của bạn rồi bấm Quét lại.")
    # nothing came through the page's list requests: the links the page itself shows (titles only, no dates)
    for it in data.get("dom") if isinstance(data.get("dom"), list) else []:
        vid = re.sub(r"[^\w-]", "", str((it or {}).get("id") or ""))[:40] if isinstance(it, dict) else ""
        if vid:
            cover = str(it.get("cover") or "")
            rows.append({"key": f"{platform}:{vid}",
                         "url": f"https://www.douyin.com/video/{vid}" if platform == "douyin" else f"https://www.bilibili.com/video/{vid}",
                         "kind": "video", "title": re.sub(r"\s+", " ", str(it.get("title") or "")).strip()[:300],
                         "duration_s": None, "views": None, "likes": None, "comments": None, "published_at": None,
                         "thumb": ("https:" + cover if cover.startswith("//") else cover)[:1000], "position": len(rows)})
    if rows:
        return rows
    raise GrabError(f"Trang {label} không hiện video nào — kiểm tra link kênh, hoặc mở trang đó trong Chrome xem có video không rồi Quét lại.")


def browser_meta(data: dict[str, Any], platform: str, url: str) -> dict[str, Any]:
    """The channel's name / avatar / followers: what the page said, topped up by the site's public profile card."""
    out: dict[str, Any] = {}
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    if user.get("name"):
        out["name"] = str(user["name"])[:120]
    if str(user.get("avatar") or "").startswith("http"):
        out["avatar"] = str(user["avatar"])[:1000]
    if _int(user.get("followers")):
        out["followers"] = _int(user.get("followers"))
    try:
        ident = url.rstrip("/").split("/user/")[-1] if platform == "douyin" else re.search(r"space\.bilibili\.com/(\d+)", url).group(1)  # type: ignore[union-attr]
        from flowboard.services.video_fetch import MOBILE_UA

        # (Douyin's card answers a phone's browser; a bare "Mozilla/5.0" gets an empty body)
        with httpx.Client(timeout=10.0, headers={"User-Agent": MOBILE_UA, "Referer": f"https://www.{platform}.com/"}) as c:
            if platform == "douyin":
                info = (c.get("https://www.iesdouyin.com/web/api/v2/user/info/", params={"sec_uid": ident}).json() or {}).get("user_info") or {}
                name, fans = info.get("nickname"), info.get("mplatform_followers_count") or info.get("follower_count")
                face = ((info.get("avatar_medium") or info.get("avatar_thumb") or {}).get("url_list") or [""])[0]
                about = info.get("signature")
            else:
                card = ((c.get("https://api.bilibili.com/x/web-interface/card", params={"mid": ident}).json() or {}).get("data") or {}).get("card") or {}
                name, fans, face, about = card.get("name"), card.get("fans"), card.get("face"), card.get("sign")
        if name:
            out["name"] = str(name)[:120]
        if _int(fans):
            out["followers"] = _int(fans)
        if str(face or "").startswith(("http", "//")):
            face = "https:" + str(face) if str(face).startswith("//") else str(face).replace("http://", "https://", 1)
            out["avatar"] = face[:1000]
        if about:
            out["description"] = re.sub(r"\s+", " ", str(about)).strip()[:400]
    except Exception as exc:  # noqa: BLE001 — the profile card is a nicety
        logger.info("channel_grab: %s profile card not read: %s", platform, exc)
    if "name" not in out and data.get("title"):
        out["name"] = re.split(r"的抖音|的个人空间|投稿视频| - 抖音|-哔哩哔哩", str(data["title"]))[0].strip()[:120] or str(data["title"])[:120]
    return out


# ── scans ──────────────────────────────────────────────────────────────────

@dataclass
class Scan:
    channel_id: int
    owner: str
    limit: int
    name: str = ""
    status: str = "running"  # running | done | error
    phase: str = "Chờ đến lượt"
    found: int = 0
    added: int = 0
    error: str = ""
    stop: bool = False
    started_at: float = field(default_factory=time.time)


SCANS: dict[tuple[str, int], Scan] = {}
_LOCK = threading.Lock()
_SCAN_SLOTS = threading.Semaphore(SCAN_PARALLEL)


def scan_of(channel_id: int) -> Optional[Scan]:
    return SCANS.get((_owner(), channel_id))


def add_channel(text: str, tags: Any = None, limit: Any = None) -> int:
    """The channel of a pasted link, kept (or found again) and scanned. Returns its id."""
    info = parse_channel(text)
    with get_session() as db:
        ch = db.exec(select(GrabChannel).where(GrabChannel.key == info["key"])).first()
        if ch is None:
            ch = GrabChannel(key=info["key"], platform=info["platform"], url=info["url"], handle=info["handle"],
                             name=info["handle"] or "", tags=normalize_tags(tags))
            db.add(ch)
            db.commit()
            db.refresh(ch)
        elif tags:
            ch.tags = normalize_tags([*(ch.tags or []), *normalize_tags(tags)])
            db.add(ch)
            db.commit()
        cid = int(ch.id)  # type: ignore[arg-type]
    start_scan(cid, limit)
    return cid


def start_scan(channel_id: int, limit: Any = None) -> Scan:
    with get_session() as db:
        ch = db.get(GrabChannel, channel_id)
        if ch is None:
            raise GrabError("Không thấy kênh này")
        name = ch.name or ch.handle or ch.url
    with _LOCK:
        cur = scan_of(channel_id)
        if cur is not None and cur.status == "running":
            return cur
        scan = Scan(channel_id=channel_id, owner=_owner(), limit=normalize_limit(limit), name=name)
        SCANS[(scan.owner, channel_id)] = scan
    threading.Thread(target=_scan, args=(scan,), name=f"grab-scan-{channel_id}", daemon=True).start()
    return scan


def scan_all(limit: Any = None) -> int:
    with get_session() as db:
        ids = [int(c.id) for c in db.exec(select(GrabChannel)).all()]  # type: ignore[arg-type]
    for cid in ids:
        start_scan(cid, limit)
    return len(ids)


def stop_scan(channel_id: int) -> None:
    scan = scan_of(channel_id)
    if scan is not None and scan.status == "running":
        scan.stop = True


def _scan(scan: Scan) -> None:
    with _SCAN_SLOTS:
        try:
            if scan.stop:
                raise GrabError(STOPPED)
            _scan_now(scan)
            scan.status, scan.phase = "done", "Xong"
        except GrabError as exc:
            scan.status, scan.error = "error", str(exc)
            _note_scan_error(scan)
        except Exception as exc:  # noqa: BLE001 — never die silently
            logger.exception("channel_grab: scan %s crashed", scan.channel_id)
            scan.status, scan.error = "error", f"{type(exc).__name__}: {exc}"
            _note_scan_error(scan)


def _note_scan_error(scan: Scan) -> None:
    if scan.owner != _owner() or scan.error == STOPPED:
        return
    try:
        with get_session() as db:
            ch = db.get(GrabChannel, scan.channel_id)
            if ch is not None:
                ch.scan_error = scan.error[:400]
                db.add(ch)
                db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("channel_grab: could not note the scan error")


def _scan_now(scan: Scan) -> None:
    with get_session() as db:
        ch = db.get(GrabChannel, scan.channel_id)
        if ch is None:
            raise GrabError("Kênh đã bị xoá")
        platform, url, key = ch.platform, ch.url, ch.key
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    errors: list[str] = []
    targets = [] if platform in BROWSER_PLATFORMS else listing_targets(platform, url, key)
    if platform in BROWSER_PLATFORMS:
        label = PLATFORMS[platform]["label"]
        scan.phase = f"Đang đọc kênh qua Chrome của bạn — một cửa sổ {label} sẽ mở rồi tự đóng, đừng đóng nó"
        data = _list_via_chrome(url, scan.limit, label, lambda: scan.stop)
        rows = browser_rows(data, platform, label)
        meta = browser_meta(data, platform, url)
        scan.found = len(rows)
    for i, (target, kind) in enumerate(targets, 1):
        scan.phase = "Đang đọc danh sách video" + (f" ({'video dài' if kind == 'video' else 'Shorts'})" if len(targets) > 1 else "")
        try:
            data = _list(target, scan.limit, lambda: scan.stop)
        except GrabError as exc:
            if str(exc) == STOPPED:
                raise
            errors.append(str(exc))  # a channel without that shelf (no Shorts tab) says so here
            continue
        meta = {**channel_meta(data), **meta}
        for row in entry_rows(data, platform, kind):
            if all(r["key"] != row["key"] for r in rows):
                rows.append(row)
        scan.found = len(rows)
    if not rows:
        raise GrabError(errors[0] if errors else "Kênh này không có video công khai nào")
    if scan.owner != _owner():
        raise GrabError("Đã đổi tài khoản giữa chừng — quét lại kênh")
    todo: list[tuple[int, str]] = []
    with get_session() as db:
        ch = db.get(GrabChannel, scan.channel_id)
        if ch is None:
            raise GrabError("Kênh đã bị xoá")
        have = {v.key: v for v in db.exec(select(GrabVideo).where(GrabVideo.channel_id == scan.channel_id)).all()}
        had_any = bool(have)
        newest = max((_aware(v.published_at) for v in have.values() if v.published_at), default=None)
        for v in have.values():
            if v.fresh:
                v.fresh = False
                db.add(v)
        passed_known: set[str] = set()  # shelves (kinds) where a video already known has gone by
        for row in rows:
            v = have.get(row["key"])
            if v is None:
                # "MỚI" = posted since the last scan — not an older video a deeper scan reached: by its date when the
                # listing gives one, else by standing ahead of every video already known on its shelf
                if row["published_at"] is not None and newest is not None:
                    fresh = row["published_at"] > newest
                else:
                    fresh = row["kind"] not in passed_known
                v = GrabVideo(channel_id=scan.channel_id, fresh=had_any and fresh, **row)
                scan.added += 1 if (fresh or not had_any) else 0
            else:
                passed_known.add(row["kind"])
                for k in ("url", "title", "thumb", "position", "kind"):
                    setattr(v, k, row[k])
                for k in ("duration_s", "views", "likes", "comments", "published_at"):  # a listing may leave these out
                    if row[k] is not None:
                        setattr(v, k, row[k])
            db.add(v)
        for k, val in meta.items():
            setattr(ch, k, val)
        ch.scanned_at, ch.scan_error = datetime.now(timezone.utc), ""
        db.add(ch)
        db.commit()
        avatar = ch.avatar
        for v in db.exec(select(GrabVideo).where(GrabVideo.channel_id == scan.channel_id)).all():
            if v.thumb and not thumb_file(int(v.id)).is_file():  # type: ignore[arg-type]
                todo.append((int(v.id), v.thumb))  # type: ignore[arg-type]
    if avatar and not avatar_file(scan.channel_id).is_file():
        fetch_image(avatar, avatar_file(scan.channel_id))
    # the covers, kept here: TikTok's links stop working in a couple of days
    done = 0
    scan.phase = f"Đang lấy ảnh bìa (0/{len(todo)})"

    def one(item: tuple[int, str]) -> None:
        nonlocal done
        if not scan.stop:
            fetch_image(item[1], thumb_file(item[0]))
        done += 1
        scan.phase = f"Đang lấy ảnh bìa ({done}/{len(todo)})"

    if todo:
        with ThreadPoolExecutor(max_workers=THUMB_PARALLEL, thread_name_prefix="grab-thumb") as pool:
            list(pool.map(one, todo))


# ── downloads ──────────────────────────────────────────────────────────────

@dataclass
class Download:
    video_id: int
    owner: str
    title: str = ""
    status: str = "queued"  # queued | running | done | error
    error: str = ""
    stop: bool = False
    started_at: float = field(default_factory=time.time)


DOWNLOADS: dict[tuple[str, int], Download] = {}
_DL_POOL = ThreadPoolExecutor(max_workers=DOWNLOAD_PARALLEL, thread_name_prefix="grab-dl")
#: the batch the badge counts: reset when nothing is left running
_BATCH: dict[str, dict[str, int]] = {}


def download_of(video_id: int) -> Optional[Download]:
    return DOWNLOADS.get((_owner(), video_id))


def download(ids: list[int]) -> dict[str, int]:
    """Queue the videos for download (two at a time). Ones already here, or already on their way, are skipped."""
    owner = _owner()
    queued = skipped = 0
    with get_session() as db:
        videos = db.exec(select(GrabVideo).where(GrabVideo.id.in_(ids))).all() if ids else []  # type: ignore[union-attr]
        wanted = [(int(v.id), v.title, v.media_id) for v in videos]  # type: ignore[arg-type]
    with _LOCK:
        idle = not any(d.owner == owner and d.status in ("queued", "running") for d in DOWNLOADS.values())
        batch = _BATCH.setdefault(owner, {"total": 0, "done": 0, "failed": 0})
        for vid, title, media_id in wanted:
            cur = DOWNLOADS.get((owner, vid))
            if local_media(media_id) is not None or (cur is not None and cur.status in ("queued", "running")):
                skipped += 1
                continue
            if idle:  # a new batch: the badge counts from here
                batch.update(total=0, done=0, failed=0)
                idle = False
            d = Download(video_id=vid, owner=owner, title=title)
            DOWNLOADS[(owner, vid)] = d
            batch["total"] += 1
            queued += 1
            _DL_POOL.submit(_download, d)
    return {"queued": queued, "skipped": skipped}


def stop_downloads(ids: Optional[list[int]] = None) -> int:
    owner, n = _owner(), 0
    for d in list(DOWNLOADS.values()):
        if d.owner == owner and d.status in ("queued", "running") and (not ids or d.video_id in ids):
            d.stop = True
            n += 1
    return n


def _download(d: Download) -> None:
    batch = _BATCH.setdefault(d.owner, {"total": 0, "done": 0, "failed": 0})
    try:
        if d.stop:
            raise GrabError(STOPPED)
        d.status = "running"
        _download_now(d)
        d.status = "done"
        batch["done"] += 1
    except GrabError as exc:
        d.status, d.error = "error", str(exc)
        batch["failed"] += 0 if d.error == STOPPED else 1
        _note_download_error(d)
    except Exception as exc:  # noqa: BLE001 — never die silently
        logger.exception("channel_grab: download %s crashed", d.video_id)
        d.status, d.error = "error", f"{type(exc).__name__}: {exc}"
        batch["failed"] += 1
        _note_download_error(d)


def _note_download_error(d: Download) -> None:
    if d.owner != _owner() or d.error == STOPPED:
        return
    try:
        with get_session() as db:
            v = db.get(GrabVideo, d.video_id)
            if v is not None:
                v.download_error = d.error[:400]
                db.add(v)
                db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("channel_grab: could not note the download error")


def _download_now(d: Download) -> None:
    from flowboard.services.video_export import probe_clip
    from flowboard.services.video_fetch import FetchError, fetch_video

    if d.owner != _owner():
        raise GrabError("Đã đổi tài khoản — tải lại video này")
    with get_session() as db:
        v = db.get(GrabVideo, d.video_id)
        if v is None:
            raise GrabError("Video đã bị xoá khỏi danh sách")
        url = v.url
    media_id = uuid.uuid4().hex
    out_dir = media_service.MEDIA_CACHE_DIR
    try:
        path, title = fetch_video(url, media_id, out_dir, max_duration_s=MAX_DURATION_S, stop=lambda: d.stop)
    except FetchError as exc:
        raise GrabError(STOPPED if d.stop else f"Không tải được: {exc}") from exc
    if d.owner != _owner():  # the account changed while it downloaded: the file is not this account's
        path.unlink(missing_ok=True)
        raise GrabError("Đã đổi tài khoản — tải lại video này")
    info = probe_clip(path)
    mime = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}.get(path.suffix.lower(), "video/mp4")
    with get_session() as db:
        db.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(path), mime=mime))
        v = db.get(GrabVideo, d.video_id)
        if v is not None:
            v.media_id, v.downloaded_at, v.download_error = media_id, datetime.now(timezone.utc), ""
            if info is not None and info.duration > 0:
                v.duration_s = float(info.duration)
            if title and not v.title:
                v.title = title[:300]
            db.add(v)
        db.commit()


# ── what the page sees ─────────────────────────────────────────────────────

def _scan_view(scan: Optional[Scan]) -> Optional[dict[str, Any]]:
    if scan is None:
        return None
    return {"status": scan.status, "phase": scan.phase, "found": scan.found, "added": scan.added, "error": scan.error,
            "stopping": scan.stop and scan.status == "running"}


def channel_view(ch: GrabChannel, counts: Optional[dict[str, int]] = None) -> dict[str, Any]:
    cid = int(ch.id)  # type: ignore[arg-type]
    return {
        "id": cid, "platform": ch.platform, "platform_label": PLATFORMS.get(ch.platform, {}).get("label", ch.platform),
        "url": ch.url, "handle": ch.handle, "name": ch.name or ch.handle or ch.url, "followers": ch.followers,
        "description": ch.description, "tags": list(ch.tags or []), "note": ch.note,
        "has_avatar": bool(ch.avatar) or avatar_file(cid).is_file(),
        "scanned_at": utc_iso(ch.scanned_at), "scan_error": ch.scan_error, "created_at": utc_iso(ch.created_at),
        "videos": (counts or {}).get("videos", 0), "downloaded": (counts or {}).get("downloaded", 0),
        "fresh": (counts or {}).get("fresh", 0), "marked": (counts or {}).get("marked", 0), "scan": _scan_view(scan_of(cid)),
    }


def channels() -> list[dict[str, Any]]:
    with get_session() as db:
        chans = db.exec(select(GrabChannel).order_by(GrabChannel.id.desc())).all()  # type: ignore[union-attr]
        counts: dict[int, dict[str, int]] = {}
        marked = {m[0] for m in db.exec(select(GrabMark.key, GrabMark.tags)).all() if m[1]}
        for v in db.exec(select(GrabVideo.channel_id, GrabVideo.media_id, GrabVideo.fresh, GrabVideo.key)).all():
            c = counts.setdefault(int(v[0]), {"videos": 0, "downloaded": 0, "fresh": 0, "marked": 0})
            c["videos"] += 1
            c["downloaded"] += 1 if v[1] else 0
            c["fresh"] += 1 if v[2] else 0
            c["marked"] += 1 if v[3] in marked else 0
        return [channel_view(ch, counts.get(int(ch.id))) for ch in chans]  # type: ignore[arg-type]


def channel(channel_id: int) -> dict[str, Any]:
    found = next((c for c in channels() if c["id"] == channel_id), None)
    if found is None:
        raise GrabError("Không thấy kênh này")
    return found


def video_view(v: GrabVideo, mark: Optional[GrabMark] = None) -> dict[str, Any]:
    vid = int(v.id)  # type: ignore[arg-type]
    here = local_media(v.media_id) is not None
    d = download_of(vid)
    state = d.status if d is not None and d.status in ("queued", "running") else ("done" if here else "")
    return {
        "id": vid, "channel_id": v.channel_id, "url": v.url, "title": v.title, "kind": v.kind,
        "duration_s": v.duration_s, "views": v.views, "likes": v.likes, "comments": v.comments,
        "published_at": utc_iso(v.published_at), "position": v.position, "fresh": bool(v.fresh),
        "media_id": v.media_id if here else None, "downloaded_at": utc_iso(v.downloaded_at) if here else None,
        # downloaded on the other machine: the row says so, the file is not here
        "elsewhere": bool(v.media_id) and not here,
        "download": state, "download_error": (d.error if d is not None and d.status == "error" and d.error != STOPPED else v.download_error) if not here else "",
        "used": {**dict(v.used or {}), **dict((mark.used if mark else None) or {})},
        "marks": list((mark.tags if mark else None) or []),
    }


def _marks_for(db: Any, keys: list[str]) -> dict[str, GrabMark]:
    out: dict[str, GrabMark] = {}
    for i in range(0, len(keys), 500):  # an IN list of a sane size
        for m in db.exec(select(GrabMark).where(GrabMark.key.in_(keys[i:i + 500]))).all():  # type: ignore[attr-defined]
            out[m.key] = m
    return out


def videos(channel_id: Optional[int] = None, limit: int = 20000) -> list[dict[str, Any]]:
    with get_session() as db:
        q = select(GrabVideo)
        if channel_id is not None:
            q = q.where(GrabVideo.channel_id == channel_id)
        rows = db.exec(q.order_by(GrabVideo.channel_id, GrabVideo.position).limit(limit)).all()
        marks = _marks_for(db, sorted({v.key for v in rows}))
        return [video_view(v, marks.get(v.key)) for v in rows]


def mark_tags() -> list[dict[str, Any]]:
    """Every label the seller has put on videos, with how many videos carry it (the ready-made ones first)."""
    count: dict[str, int] = {}
    with get_session() as db:
        for tags in db.exec(select(GrabMark.tags)).all():
            for t in tags or []:
                count[t] = count.get(t, 0) + 1
    order = MARK_PRESETS + sorted((t for t in count if t not in MARK_PRESETS), key=lambda s: s.lower())
    return [{"tag": t, "videos": count.get(t, 0), "preset": t in MARK_PRESETS} for t in order]


def set_marks(ids: list[int], add: Any = None, remove: Any = None) -> int:
    """Put / take labels on the videos ``ids`` — kept by each video's key, so they come back with it."""
    plus, minus = normalize_marks(add), {t.lower() for t in normalize_marks(remove)}
    if not ids or not (plus or minus):
        return 0
    now = datetime.now(timezone.utc)
    with get_session() as db:
        keys = sorted({v.key for v in db.exec(select(GrabVideo).where(GrabVideo.id.in_(ids))).all()})  # type: ignore[union-attr]
        have = _marks_for(db, keys)
        for key in keys:
            m = have.get(key) or GrabMark(key=key, tags=[], used={})
            tags = [t for t in (m.tags or []) if t.lower() not in minus]
            m.tags = normalize_marks([*tags, *plus])
            m.updated_at = now
            db.add(m)
        db.commit()
    return len(keys)


def state() -> dict[str, Any]:
    """Scans and downloads in flight (memory only): what the page polls."""
    owner = _owner()
    return {
        "scans": {str(s.channel_id): _scan_view(s) for (o, _), s in SCANS.items() if o == owner and s.status == "running"},
        "downloads": {str(d.video_id): {"status": d.status, "stopping": d.stop} for d in DOWNLOADS.values()
                      if d.owner == owner and d.status in ("queued", "running")},
    }


def update_channel(channel_id: int, *, tags: Any = None, note: Optional[str] = None, name: Optional[str] = None) -> dict[str, Any]:
    with get_session() as db:
        ch = db.get(GrabChannel, channel_id)
        if ch is None:
            raise GrabError("Không thấy kênh này")
        if tags is not None:
            ch.tags = normalize_tags(tags)
        if note is not None:
            ch.note = note.strip()[:300]
        if name is not None and name.strip():
            ch.name = name.strip()[:120]
        db.add(ch)
        db.commit()
    return channel(channel_id)


def delete_channel(channel_id: int) -> int:
    """The channel and its list leave; the videos already downloaded stay (clips made from them keep working)."""
    stop_scan(channel_id)
    with get_session() as db:
        ch = db.get(GrabChannel, channel_id)
        if ch is None:
            raise GrabError("Không thấy kênh này")
        vids = db.exec(select(GrabVideo).where(GrabVideo.channel_id == channel_id)).all()
        ids = [int(v.id) for v in vids]  # type: ignore[arg-type]
        stop_downloads(ids) if ids else None
        for v in vids:
            db.delete(v)
        db.delete(ch)
        db.commit()
    for vid in ids:
        thumb_file(vid).unlink(missing_ok=True)
    avatar_file(channel_id).unlink(missing_ok=True)
    return len(ids)


def media_of(ids: list[int]) -> list[dict[str, Any]]:
    """The downloaded videos among ``ids``, in that order — what "✂️ Cắt video" / "🎙 Lồng tiếng" take as files."""
    with get_session() as db:
        rows = {int(v.id): v for v in db.exec(select(GrabVideo).where(GrabVideo.id.in_(ids))).all()} if ids else {}  # type: ignore[union-attr,arg-type]
    out = []
    for vid in ids:
        v = rows.get(vid)
        if v is not None and local_media(v.media_id) is not None:
            out.append({"id": vid, "media_id": v.media_id, "name": v.title or f"Video {vid}"})
    return out


def mark_used(ids: list[int], tool: str) -> int:
    if tool not in ("cut", "dub"):
        raise GrabError("Công cụ không hợp lệ")
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as db:
        rows = db.exec(select(GrabVideo).where(GrabVideo.id.in_(ids))).all() if ids else []  # type: ignore[union-attr]
        marks = _marks_for(db, sorted({v.key for v in rows}))
        for v in rows:
            v.used = {**(v.used or {}), tool: now}
            db.add(v)
            # kept by the video too, so a removed and re-added channel still says "đã cắt / đã lồng"
            m = marks.get(v.key) or GrabMark(key=v.key, tags=[], used={})
            m.used = {**(m.used or {}), tool: now}
            m.updated_at = datetime.now(timezone.utc)
            marks[v.key] = m
            db.add(m)
        db.commit()
        return len(rows)


# ── the AI's pick ──────────────────────────────────────────────────────────

_PICK_SYSTEM = (
    "You help a Vietnamese short-video seller choose which videos of a source channel to download and rework "
    "(cut into shorts, dub into Vietnamese). You get the seller's request and a numbered list of videos with their "
    "title, views, likes, length and date — nothing else: judge by the titles and the numbers only, never invent what "
    "a video contains. Follow the request exactly (topic, how many, view counts, length, dates…); when it gives no "
    "number, pick every video that fits. Answer with ONE JSON object and nothing else: "
    '{"picks": [{"n": <number from the list>, "why": "<Vietnamese, at most 12 words: why this one fits>"}], '
    '"note": "<Vietnamese, one short sentence about the pick, or empty>"}. Best fit first. '
    "If nothing fits, return an empty picks list and say why in note."
)


def _count(n: Optional[int]) -> str:
    return "?" if n is None else str(n)


def pick_prompt(rows: list[GrabVideo], request: str, today: Optional[datetime] = None) -> str:
    today = today or datetime.now(timezone.utc)
    lines = []
    for i, v in enumerate(rows, 1):
        dur = f"{v.duration_s:.0f}s" if v.duration_s else ("short" if v.kind == "short" else "?")
        day = v.published_at.strftime("%Y-%m-%d") if v.published_at else "?"
        lines.append(f"[{i}] views={_count(v.views)} likes={_count(v.likes)} length={dur} date={day} | {v.title[:160] or '(không có tiêu đề)'}")
    return (f"Today: {today.strftime('%Y-%m-%d')}\nTHE SELLER'S REQUEST: {request}\nEND OF THE REQUEST.\n"
            f"VIDEOS ({len(lines)}):\n" + "\n".join(lines))


async def pick(ids: list[int], request: str) -> dict[str, Any]:
    """``{picks: [{id, why}], note}`` — the AI's choice among ``ids`` for the seller's ``request``."""
    from flowboard.services import dub_split
    from flowboard.services.llm import run_llm
    from flowboard.services.llm.base import LLMError

    request = re.sub(r"[ \t]+", " ", (request or "").strip())[:1500]
    if not request:
        raise GrabError("Gõ yêu cầu chọn video, ví dụ: “10 video nhiều view nhất về vũ trụ, dưới 3 phút”")
    if not ids:
        raise GrabError("Chưa có video nào để chọn")
    if len(ids) > PICK_MAX:
        raise GrabError(f"AI xem tối đa {PICK_MAX} video một lần — lọc bớt (theo lượt xem, ngày đăng…) rồi nhờ AI chọn")
    with get_session() as db:
        found = {int(v.id): v for v in db.exec(select(GrabVideo).where(GrabVideo.id.in_(ids))).all()}  # type: ignore[union-attr,arg-type]
    rows = [found[i] for i in ids if i in found]
    if not rows:
        raise GrabError("Chưa có video nào để chọn")
    try:
        text = await run_llm("auto_prompt", pick_prompt(rows, request), system_prompt=_PICK_SYSTEM, timeout=LLM_TIMEOUT_S)
        data = dub_split._json_obj(text)
    except (LLMError, dub_split.SplitError) as exc:
        raise GrabError(f"AI chưa chọn được: {str(exc)[:200]}") from exc
    picks, seen = [], set()
    for p in data.get("picks") if isinstance(data.get("picks"), list) else []:
        n = _int(p.get("n")) if isinstance(p, dict) else None
        if n is None or not 1 <= n <= len(rows) or n in seen:
            continue
        seen.add(n)
        picks.append({"id": int(rows[n - 1].id), "why": re.sub(r"\s+", " ", str(p.get("why") or "")).strip()[:120]})  # type: ignore[arg-type]
    return {"picks": picks, "note": re.sub(r"\s+", " ", str(data.get("note") or "")).strip()[:240]}


# ── the "việc đang chạy" badge ─────────────────────────────────────────────

def running_items() -> list[dict[str, Any]]:
    owner = _owner()
    out = [{"key": f"grabscan:{s.channel_id}", "kind": "grab", "title": f"Đọc kênh “{s.name or 'kênh'}”"[:90],
            "detail": s.phase + (f" — {s.found} video" if s.found else ""), "progress": None,
            "started_at": s.started_at, "link": f"/tools/grab?channel={s.channel_id}"}
           for (o, _), s in SCANS.items() if o == owner and s.status == "running"]
    live = [d for d in DOWNLOADS.values() if d.owner == owner and d.status in ("queued", "running")]
    if live:
        b = _BATCH.get(owner) or {"total": len(live), "done": 0, "failed": 0}
        total = max(b["total"], len(live))
        finished = max(0, total - len(live))
        out.append({"key": "grabdl:batch", "kind": "grab", "title": f"Tải {total} video từ kênh",
                    "detail": f"Xong {finished}/{total}" + (f" · {b['failed']} lỗi" if b["failed"] else ""),
                    "progress": int(100 * finished / total) if total else None,
                    "started_at": min(d.started_at for d in live), "link": "/tools/grab"})
    return out


def outcome(kind: str, ident: str) -> dict[str, Any]:
    if kind == "grabscan" and ident.isdigit():
        s = scan_of(int(ident))
        if s is None:
            return {"ok": True, "message": ""}
        if s.status == "error":
            return {"ok": s.error == STOPPED, "message": s.error}
        return {"ok": True, "message": f"Đã đọc {s.found} video" + (f" ({s.added} video mới)" if s.added else "")}
    b = _BATCH.get(_owner()) or {"total": 0, "done": 0, "failed": 0}
    if b["failed"]:
        return {"ok": False, "message": f"Tải xong {b['done']} video, {b['failed']} video lỗi — xem ở trang Cào video kênh"}
    return {"ok": True, "message": f"Đã tải xong {b['done']} video — chọn để cắt / lồng tiếng" if b["done"] else ""}
