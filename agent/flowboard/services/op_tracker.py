"""Long in-page operations (an AI write, a link read, a page review…) as seen
by the floating "đang chạy" badge.

The heavy *jobs* (dubbing, AI erase, Flow renders) already live somewhere
the badge can read. Everything else is one long HTTP request the page
waits on: leave the page and the work goes on in the agent, but nothing
shows it. ``main._track_long_ops`` wraps the requests listed in
:data:`TRACKED` with :func:`start` / :func:`finish`, so they appear in
``GET /api/running`` like the jobs, with the page they were started from as
the way back (the ``Referer``), and their outcome / result kept for a while
(``GET /api/running/outcome``, ``/latest``) — the posts page uses that to
restore a post the AI finished while you were elsewhere.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

#: How long a finished operation stays answerable (outcome / result).
KEEP_S = 15 * 60
MAX_KEPT = 200


@dataclass
class Rule:
    method: str
    pattern: re.Pattern[str]
    kind: str
    title: str
    #: where to go back to when the request has no usable Referer; may use the path's groups
    default_link: str = "/today"
    #: keep the JSON answer (only for small answers the page can restore)
    keep_result: bool = False


def _r(method: str, path: str, kind: str, title: str, link: str = "/today", keep: bool = False) -> Rule:
    return Rule(method, re.compile(f"^{path}$"), kind, title, link, keep)


#: The long requests worth a badge. Order matters only for overlapping patterns.
TRACKED: list[Rule] = [
    _r("POST", r"/api/posts/write", "post_write", "AI đang viết bài", "/posts", keep=True),
    _r("POST", r"/api/posts/write-batch", "post_batch", "AI đang viết nhiều bài", "/posts"),
    _r("POST", r"/api/posts/hooks", "ai", "AI viết câu mở đầu", "/posts"),
    _r("POST", r"/api/posts/clip-hooks", "ai", "AI viết câu mở đầu cho clip", "/clips"),
    _r("POST", r"/api/posts/revise-image", "ai", "AI sửa prompt ảnh", "/posts"),
    _r("POST", r"/api/bundles", "bundle", "Đang tạo gói nội dung", "/clips"),
    _r("POST", r"/api/channels/(\d+)/brainstorm", "channel", "AI định hướng kênh", "/channels?id={0}"),
    _r("POST", r"/api/channels/(\d+)/review", "channel", "Đang xem & đánh giá kênh", "/channels?id={0}"),
    _r("POST", r"/api/channels/(\d+)/facebook", "channel", "Đang kết nối Facebook Page", "/channels?id={0}"),
    _r("POST", r"/api/products/from-link", "product", "Đang đọc sản phẩm từ link", "/products"),
    _r("POST", r"/api/products/import-tabs", "product", "Đang nhập sản phẩm từ tab", "/products"),
    _r("POST", r"/api/boards/from-template", "clip_setup", "AI đang viết kịch bản clip", "/clips"),
    _r("POST", r"/api/boards/(\d+)/tailor", "clip_setup", "AI viết lại kịch bản", "/clips/{0}/script"),
    _r("POST", r"/api/boards/(\d+)/cover", "clip_setup", "Đang làm ảnh bìa", "/clips/{0}/export"),
    _r("POST", r"/api/dub/jobs/([0-9a-f]+)/names", "ai", "AI đang rà tên riêng", "/tools/dub?job={0}"),
    _r("POST", r"/api/cut/sessions/([0-9a-f]+)/suggest", "cut", "AI đang chọn đoạn cắt", "/tools/cut?session={0}"),
    _r("POST", r"/api/prompt/(auto|refine|revise|auto-batch)", "ai", "AI viết prompt", "/clips"),
    _r("POST", r"/api/prompt/narration", "ai", "AI viết lời thoại", "/clips"),
    _r("POST", r"/api/reference-video/(analyze|analyze-link)", "video", "AI đang xem video mẫu", "/clips/from-video"),
    _r("POST", r"/api/reference-video/fetch", "video", "Đang tải video từ link", "/clips/from-video"),
    _r("POST", r"/api/reference-video/build", "clip_setup", "Đang dựng clip theo video mẫu", "/clips"),
    _r("POST", r"/api/swipes/analyze", "ai", "AI phân tích mẫu đang hot", "/swipes"),
    _r("POST", r"/api/swipes/(\d+)/adapt", "ai", "AI viết theo mẫu đang hot", "/swipes"),
    _r("POST", r"/api/drama/(analyze|build)", "ai", "AI dựng drama", "/clips"),
    _r("POST", r"/api/clean/([^/]+)/detect", "video", "Đang tìm chữ trên video (OCR)", "/tools/clean"),
    _r("POST", r"/api/clean/([^/]+)/erase", "video", "Đang xoá chữ / logo", "/tools/clean"),
    _r("POST", r"/api/schedule/(\d+)/publish", "publish", "Đang đăng lên Facebook", "/schedule"),
    _r("POST", r"/api/upload", "upload", "Đang tải ảnh lên Flow", "/today"),
    _r("POST", r"/api/upload-url", "upload", "Đang tải ảnh lên Flow", "/today"),
    _r("POST", r"/api/flow/projects/sync-up", "upload", "Đang đồng bộ ảnh sang project Flow", "/today"),
    _r("POST", r"/api/media/clean-marks/run", "media", "Đang xoá logo Gemini trên ảnh cũ", "/today"),
    _r("POST", r"/api/cloud/(migrate|files/sync)", "media", "Đang đồng bộ dữ liệu lên cloud", "/today"),
    _r("POST", r"/api/llm/voices/preview", "ai", "Đang tạo giọng nghe thử", "/today"),
    _r("POST", r"/api/voices/clones", "ai", "Đang nhân bản giọng", "/voices"),
]


@dataclass
class Op:
    id: str
    kind: str
    title: str
    link: str
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    ok: Optional[bool] = None
    message: str = ""
    result: Any = None
    claimed: bool = False

    def running_item(self) -> dict[str, Any]:
        secs = int(time.time() - self.started_at)
        return {"key": f"op:{self.id}", "kind": self.kind, "title": self.title,
                "detail": f"Đang chạy {secs // 60} phút {secs % 60} giây" if secs >= 60 else f"Đang chạy {secs} giây",
                "progress": None, "started_at": _iso(self.started_at), "link": self.link}


_ops: dict[str, Op] = {}
_lock = threading.Lock()


def _iso(ts: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def match(method: str, path: str) -> Optional[tuple[Rule, tuple[str, ...]]]:
    for rule in TRACKED:
        if rule.method == method:
            m = rule.pattern.match(path)
            if m:
                return rule, m.groups()
    return None


def link_from(referer: Optional[str], fallback: str) -> str:
    """The app page the request came from (its path + query), else ``fallback``."""
    if referer:
        u = urlparse(referer)
        if u.path.startswith("/") and u.path not in ("", "/") and not u.path.startswith(("/api/", "/media/")):
            return u.path + (f"?{u.query}" if u.query else "")
    return fallback


def _prune() -> None:
    cutoff = time.time() - KEEP_S
    for oid in [o.id for o in _ops.values() if o.finished_at and o.finished_at < cutoff]:
        _ops.pop(oid, None)
    if len(_ops) > MAX_KEPT:
        for o in sorted(_ops.values(), key=lambda x: x.started_at)[: len(_ops) - MAX_KEPT]:
            _ops.pop(o.id, None)


def start(rule: Rule, groups: tuple[str, ...], referer: Optional[str] = None) -> Op:
    try:
        fallback = rule.default_link.format(*groups)
    except (IndexError, KeyError):
        fallback = "/today"
    op = Op(id=uuid.uuid4().hex[:12], kind=rule.kind, title=rule.title, link=link_from(referer, fallback))
    with _lock:
        _prune()
        _ops[op.id] = op
    return op


def finish(op: Op, ok: bool, message: str = "", result: Any = None) -> None:
    with _lock:
        op.finished_at, op.ok, op.message = time.time(), ok, message[:300]
        op.result = result


def drop(op: Op) -> None:
    """Forget an op that turned out not to be one (e.g. a 401 before login)."""
    with _lock:
        _ops.pop(op.id, None)


def active_items() -> list[dict[str, Any]]:
    with _lock:
        return [o.running_item() for o in _ops.values() if o.finished_at is None]


def outcome(op_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        o = _ops.get(op_id)
        if o is None or o.finished_at is None:
            return None
        return {"ok": bool(o.ok), "message": o.message or ("Đã xong — bấm để xem" if o.ok else "Bị lỗi")}


def latest(kind: str, *, claim: bool = False) -> Optional[dict[str, Any]]:
    """The newest unclaimed op of ``kind``: ``{op_id, status: running|done|error,
    message, result}``; ``claim`` marks a finished one as taken (shown once)."""
    with _lock:
        ops = [o for o in _ops.values() if o.kind == kind and not o.claimed]
        if not ops:
            return None
        o = max(ops, key=lambda x: x.started_at)
        status = "running" if o.finished_at is None else ("done" if o.ok else "error")
        out = {"op_id": o.id, "status": status, "message": o.message, "started_at": _iso(o.started_at),
               "result": o.result if status == "done" else None}
        if claim and status != "running":
            o.claimed = True
        return out


def reset() -> None:
    """Tests."""
    with _lock:
        _ops.clear()


__all__ = ["TRACKED", "Rule", "Op", "match", "link_from", "start", "finish", "drop", "active_items", "outcome", "latest", "reset"]
