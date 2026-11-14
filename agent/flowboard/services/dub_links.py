"""Link library for dubbing ("📚 Thư viện link" on /tools/dub).

The seller imports .txt / .md files with whatever in them (notes, a list
copied from a chat, Douyin share texts…); every http(s) link found becomes a
:class:`DubLink` row. The library says for each link whether that video was
already dubbed (any dub job or dubbed clip made from the same video, matched
by a canonical :func:`link_key` — ``douyin:<id>``, ``youtube:<id>``… — so a
short share link and the full page link of the same video count as one),
and queues links for dubbing: :func:`queue` keeps the chosen options on the
rows, :func:`feed` (hooked into ``dub._pump``) starts the next one whenever
nobody is waiting in the dub queue, so a long list flows through one video
at a time and a link pasted by hand still finds room.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Board, DubLink
from flowboard.services import dub, tts
from flowboard.services.video_fetch import MOBILE_UA, _URL_RE

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 2_000_000
MAX_FILES = 20
MAX_LINKS_PER_IMPORT = 2000
MAX_LABEL = 160

#: what the dub queue cannot take (it downloads TikTok / Douyin / YouTube / Instagram / Facebook / X only)
NOT_VIDEO = "không phải link TikTok / Douyin / YouTube / Instagram / Facebook / X"
#: share links that only redirect to the real page: resolved once to get the video id
SHORT_HOSTS = ("v.douyin.com", "vt.tiktok.com", "vm.tiktok.com", "b23.tv", "xhslink.com")
RESOLVE_TIMEOUT_S = 8.0
RESOLVE_RETRY_S = 600

_MD_LINK = re.compile(r"\[([^\]\n]{1,300})\]\((https?://[^)\s]+)\)")
_TRAIL = ".,;:!?)'\"*]>"
_DROP_QUERY = re.compile(r"^(utm_|share|is_|u_code|did|iid|sec_|from|tt_from|_r|_t|checksum|timestamp|enter_from|previous_page|"
                         r"extra_params|xsec_|app|region|mid|lang|si$|feature$|pp$|t$|igsh|mibextid|ref)", re.I)


# ── reading files ─────────────────────────────────────────────────────────

def _clean_url(raw: str) -> str:
    url = raw
    while url and url[-1] in _TRAIL:
        # keep a closing bracket that belongs to the URL itself (…/wiki/Foo_(bar))
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    return url


def _label(line: str, url: str) -> str:
    text = line.replace(url, " ")
    text = _URL_RE.sub(" ", text)
    text = re.sub(r"^\s*(?:[-*+>]|\d+[.)]|#+)\s*", "", text)   # list / quote / heading markers
    text = re.sub(r"[\[\]()<>`*_|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -–—:·|")
    return text[:MAX_LABEL]


def extract_links(text: str) -> list[dict[str, str]]:
    """Every distinct http(s) link in ``text``, in order: ``[{url, label}]``. ``label`` = the link
    text of a markdown link, else the rest of the line (a Douyin share's title, a note next to it)."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        if "http" not in line:
            continue
        # [text](url): the text is the label; the brackets would otherwise glue onto the URL match
        md = {_clean_url(m.group(2)): m.group(1).strip() for m in _MD_LINK.finditer(line)}
        line = _MD_LINK.sub(lambda m: f" {m.group(2)} ", line)
        for m in _URL_RE.finditer(line):
            url = _clean_url(m.group(0))
            if len(url) < 12 or url in seen:
                continue
            seen.add(url)
            label = md.get(url) or _label(line, m.group(0))
            out.append({"url": url[:2000], "label": label})
    return out


# ── the same video, however the link is written ───────────────────────────

def _host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    for p in ("www.", "m.", "mobile."):
        if host.startswith(p):
            host = host[len(p):]
    return host


def _on(host: str, *domains: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def is_video_link(url: str) -> bool:
    """A link the dubbing download takes (the same host list as reference videos); others are listed only."""
    from flowboard.routes.reference_video import _host_allowed

    return _host_allowed(url)


def link_key(url: str) -> str:
    """Canonical key of a link: ``douyin:<id>`` / ``tiktok:<id>`` / ``youtube:<id>`` / ``bilibili:<bv>``
    when the id is in the link, else ``host/path[?useful query]`` (tracking parameters dropped)."""
    try:
        u = urlparse(url.strip())
    except ValueError:
        return url.strip().lower()
    host = _host(url)
    path = re.sub(r"/{2,}", "/", u.path or "").rstrip("/")
    q = parse_qs(u.query)
    if _on(host, "douyin.com", "iesdouyin.com"):
        m = re.search(r"/(?:video|note|share/video|share/note|share/slides)/(\d{8,})", path)
        vid = m.group(1) if m else (q.get("modal_id") or q.get("vid") or [""])[0]
        if vid.isdigit():
            return f"douyin:{vid}"
    if _on(host, "tiktok.com"):
        m = re.search(r"/(?:video|photo|v)/(\d{8,})", path)
        if m:
            return f"tiktok:{m.group(1)}"
    if host == "youtu.be" and path.strip("/"):
        return f"youtube:{path.strip('/').split('/')[0]}"
    if _on(host, "youtube.com"):
        m = re.search(r"/(?:shorts|embed|live|v)/([\w-]{6,})", path)
        vid = m.group(1) if m else (q.get("v") or [""])[0]
        if vid:
            return f"youtube:{vid}"
    if _on(host, "bilibili.com"):
        m = re.search(r"/video/(BV\w+|av\d+)", path, re.I)
        if m:
            return f"bilibili:{m.group(1)}"
    keep = sorted((k, v[0]) for k, v in q.items() if v and not _DROP_QUERY.match(k))
    return f"{host}{path}" + (f"?{urlencode(keep)}" if keep else "")


_RESOLVED: dict[str, tuple[Optional[str], float]] = {}


def resolve_final(url: str) -> Optional[str]:
    """Where a share link redirects to (no body read), or None. Swapped out in tests."""
    try:
        with httpx.Client(follow_redirects=True, timeout=RESOLVE_TIMEOUT_S, headers={"User-Agent": MOBILE_UA}) as c:
            with c.stream("GET", url) as r:
                return str(r.url)
    except Exception as exc:  # noqa: BLE001 — a dead or blocked link just keeps its plain key
        logger.info("dub_links: could not resolve %s: %s", url, exc)
        return None


def key_for(url: str, *, resolve: bool = True) -> str:
    """:func:`link_key`, following a short share link (``v.douyin.com/…``) to the video id first.
    Answers are remembered (failures retried after :data:`RESOLVE_RETRY_S`)."""
    key = link_key(url)
    if not resolve or _host(url) not in SHORT_HOSTS:
        return key
    hit = _RESOLVED.get(url)
    if hit is None or (hit[0] is None and time.time() - hit[1] > RESOLVE_RETRY_S):
        final = resolve_final(url)
        hit = (final, time.time())
        _RESOLVED[url] = hit
    final = hit[0]
    if not final:
        return key
    resolved = link_key(final)
    return resolved if ":" in resolved.split("/")[0] else key


def keys_of(url: Optional[str]) -> set[str]:
    """Both the plain and the resolved key: two links match when they share one."""
    if not url:
        return set()
    from flowboard.services.video_fetch import extract_url

    url = extract_url(url) or url
    return {link_key(url), key_for(url)}


def _keys_parallel(urls: Iterable[str]) -> dict[str, str]:
    urls = list(dict.fromkeys(urls))
    short = [u for u in urls if _host(u) in SHORT_HOSTS and u not in _RESOLVED]
    if short:
        with ThreadPoolExecutor(max_workers=min(8, len(short))) as pool:
            list(pool.map(key_for, short))
    return {u: key_for(u) for u in urls}


# ── import ────────────────────────────────────────────────────────────────

class LinkError(ValueError):
    pass


def import_texts(files: list[dict[str, str]]) -> dict[str, Any]:
    """``files`` = ``[{name, text}]`` (the page reads the files) → new library rows, file order kept.
    A link already in the library (same key) is not added twice."""
    if not files:
        raise LinkError("Chưa có file nào")
    if len(files) > MAX_FILES:
        raise LinkError(f"Tối đa {MAX_FILES} file một lần")
    found: list[dict[str, str]] = []
    per_file: list[dict[str, Any]] = []
    for f in files:
        name = str(f.get("name") or "").strip()[:120] or "văn bản dán vào"
        text = str(f.get("text") or "")
        if len(text) > MAX_TEXT_CHARS:
            raise LinkError(f"File “{name}” quá lớn (tối đa ~2 MB chữ)")
        links = extract_links(text)
        per_file.append({"name": name, "links": len(links)})
        found += [dict(x, source=name) for x in links]
    if len(found) > MAX_LINKS_PER_IMPORT:
        raise LinkError(f"Tìm thấy {len(found)} link — tối đa {MAX_LINKS_PER_IMPORT} link một lần, chia file nhỏ hơn")
    keys = _keys_parallel(x["url"] for x in found)
    now = datetime.now(timezone.utc)
    added: list[int] = []
    existing: list[int] = []
    with get_session() as s:
        have: dict[str, DubLink] = {}
        for row in s.exec(select(DubLink)).all():
            have.setdefault(row.key, row)
            have.setdefault(link_key(row.url), row)
        fresh: list[DubLink] = []
        for pos, x in enumerate(found):
            key = keys[x["url"]]
            old = have.get(key) or have.get(link_key(x["url"]))
            if old is not None:
                if old.id is not None:
                    existing.append(old.id)
                if not old.label and x["label"]:
                    old.label = x["label"]
                    s.add(old)
                continue
            row = DubLink(url=x["url"], key=key, label=x["label"], source=x["source"], position=pos, created_at=now)
            s.add(row)
            have[key] = row
            fresh.append(row)
        s.commit()
        for row in fresh:
            s.refresh(row)
            added.append(row.id)  # type: ignore[arg-type]
    return {"found": len(found), "added": added, "existing": sorted(set(existing)), "files": per_file}


# ── what each link has become ─────────────────────────────────────────────

_ACTIVE = ("queued", "running", "rendering")
_RANK = {"running": 4, "done": 3, "review": 2, "error": 1}


def _job_state(status: str) -> str:
    return "running" if status in _ACTIVE else status


def _dubbed_boards() -> list[dict[str, Any]]:
    """Dubbed clips whose job left the list (deleted / another machine): ``[{job_id, board_id, url, name}]``."""
    out = []
    with get_session() as s:
        for b in s.exec(select(Board)).all():
            qt = (b.data or {}).get("quicktool") or {}
            if qt.get("template_id") != "dub":
                continue
            d = qt.get("dub") or {}
            snap = d.get("snapshot") or {}
            if snap.get("url"):
                out.append({"job_id": d.get("job_id"), "board_id": b.id, "url": snap["url"], "name": b.name})
    return out


def _evidence() -> dict[str, list[dict[str, Any]]]:
    """key → every dub job / dubbed clip of that video."""
    dub.load_jobs()
    by_key: dict[str, list[dict[str, Any]]] = {}
    seen_jobs: set[str] = set()
    for j in list(dub.JOBS.values()):
        if not j.url:
            continue
        seen_jobs.add(j.id)
        item = {"job_id": j.id, "status": _job_state(j.status), "phase": j.phase, "progress": j.progress,
                "title": j.name or j.title, "board_id": j.board_id, "error": j.error, "at": j.started_at}
        for k in keys_of(j.url):
            by_key.setdefault(k, []).append(item)
    try:
        boards = _dubbed_boards()
    except Exception as exc:  # noqa: BLE001 — the jobs alone still answer most rows
        logger.warning("dub_links: reading dubbed clips failed: %s", exc)
        boards = []
    for b in boards:
        if b["job_id"] in seen_jobs:
            continue
        item = {"job_id": b["job_id"], "status": "done", "phase": "", "progress": 100, "title": b["name"],
                "board_id": b["board_id"], "error": None, "at": 0}
        for k in keys_of(b["url"]):
            by_key.setdefault(k, []).append(item)
    return by_key


def _row(link: DubLink, evidence: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    items: dict[Any, dict[str, Any]] = {}
    for k in {link.key, link_key(link.url)}:
        for it in evidence.get(k, []):
            items[it["job_id"] or f"b{it['board_id']}"] = it
    found = list(items.values())
    done = [it for it in found if it["status"] == "done"]
    best = max(found, key=lambda it: (it["job_id"] == link.job_id and it["status"] == "running", _RANK.get(it["status"], 0), it["at"]),
               default=None)
    status = best["status"] if best else "new"
    if link.queued and status != "running":
        status = "waiting"
    elif status == "new" and link.error:
        status = "error"
    elif status == "new" and not is_video_link(link.url):
        status = "other"  # listed, but the dub download cannot take it
    return {
        "id": link.id, "url": link.url, "label": link.label, "source": link.source, "key": link.key,
        "video": is_video_link(link.url), "status": status, "queued": link.queued,
        "imported_at": link.created_at.isoformat() if link.created_at else None,
        "job": best, "done_count": len(done), "error": (best or {}).get("error") or link.error,
    }


def library() -> dict[str, Any]:
    """Every link, newest import first (file order inside an import), with what it has become."""
    with get_session() as s:
        links = list(s.exec(select(DubLink)).all())
    evidence = _evidence()
    links.sort(key=lambda r: (-(r.created_at.timestamp() if r.created_at else 0), r.position, r.id or 0))
    rows = [_row(r, evidence) for r in links]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"links": rows, "counts": counts, "total": len(rows)}


# ── the library queue ─────────────────────────────────────────────────────

#: something may be queued (unknown after a restart): saves a database read on every dub pump
_maybe_queued = True
_FEED_LOCK = threading.Lock()


def queue(ids: list[int], options: dict[str, Any]) -> dict[str, Any]:
    """Mark links to be dubbed with ``options`` (voice, keep_bgm, style, engine, channel_id, auto_render,
    layout, highlights); :func:`feed` starts them one after another. Links already running are skipped."""
    global _maybe_queued
    if not tts.is_voice(options.get("voice")):
        raise LinkError("Giọng đọc không hợp lệ")
    evidence = _evidence()
    now = datetime.now(timezone.utc)
    queued, skipped = 0, []
    with get_session() as s:
        for i, link_id in enumerate(ids):
            link = s.get(DubLink, link_id)
            if link is None:
                skipped.append({"id": link_id, "reason": "không còn trong thư viện"})
                continue
            if not is_video_link(link.url):
                skipped.append({"id": link_id, "reason": NOT_VIDEO})
                continue
            if _row(link, evidence)["status"] == "running":
                skipped.append({"id": link_id, "reason": "đang lồng tiếng"})
                continue
            link.queued = True
            # the order they were picked in (one microsecond apart: same click, stable order)
            link.queued_at = datetime.fromtimestamp(now.timestamp() + i / 1e6, tz=timezone.utc)
            link.options = dict(options)
            link.error = None
            s.add(link)
            queued += 1
        s.commit()
    if queued:
        _maybe_queued = True
    started = feed()
    return {"queued": queued, "skipped": skipped, "started": started}


def unqueue(ids: list[int]) -> int:
    n = 0
    with get_session() as s:
        for link_id in ids:
            link = s.get(DubLink, link_id)
            if link is not None and link.queued:
                link.queued = False
                s.add(link)
                n += 1
        s.commit()
    return n


def delete(ids: list[int]) -> int:
    """Take links out of the library; the jobs and clips made from them stay."""
    n = 0
    with get_session() as s:
        for link_id in ids:
            link = s.get(DubLink, link_id)
            if link is not None:
                s.delete(link)
                n += 1
        s.commit()
    return n


def waiting_count() -> int:
    if not _maybe_queued:
        return 0
    with get_session() as s:
        return len(s.exec(select(DubLink.id).where(DubLink.queued == True)).all())  # noqa: E712


def feed() -> Optional[str]:
    """Start the next queued link when nobody waits in the dub queue (one waits while one runs, so a
    long list keeps flowing and a link pasted by hand still has room). Returns the new job id."""
    global _maybe_queued
    if not _maybe_queued or dub.queued_jobs():
        return None
    if not _FEED_LOCK.acquire(blocking=False):
        return None
    try:
        if not dub.status()["available"]:
            return None
        for _ in range(5):  # a link that fails to start (bad saved options) gives way to the next one
            with get_session() as s:
                link = s.exec(select(DubLink).where(DubLink.queued == True)  # noqa: E712
                              .order_by(DubLink.queued_at, DubLink.id)).first()  # type: ignore[arg-type]
                if link is None:
                    _maybe_queued = False
                    return None
                o = link.options or {}
                link.queued = False
                try:
                    job = dub.start_job(url=link.url, source_media_id=None, voice=o.get("voice") or tts.DEFAULT_VOICE,
                                        keep_bgm=bool(o.get("keep_bgm")), style=o.get("style") or "box_yellow",
                                        channel_id=o.get("channel_id"), name="", auto_render=o.get("auto_render", True) is not False,
                                        engine=o.get("engine") or "ass", layout=o.get("layout"), highlights=o.get("highlights"),
                                        translator=o.get("translator") or "google", mode=o.get("mode") or "dub",
                                        sub_lang=o.get("sub_lang") or "vi")
                except dub.DubError as exc:
                    link.error = str(exc)
                    s.add(link)
                    s.commit()
                    continue
                link.job_id, link.error = job.id, None
                s.add(link)
                s.commit()
                logger.info("dub_links: started %s for link %s", job.id, link.id)
                return job.id
        return None
    finally:
        _FEED_LOCK.release()


def after_login() -> None:
    """Another account's library is open now: look for its queued links again."""
    global _maybe_queued
    _maybe_queued = True


def feed_quietly() -> None:
    """The ``dub._pump`` hook: never lets a library problem break the dub queue."""
    try:
        feed()
    except Exception as exc:  # noqa: BLE001 — e.g. no account active yet
        logger.debug("dub_links: feed skipped: %s", exc)
