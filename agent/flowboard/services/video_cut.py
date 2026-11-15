"""✂️ Cắt video — a tool of its own (menu "Cắt video", ``/tools/cut``): links or files → many short videos, no dubbing.

One source video is a *session*: download it (``video_fetch``, like dubbing) → Whisper hears it (the pyvideotrans venv,
when this machine has it) → the AI picks the parts from the transcript, following the seller's request ("mỗi đoạn một
mẹo") or its own pick of the moments worth a short video, or the video is spread evenly → (when asked) stop so the rows
can be checked → ffmpeg cuts every part from the source (exact, re-encoded). Every part becomes

* a clip in "Clip của tôi" (board ``template_id: "cut_part"``): download it, schedule it, post it, dub it later, and
* an editing project — a :class:`dub.Job` of kind ``"cut"`` (mode "sub": the part keeps its own sound, subtitles off
  until switched on) — so the dubbing editor edits one part, or every part at once with "⇪ Áp cho cả loạt": subtitles
  from the words heard (or translated), blur boxes, output format + background, frame, sticker, key moments, presets.
  Its lines are the session's Whisper lines inside the part, moved to start at 0.

The parts of every link pasted together share one batch (``run_id``). Sessions live in ``<media>/cut/<id>/session.json``
on this machine; the parts are clips (synced) whose projects keep a snapshot on the clip, like dubbed videos.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Asset, Board
from flowboard.services import dub, dub_names, dub_split
from flowboard.services import media as media_service
from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError
from flowboard.services.video_export import probe_clip

logger = logging.getLogger(__name__)

MAX_DURATION_S = 60 * 60
MAX_LINKS = 10
#: sessions waiting + running at once
MAX_QUEUE = 20
#: ai = the AI picks; prompt = the seller's request; manual = "Tự cắt", the seller types each part's start / end / name
#: (one video at a time); even = spread evenly (the assistant and "✨ Gợi ý lại" still offer it)
HOWS = ("ai", "prompt", "manual", "even")
PROMPT_MAX = 4000
#: saved cut prompts ("Prompt đã lưu"): AppSetting in the account's database, [{id, name, text}]
PROMPTS_KEY = "cut_prompts"
MAX_SAVED_PROMPTS = 30
#: languages offered for the titles the AI writes (Vietnamese names — they go into the prompt as written)
TITLE_LANGS = ("Việt", "Tây Ban Nha", "Anh", "Bồ Đào Nha", "Pháp", "Đức", "Indonesia", "Thái", "Nhật", "Hàn", "Trung")
#: the saved prompt an account starts with (edit / delete it like any other)
DEFAULT_PROMPT_NAME = "Hook TikTok · 70–150 giây · tiêu đề từng đoạn"
DEFAULT_PROMPT = """Gợi ý cho tôi 1 tiêu đề (Name) tối ưu nhất để đăng TikTok thỏa mãn các điều kiện:
- Tiêu đề chứa hook hoặc tạo sự tò mò/kịch tính cao nhất, đạt chuẩn SEO TikTok để thu hút người xem và dễ viral.
- Được viết bằng NGÔN NGỮ TIÊU ĐỀ đã chọn (độ dài từ 3 đến 8 từ).
- Tuyệt đối KHÔNG chứa tên riêng của nhân vật, hãy thay bằng các từ chung (cô gái, chàng trai, người phụ nữ, người đàn ông...).
Lấy tiêu đề đó gán cho biến (Name).

NHIỆM VỤ PHÂN TÍCH VÀ CẮT:
Quét toàn bộ video từ giây đầu tiên đến giây cuối cùng để trích xuất TẤT CẢ các đoạn thỏa mãn điều kiện.
Số lượng đoạn cắt là HOÀN TOÀN TỰ ĐỘNG, từ 2 đoạn trở lên. Video có bao nhiêu đoạn đạt tiêu chuẩn thì trích xuất hết, không bỏ sót.

TIÊU CHÍ CHỌN ĐOẠN CẮT (BẮT BUỘC):
1. Hook: câu thứ 1 hoặc thứ 2 của mỗi đoạn phải đủ giật gân, kịch tính, gây sốc hoặc gây tò mò để giữ người xem đến hết clip. Đoạn không có hook mạnh ở 2 câu đầu thì BỎ QUA.
2. Thời lượng: mỗi đoạn dài trên 70 giây và ngắn hơn 2 phút 30 giây (70s < thời lượng < 150s).
3. Bỏ Intro & Outro:
- Bỏ Intro (khoảng 15-30 giây đầu nếu là nội dung lặp lại / preview).
- Bỏ Outro (khoảng 20 giây cuối: lời cảm ơn, MC giao lưu / tóm tắt, hoặc clip chèn nhạc).
4. Tiêu đề từng đoạn (title_bottom_N): viết bằng NGÔN NGỮ TIÊU ĐỀ đã chọn, 3-8 từ, có hook, giật gân, không chứa tên riêng."""
DEFAULT_MIN_S, DEFAULT_MAX_S = 30.0, 60.0
TAG_PREFIX = "flowboard-cut:"
LLM_TIMEOUT_S = 240
#: a line shorter than this inside a part is dropped (a word clipped by the cut)
MIN_LINE_S = 0.2

STATUSES = ("queued", "running", "review", "cutting", "done", "error")
BUSY = ("queued", "running", "cutting")


class CutError(RuntimeError):
    """Said to the person in front of the screen."""


@dataclass
class Session:
    id: str
    run_id: str
    url: Optional[str] = None
    source_media_id: Optional[str] = None
    how: str = "ai"
    prompt: str = ""
    min_s: float = DEFAULT_MIN_S
    max_s: float = DEFAULT_MAX_S
    max_parts: int = 0
    review: bool = False
    channel_id: Optional[int] = None
    status: str = "queued"
    phase: str = "Đang chờ"
    progress: int = 0
    title: str = ""
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    language: str = ""
    #: the whole video heard once: [{start, end, text}]; ``heard`` = Whisper ran (an empty list then = no speech)
    segments: list[dict] = field(default_factory=list)
    heard: bool = False
    prepared: bool = False
    #: the cut asked for [{start, end, title}], who picked it (ai | even | manual) and what to tell the seller about it
    rows: list[dict] = field(default_factory=list)
    by: str = ""
    note: str = ""
    #: one title for the whole video, when the request asks for one ("Name")
    name: str = ""
    #: the language the AI writes the titles in ("" = what the request says, else Vietnamese)
    title_lang: str = ""
    #: "🔍 Phân tích" first: the video is downloaded and heard, then waits (status review, no rows) for the seller to
    #: type the parts or ask the AI — with the real length known
    ask: bool = False
    #: Whisper in the background of an analysed video ("" = not asked / an older session, wait, run, done, skip, error):
    #: the parts can be typed and cut while it runs; only the AI's pick and the subtitles wait for it
    hear: str = ""
    hear_progress: int = 0
    hear_error: str = ""
    hear_stop: bool = False
    #: "Sáng / tối" set on the cut page: every part starts with it (dub.normalize_adjust), None = untouched
    adjust: Optional[dict] = None
    #: "Tốc độ" set on the cut page (0.8–3): every part is exported that much faster / slower; None = untouched
    speed: Optional[float] = None
    volume: Optional[float] = None
    #: the parts cut so far [{index, start, end, title, job_id, board_id, media_id}]
    parts: list[dict] = field(default_factory=list)
    #: "★ Mẫu chỉnh sửa" picked for this cut (dub.normalize_look_preset): every new part comes out in that look
    #: (9:16 frame, background, sticker, blur boxes…) — rendered right after it is cut; None = the raw pieces
    look: Optional[dict] = None
    error: Optional[str] = None
    stop: bool = False
    started_at: float = field(default_factory=time.time)
    position: int = 0
    work: Optional[Path] = None

    SAVED = ("id", "run_id", "url", "source_media_id", "how", "prompt", "min_s", "max_s", "max_parts", "review", "channel_id",
             "status", "phase", "progress", "title", "duration_s", "width", "height", "language", "segments", "heard", "prepared",
             "rows", "by", "note", "name", "title_lang", "ask", "hear", "hear_progress", "hear_error", "adjust", "speed", "volume", "parts", "look",
             "error", "started_at", "position")

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.SAVED}


SESSIONS: dict[str, Session] = {}
_LOCK = threading.Lock()


def _root() -> Path:
    return media_service.MEDIA_CACHE_DIR / "cut"


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# ── options ────────────────────────────────────────────────────────────────

def normalize_lengths(min_s: Any, max_s: Any) -> tuple[float, float]:
    """``(min, max)`` seconds of one part: 5 s … 20 min. ``min == max`` = "Tuỳ chỉnh": every part exactly that long
    (the last one takes what is left)."""
    try:
        lo = float(min_s)
    except (TypeError, ValueError):
        lo = DEFAULT_MIN_S
    try:
        hi = float(max_s)
    except (TypeError, ValueError):
        hi = DEFAULT_MAX_S
    if abs(hi - lo) < 0.05:  # one length typed by the seller
        lo = hi = max(5.0, min(1200.0, lo))
        return round(lo, 1), round(hi, 1)
    lo = max(5.0, min(600.0, lo))
    hi = max(lo + 5.0, min(1200.0, hi))
    return round(lo, 1), round(hi, 1)


def normalize_how(how: Any) -> str:
    return how if how in HOWS else "ai"


def manual_rows(raw: Any) -> list[dict[str, Any]]:
    """"Tự cắt": the parts the seller typed, checked one by one — start and end (seconds), a name (required), a second
    line (optional). The video's length is not known yet: ends past it are cut back once it is downloaded."""
    if not isinstance(raw, list) or not raw:
        raise CutError("Nhập ít nhất một đoạn: giờ bắt đầu, giờ kết thúc và tên đoạn")
    if len(raw) > dub_split.MAX_PARTS:
        raise CutError(f"Tối đa {dub_split.MAX_PARTS} đoạn một video")
    rows: list[dict[str, Any]] = []
    bad: list[str] = []
    for i, r in enumerate(raw, 1):
        r = r if isinstance(r, dict) else {}
        try:
            a, b = float(r.get("start")), float(r.get("end"))
            if not (a == a and b == b):  # NaN
                raise ValueError
        except (TypeError, ValueError):
            bad.append(f"Đoạn {i}: thiếu giờ bắt đầu hoặc kết thúc")
            continue
        title = dub_split._clean_title(r.get("title"))
        if a < 0:
            bad.append(f"Đoạn {i}: giờ bắt đầu không được âm")
        elif b <= a:
            bad.append(f"Đoạn {i}: giờ kết thúc phải sau giờ bắt đầu")
        elif b - a < dub_split.CUT_MIN:
            bad.append(f"Đoạn {i}: ngắn hơn {dub_split.CUT_MIN:g} giây")
        elif a >= MAX_DURATION_S:
            bad.append(f"Đoạn {i}: bắt đầu quá {MAX_DURATION_S // 60} phút (video dài tối đa {MAX_DURATION_S // 60} phút)")
        elif not title:
            bad.append(f"Đoạn {i}: thiếu tên đoạn")
        row = {"start": round(a, 2), "end": round(b, 2), "title": title}
        if dub_split._clean_subtitle(r.get("subtitle")):
            row["subtitle"] = dub_split._clean_subtitle(r.get("subtitle"))
        rows.append(row)
    if bad:
        raise CutError("; ".join(bad[:5]) + (f" (và {len(bad) - 5} lỗi khác)" if len(bad) > 5 else ""))
    return rows


def normalize_max_parts(n: Any) -> int:
    try:
        v = int(n or 0)
    except (TypeError, ValueError):
        v = 0
    return max(0, min(dub_split.MAX_PARTS, v))


def clean_prompt(text: Any) -> str:
    """A cut request as typed — a long, structured prompt keeps its lines (spaces tidied, blank runs collapsed)."""
    lines = [re.sub(r"[ \t\f\v]+", " ", ln).strip() for ln in str(text or "").replace("\r", "").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()[:PROMPT_MAX]


def normalize_title_lang(lang: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\-]", " ", str(lang or ""))).strip()[:30]


# ── saved prompts ──────────────────────────────────────────────────────────

def normalize_prompts(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict):
            continue
        text = clean_prompt(p.get("text"))
        if not text:
            continue
        pid = re.sub(r"[^A-Za-z0-9_-]", "", str(p.get("id") or ""))[:24]
        if not pid or pid in seen:
            pid = _uid()
        seen.add(pid)
        name = re.sub(r"\s+", " ", str(p.get("name") or "")).strip()[:60] or f"Prompt {len(out) + 1}"
        out.append({"id": pid, "name": name, "text": text})
    return out[:MAX_SAVED_PROMPTS]


def saved_prompts() -> list[dict[str, str]]:
    """The account's saved cut prompts; an account that never saved any starts with the built-in one."""
    from flowboard.db import get_session
    from flowboard.db.models import AppSetting

    with get_session() as db:
        row = db.get(AppSetting, PROMPTS_KEY)
        if row is None:
            return [{"id": "default", "name": DEFAULT_PROMPT_NAME, "text": DEFAULT_PROMPT}]
        try:
            return normalize_prompts(json.loads(row.value or "[]"))
        except (TypeError, ValueError):
            return []


def save_prompts(raw: Any) -> list[dict[str, str]]:
    from flowboard.db import get_session
    from flowboard.db.models import AppSetting

    prompts = normalize_prompts(raw)
    with get_session() as db:
        row = db.get(AppSetting, PROMPTS_KEY) or AppSetting(key=PROMPTS_KEY, value="")
        row.value = json.dumps(prompts, ensure_ascii=False)
        db.add(row)
        db.commit()
    return prompts


# ── persistence ────────────────────────────────────────────────────────────

def persist(s: Session) -> None:
    try:
        work = s.work or (_root() / s.id)
        work.mkdir(parents=True, exist_ok=True)
        s.work = work
        (work / "session.json").write_text(json.dumps(s.to_dict(), ensure_ascii=False), encoding="utf-8")
    except OSError as exc:  # noqa: BLE001 — best effort
        logger.warning("video_cut: could not save session %s: %s", s.id, exc)


def _from_dict(d: dict, work: Path) -> Session:
    s = Session(id=str(d.get("id") or work.name), run_id=str(d.get("run_id") or work.name))
    for k in Session.SAVED:
        if k in d and k not in ("id", "run_id"):
            setattr(s, k, d[k])
    s.work = work
    s.segments = [x for x in s.segments or [] if isinstance(x, dict)]
    s.rows = [x for x in s.rows or [] if isinstance(x, dict)]
    s.parts = [x for x in s.parts or [] if isinstance(x, dict)]
    if s.status in BUSY:
        s.status = "error"
        s.error = "Agent khởi động lại giữa chừng — bấm ↻ Làm lại"
    if s.hear in ("wait", "run"):  # the agent stopped while it was listening: "🎧 Nghe lời" starts it again
        s.hear, s.hear_progress = "", 0
    return s


def load_sessions() -> None:
    root = _root()
    if not root.is_dir():
        return
    for meta in root.glob("*/session.json"):
        try:
            d = json.loads(meta.read_text(encoding="utf-8"))
            sid = str(d.get("id") or meta.parent.name)
            if sid in SESSIONS:
                continue
            SESSIONS[sid] = _from_dict(d, meta.parent)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("video_cut: skipped %s: %s", meta, exc)


def _mine(s: Session) -> bool:
    """A session of the account whose data folder is open (SESSIONS outlives a switch of account)."""
    return s.work is None or s.work.parent == _root()


def sessions() -> list[Session]:
    load_sessions()
    return sorted((s for s in SESSIONS.values() if _mine(s)), key=lambda s: (s.started_at, s.position), reverse=True)


def find(session_id: str) -> Optional[Session]:
    load_sessions()
    s = SESSIONS.get(session_id)
    return s if s is not None and _mine(s) else None


# ── what the page sees ─────────────────────────────────────────────────────

def _part_view(p: dict[str, Any]) -> dict[str, Any]:
    out = dict(p)
    job = dub.JOBS.get(str(p.get("job_id") or ""))
    if job is not None:
        out.update(name=job.name or p.get("title"), status=job.status, phase=job.phase, progress=job.progress,
                   media_id=job.media_id, error=job.error, board_id=job.board_id or p.get("board_id"),
                   edited=bool(job.outputs), duration_s=round(job.duration_s or (p["end"] - p["start"]), 1),
                   lines=len(job.segments), sub_lang=job.sub_lang)
    else:
        out.update(name=p.get("title"), status="missing", duration_s=round(float(p.get("end", 0)) - float(p.get("start", 0)), 1))
    return out


def public(s: Session, *, brief: bool = False) -> dict[str, Any]:
    dub.load_jobs()
    out = {k: getattr(s, k) for k in Session.SAVED if k not in ("segments",)}
    out["lines"] = len(s.segments)
    # "Dừng" was pressed and the work is winding down (a moment): the button says so instead of looking unpressed
    out["stopping"] = bool(s.stop and s.status in BUSY)
    out["parts"] = [_part_view(p) for p in s.parts]
    if s.source_media_id:
        out["source_url"] = f"/media/{s.source_media_id}"
    if not brief:
        out["segments"] = s.segments
    return out


def part_jobs(*, run_id: Optional[str] = None, session_id: Optional[str] = None) -> list[dub.Job]:
    """The editing projects of the parts — of one session, or of every link pasted together — in cut order."""
    dub.load_jobs()
    picked = [s for s in sessions() if (session_id and s.id == session_id) or (run_id and s.run_id == run_id)]
    picked.sort(key=lambda s: (s.started_at, s.position))
    out: list[dub.Job] = []
    for s in picked:
        for p in sorted(s.parts, key=lambda p: int(p.get("index") or 0)):
            job = dub.find_job(str(p.get("job_id") or ""))
            if job is not None:
                out.append(job)
    return out


def status() -> dict[str, Any]:
    st = dub.status()
    return {"whisper": bool(st.get("available")), "whisper_reason": "" if st.get("available") else st.get("reason", ""),
            "remotion": bool(st.get("remotion")), "max_minutes": MAX_DURATION_S // 60, "max_links": MAX_LINKS,
            "max_parts": dub_split.MAX_PARTS, "prompt_max": PROMPT_MAX, "title_langs": list(TITLE_LANGS),
            "slow_reason": st.get("slow_reason", ""),
            "default_min": DEFAULT_MIN_S, "default_max": DEFAULT_MAX_S}


# ── start / queue ──────────────────────────────────────────────────────────

def start(*, links: list[str], media: list[dict[str, Any]], how: str = "ai", prompt: str = "", min_s: Any = None,
          max_s: Any = None, max_parts: Any = 0, review: bool = False, channel_id: Optional[int] = None,
          look: Optional[dict] = None, title_lang: Any = "", rows: Any = None,
          analyze: bool = False) -> tuple[str, list[Session]]:
    """One session per link / file, all in one run (their parts are one batch in the editor). ``look`` = a saved
    "★ Mẫu chỉnh sửa" (:func:`dub.look_preset`) every part is rendered in. ``how == "manual"`` ("Tự cắt") takes the
    parts from ``rows`` and one video only. Returns ``(run_id, sessions)``."""
    from flowboard.services.video_fetch import extract_url

    items: list[tuple[str, Any]] = []
    for raw in links:
        text = str(raw or "").strip()
        if text:
            items.append(("url", extract_url(text) or text))
    for m in media:
        if isinstance(m, dict) and m.get("media_id"):
            items.append(("media", m))
    if not items:
        raise CutError("Dán ít nhất một link video hoặc chọn một file")
    if len(items) > MAX_LINKS:
        raise CutError(f"Tối đa {MAX_LINKS} video một lần")
    busy = [s for s in sessions() if s.status in ("queued", "running")]
    if len(busy) + len(items) > MAX_QUEUE:
        raise CutError(f"Đang có {len(busy)} video chờ cắt — đợi bớt rồi thêm tiếp")
    how = normalize_how(how)
    prompt = clean_prompt(prompt)
    if analyze:  # only download + hear now; how to cut is chosen per video afterwards
        how, prompt = "manual", ""
    if how == "prompt" and not prompt:
        raise CutError("Gõ yêu cầu cắt (VD: “mỗi đoạn một mẹo”) hoặc chọn “AI tự chọn đoạn hay”")
    typed: list[dict[str, Any]] = []
    if how == "manual" and not analyze:
        if len(items) != 1:
            raise CutError("Tự cắt nhập giờ cho từng video — mỗi lần một link hoặc một file")
        typed = manual_rows(rows)
    lo, hi = normalize_lengths(DEFAULT_MIN_S if min_s is None else min_s, DEFAULT_MAX_S if max_s is None else max_s)
    run_id = _uid()
    now = time.time()
    made: list[Session] = []
    for i, (kind, value) in enumerate(items):
        s = Session(id=_uid(), run_id=run_id, how=how, prompt=prompt, min_s=lo, max_s=hi,
                    max_parts=normalize_max_parts(max_parts), review=bool(review), channel_id=channel_id,
                    title_lang=normalize_title_lang(title_lang), ask=bool(analyze),
                    look=dub.normalize_look_preset(look) if look else None, started_at=now, position=i)
        if kind == "url":
            s.url = str(value)[:2000]
        else:
            s.source_media_id = str(value["media_id"])[:64]
            s.title = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", str(value.get("name") or "")).strip()[:80]
        if typed:
            s.rows, s.by = [dict(r) for r in typed], "manual"
        s.work = _root() / s.id
        SESSIONS[s.id] = s
        persist(s)
        made.append(s)
    _pump()
    return run_id, made


def _pump() -> None:
    """One video heard at a time (Whisper wants the GPU); cutting runs in its own thread."""
    with _LOCK:
        if any(s.status == "running" for s in SESSIONS.values()):
            return
        waiting = sorted((s for s in SESSIONS.values() if s.status == "queued" and _mine(s)), key=lambda s: (s.started_at, s.position))
        for i, s in enumerate(waiting[1:], 1):
            s.phase = f"Chờ đến lượt ({i} video trước)"
        if not waiting:
            return
        s = waiting[0]
        s.status, s.phase, s.progress = "running", "Bắt đầu", 1
    persist(s)
    threading.Thread(target=_run, args=(s,), name=f"cut-{s.id}", daemon=True).start()


def _set(s: Session, phase: str, progress: float) -> None:
    s.phase, s.progress = phase, int(progress)
    if s.stop:
        raise CutError("Đã dừng theo yêu cầu")


def _run(s: Session) -> None:
    try:
        if not s.prepared:
            _prepare(s)
        if s.ask and not s.rows:
            # "🔍 Phân tích": ready — the seller now types the parts or asks the AI (the card shows the editor).
            # The words are heard in the background: nothing waits for Whisper but the AI's pick and the subtitles.
            s.status, s.phase, s.progress = "review", "Đã tải xong — chọn các đoạn rồi bấm ✂️ Cắt", 100
            hear_later(s)
            return
        if not s.heard and s.hear != "skip":
            _hear(s, progress=lambda p: _set(s, "Đang nghe lời trong video (Whisper)", 8 + p * 0.5), stop=lambda: s.stop)
        if s.how == "manual":
            # "Tự cắt": the seller's parts, now checked against the video's real length
            _set(s, "Đang kiểm các đoạn đã nhập", 62)
            typed = list(s.rows)
            s.rows, s.by = check_rows(s, typed), "manual"
            cut_back = [i for i, (a, b) in enumerate(zip(typed, s.rows), 1) if b["end"] < float(a.get("end") or 0) - 0.01]
            s.note = (f"Đoạn {', '.join(map(str, cut_back))} kết thúc sau cuối video ({s.duration_s:.0f} giây) — đã lấy tới hết video."
                      if cut_back else "")
        else:
            _set(s, "AI đang chọn đoạn cắt" if s.how != "even" and s.segments else "Đang chia đoạn", 62)
            res = asyncio.run(suggest(s))
            s.rows, s.by, s.note, s.name = res["rows"], res["by"], res["note"], res.get("name", "")
        if not s.rows:
            raise CutError("Không chia được đoạn nào")
        if s.review:
            s.status, s.phase, s.progress = "review", "Xem lại các đoạn rồi bấm ✂️ Cắt", 100
        else:
            _cut_all(s, s.rows, base=70)
    except (CutError, dub.DubError, dub_split.SplitError) as exc:
        s.status, s.error = "error", str(exc)
        logger.warning("video_cut: session %s failed: %s", s.id, exc)
    except Exception as exc:  # noqa: BLE001 — never die silently
        s.status, s.error = "error", f"{type(exc).__name__}: {exc}"
        logger.exception("video_cut: session %s crashed", s.id)
    finally:
        persist(s)
        _pump()


def _prepare(s: Session) -> None:
    """Download (link) → probe; a video that was not sent to be analysed is heard right away (Whisper)."""
    from flowboard.services.video_fetch import FetchError, extract_url, fetch_video

    assert s.work is not None
    s.work.mkdir(parents=True, exist_ok=True)
    if s.url and not s.source_media_id:
        _set(s, "Đang tải video về", 3)
        media_id = uuid.uuid4().hex
        try:
            path, title = fetch_video(s.url, media_id, media_service.MEDIA_CACHE_DIR, max_duration_s=MAX_DURATION_S,
                                      stop=lambda: s.stop)
        except FetchError as exc:
            if s.stop:
                raise CutError("Đã dừng theo yêu cầu") from exc
            raise CutError(f"Không tải được video: {exc}") from exc
        s.url = extract_url(s.url) or s.url
        mime = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}.get(path.suffix.lower(), "video/mp4")
        with get_session() as db:
            db.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(path), mime=mime))
            db.commit()
        s.source_media_id = media_id
        if title and not s.title:
            s.title = title[:80]
        persist(s)
    src = _source(s)
    info = probe_clip(src)
    if info is None or info.duration <= 0:
        raise CutError("Không đọc được video")
    if info.duration > MAX_DURATION_S:
        raise CutError(f"Video dài {info.duration / 60:.0f} phút — tối đa {MAX_DURATION_S // 60} phút")
    s.duration_s, s.width, s.height = float(info.duration), int(info.width), int(info.height)
    s.segments, s.heard = [], False
    s.prepared = True
    persist(s)
    if not s.ask:
        _hear(s, progress=lambda p: _set(s, "Đang nghe lời trong video (Whisper)", 8 + p * 0.5), stop=lambda: s.stop)
        persist(s)


# ── hearing the words (Whisper) ────────────────────────────────────────────

#: one video heard at a time on this machine (the card, or every CPU core)
_WHISPER_LOCK = threading.Lock()


def _hear(s: Session, *, progress: Any, stop: Any) -> None:
    """Whisper hears the whole video once → ``s.segments`` (``heard``). A machine without Whisper leaves it unheard."""
    src = _source(s)
    info = probe_clip(src)
    if info is None or not info.has_audio:
        s.segments, s.heard = [], True  # nothing to hear
        return
    if not dub.status().get("available"):
        return
    assert s.work is not None
    s.work.mkdir(parents=True, exist_ok=True)
    wav = s.work / "speech16.wav"
    out = s.work / "asr.json"
    with _WHISPER_LOCK:
        progress(0)
        dub._extract_wav(dub._ffmpeg(), src, wav, 16000, True)
        hint = dub_names.asr_hint(s.title) if s.url else ""
        try:
            dub._runner("transcribe", str(wav), str(out), "auto", "-", hint, progress=progress, stop=stop)
        finally:
            wav.unlink(missing_ok=True)
    data = json.loads(out.read_text(encoding="utf-8"))
    s.language = str(data.get("language") or "")
    s.segments = [{"start": round(float(x["start"]), 3), "end": round(float(x["end"]), 3), "text": str(x.get("text") or "").strip()}
                  for x in data.get("segments") or [] if float(x["end"]) > float(x["start"])]
    s.heard = True


def hear_later(s: Session) -> Session:
    """Hear this video in the background (one at a time): the card stays usable — parts typed and cut meanwhile."""
    if s.heard or s.hear in ("wait", "run") or not s.prepared:
        return s
    if not dub.status().get("available"):
        return s
    s.hear, s.hear_progress, s.hear_error, s.hear_stop = "wait", 0, "", False
    persist(s)
    threading.Thread(target=_hear_bg, args=(s,), name=f"cut-hear-{s.id}", daemon=True).start()
    return s


def hear_skip(s: Session) -> Session:
    """"Bỏ nghe lời": stop listening (the parts are typed by hand; no AI pick, no subtitles from the words)."""
    if s.hear in ("wait", "run"):
        s.hear_stop = True
        if s.hear == "wait":
            s.hear = "skip"
        persist(s)
    return s


def _hear_bg(s: Session) -> None:
    def progress(p: int) -> None:
        s.hear, s.hear_progress = "run", int(p)

    def gone() -> bool:
        return s.hear_stop or SESSIONS.get(s.id) is not s

    try:
        # waiting for the video before it: asked to stop meanwhile = never started
        while not _WHISPER_LOCK.acquire(timeout=1.0):
            if gone():
                s.hear = "skip"
                return
        _WHISPER_LOCK.release()
        if gone():
            s.hear = "skip"
            return
        _hear(s, progress=progress, stop=gone)
        s.hear, s.hear_progress = ("done", 100) if s.heard else ("", 0)
        if s.heard:
            _lines_for_parts(s)
    except (CutError, dub.DubError) as exc:
        s.hear, s.hear_error = ("skip", "") if s.hear_stop else ("error", str(exc)[:300])
    except Exception as exc:  # noqa: BLE001 — never die silently
        s.hear, s.hear_error = "error", f"{type(exc).__name__}: {exc}"[:300]
        logger.exception("video_cut: hearing %s crashed", s.id)
    finally:
        if SESSIONS.get(s.id) is s:
            persist(s)


def _lines_for_parts(s: Session) -> None:
    """Parts cut before the video was heard get their lines now (subtitles can be switched on in the editor)."""
    for p in s.parts:
        job = dub.find_job(str(p.get("job_id") or ""))
        if job is None or job.segments or job.status in ("queued", "running", "rendering"):
            continue
        job.segments = part_lines(s, float(p["start"]), float(p["end"]))
        job.language = s.language
        if job.segments:
            dub.persist(job)


def _source(s: Session) -> Path:
    p = media_service.cached_path(s.source_media_id or "")
    if not p or not Path(p).is_file():
        raise CutError("Không thấy file video gốc trên máy này")
    return Path(p)


# ── picking the parts ──────────────────────────────────────────────────────

def _as_job(s: Session) -> dub.Job:
    """The session seen as a dub job, so dub_split's helpers (pauses, even split, AI ranges) work on it."""
    job = dub.Job(id=s.id, url=None, source_media_id=s.source_media_id, name=s.title or "Video", title=s.title,
                  duration_s=s.duration_s)
    job.segments = [dub.Segment(float(x["start"]), float(x["end"]), str(x["text"]), str(x["text"])) for x in s.segments]
    return job


def exact_rows(s: Session) -> list[dict[str, Any]]:
    """"Tuỳ chỉnh": parts of exactly ``min_s`` seconds one after another — a cut moves to the pause between two lines
    when one is within a couple of seconds — and the last part is whatever is left (a tail under 3 s joins it)."""
    job = _as_job(s)
    dur, step = float(s.duration_s or 0), float(s.min_s)
    if dur <= 0:
        return []
    pts = dub_split.cut_points(job)
    spans: list[tuple[float, float]] = []
    start, k = 0.0, 1
    while k * step < dur - dub_split.CUT_MIN and len(spans) < dub_split.MAX_PARTS - 1:
        cut = dub_split.snap(k * step, pts)
        if cut - start >= dub_split.CUT_MIN and dur - cut >= dub_split.CUT_MIN:
            spans.append((start, cut))
            start = cut
        k += 1
    spans.append((start, dur))
    return dub_split._titled(job, spans)


def even_rows(s: Session) -> list[dict[str, Any]]:
    if s.min_s == s.max_s:
        return exact_rows(s)
    target = (s.min_s + s.max_s) / 2
    if s.max_parts and s.duration_s / target > s.max_parts:
        target = s.duration_s / s.max_parts
    rows = dub_split.suggest_even(_as_job(s), target)
    if s.max_parts and len(rows) > s.max_parts:
        rows = rows[:s.max_parts]
        rows[-1]["end"] = round(s.duration_s, 2)
    return rows


_SYSTEM = (
    "You cut ONE video into short vertical videos for TikTok / Facebook Reels / YouTube Shorts. You get its transcript in "
    "the video's own language: one numbered line per spoken sentence with its time. Rules: a part is a run of whole "
    "consecutive lines (never cut inside a line); parts keep the video's order and never overlap; every part must stand on "
    "its own — a viewer who never saw the rest understands it: it opens on a hook or the start of an idea and ends when "
    "that idea is finished. Follow THE SELLER'S REQUEST when there is one (what to keep, what to leave out, how many, how "
    "long) — it wins over the other rules. Without a request keep only the moments worth a short video on their own (a "
    "strong hook, one whole idea, a payoff or a surprise) and leave out intros, outros, sponsor reads, greetings, filler "
    "and repeats. Keep each part inside the length asked for when the content allows; never more parts than asked for. "
    "Give each part a title about what that part shows. When the request sets rules for the titles (language, number of "
    "words, a hook, no proper names, SEO…), write every title by those rules; otherwise a catchy Vietnamese title (<= 60 "
    "chars), no clickbait lies, no hashtags, no quotes. A TITLE LANGUAGE line, when given, is the language of every "
    "title and of the name — it overrides any other language instruction. When the request also asks for ONE title for "
    "the whole video (it may call it Name), put it in \"name\" by the request's rules; otherwise name is empty. The "
    "request may describe its own output layout (one line, 'start_1 | end_1 | title_bottom_1', mm:ss times…): ignore that "
    "layout — answer in the JSON below; a per-part title it names (title_bottom_N…) goes in that part's \"title\", and "
    "the times come from the line numbers. If the request cannot be met (the video has no such moment), return the closest parts and say why in "
    "\"note\" (one Vietnamese sentence); otherwise note is empty. Output ONLY one JSON object: "
    "{\"name\": str, \"parts\": [{\"from\": <first line number>, \"to\": <last line number>, \"title\": str}], \"note\": str}"
)


def ai_prompt(s: Session) -> str:
    lines = [f"[{i}] ({x['start']:.1f}-{x['end']:.1f}s) {str(x['text'])[:220]}" for i, x in enumerate(s.segments, 1)]
    want = ((f"Each short video: about {s.min_s:.0f} seconds (cut at the end of the sentence nearest to it; the last one "
             "may be shorter — it takes what is left)") if s.min_s == s.max_s else f"Each short video: {s.min_s:.0f}-{s.max_s:.0f} seconds"
            ) + (f"; at most {s.max_parts} videos" if s.max_parts else "")
    req = s.prompt if s.how == "prompt" else ""
    if req:  # a request sets its own length and number of parts (the form has no pickers for it)
        want = ("Length of each short video and how many: as the request below says; where it says nothing, 30-180 seconds "
                "each and as many as the content gives" + (f" (never more than {s.max_parts})" if s.max_parts else ""))
    lang = f"TITLE LANGUAGE: tiếng {s.title_lang}\n" if s.title_lang and s.how != "even" else ""
    return (f"Video title: {s.title or '-'}\nVideo length: {s.duration_s:.0f} s. Language heard: {s.language or '?'}.\n{want}.\n"
            + lang
            + (f"THE SELLER'S REQUEST (follow it): {req}\nEND OF THE REQUEST.\n" if req else
               "No request from the seller: pick the moments that make the best short videos on their own.\n")
            + f"TRANSCRIPT ({len(lines)} lines):\n" + "\n".join(lines))


async def ai_rows(s: Session) -> tuple[list[dict[str, Any]], str, str]:
    prompt = ai_prompt(s)
    data: Optional[dict[str, Any]] = None
    for attempt in (1, 2):  # an answer that is not JSON (seen once from the Claude CLI) is asked again before giving up
        try:
            text = await run_llm("auto_prompt", prompt if attempt == 1 else prompt + "\n\nAnswer with the JSON object only.",
                                 system_prompt=_SYSTEM, timeout=LLM_TIMEOUT_S)
        except LLMError as exc:
            raise dub_split.SplitError(str(exc)) from exc
        try:
            data = dub_split._json_obj(text)
            break
        except dub_split.SplitError:
            logger.warning("video_cut %s: AI answer %d is not JSON: %.300s", s.id, attempt, text)
            if attempt == 2:
                raise
    assert data is not None
    rows = dub_split.parts_from_ai(_as_job(s), data)
    if s.max_parts:
        rows = rows[:s.max_parts]
    def tidy(v: Any, n: int) -> str:
        return re.sub(r"\s+", " ", str(v or "")).strip()[:n]

    return rows, tidy(data.get("note"), 240), tidy(data.get("name"), 120)


async def suggest(s: Session) -> dict[str, Any]:
    """``{rows, by: "ai" | "even", note}`` — the AI when asked and the video was heard; its failure → the even split."""
    if s.how in ("ai", "prompt"):
        if not s.segments:
            why = ("Video không có lời nói nên AI không chọn theo nội dung được" if s.heard else
                   "Máy này chưa nghe được lời trong video (cần Whisper của pyvideotrans) nên AI không chọn theo nội dung được")
            return {"rows": even_rows(s), "by": "even", "note": f"{why} — đã chia đều theo độ dài.", "name": ""}
        try:
            rows, note, name = await ai_rows(s)
            return {"rows": rows, "by": "ai", "note": note, "name": name}
        except dub_split.SplitError as exc:
            logger.warning("video_cut %s: AI pick failed, even split instead: %s", s.id, exc)
            return {"rows": even_rows(s), "by": "even", "note": f"AI chưa chọn được đoạn ({str(exc)[:160]}) — đã chia đều theo chỗ ngắt câu.", "name": ""}
    return {"rows": even_rows(s), "by": "even", "note": "", "name": ""}


async def suggest_again(s: Session, *, how: str, prompt: str, min_s: Any, max_s: Any, max_parts: Any,
                        title_lang: Any = None) -> dict[str, Any]:
    """"✨ Gợi ý lại" with other options (nothing is cut)."""
    if s.status in BUSY:
        raise CutError("Video này đang chạy — chờ xong")
    if not s.prepared:
        raise CutError("Video chưa tải xong — bấm ↻ Làm lại")
    if normalize_how(how) in ("ai", "prompt") and s.hear in ("wait", "run"):
        raise CutError(f"Tool đang nghe lời trong video ({s.hear_progress}%) — AI chọn đoạn theo nội dung được khi nghe xong. "
                       "Trong lúc chờ bạn tự nhập đoạn, hoặc chọn Chia đều.")
    s.how, s.prompt = normalize_how(how), clean_prompt(prompt)
    if s.how == "prompt" and not s.prompt:
        raise CutError("Gõ yêu cầu cắt trước")
    s.min_s, s.max_s = normalize_lengths(min_s, max_s)
    s.max_parts = normalize_max_parts(max_parts)
    if title_lang is not None:
        s.title_lang = normalize_title_lang(title_lang)
    res = await suggest(s)
    s.rows, s.by, s.note, s.name = res["rows"], res["by"], res["note"], res.get("name", "")
    persist(s)
    return res


# ── cutting ────────────────────────────────────────────────────────────────

def check_rows(s: Session, rows: Any) -> list[dict[str, Any]]:
    rows = dub_split.normalize_rows(rows, s.duration_s)
    if not rows:
        raise CutError("Chưa có đoạn nào để cắt")
    bad = [f"Đoạn {i}: {dub_split.row_problem(r, s.duration_s)}" for i, r in enumerate(rows, 1) if dub_split.row_problem(r, s.duration_s)]
    if bad:
        raise CutError("; ".join(bad[:4]))
    return rows


def cut(s: Session, rows: Any, how: Optional[str] = None, adjust: Any = None, speed: Any = None,
        volume: Any = None) -> Session:
    """Cut (or cut again) with these rows, in a thread. Part n reuses the project + clip of the old part n.
    ``how == "manual"``: the seller typed the rows (the card says "tự cắt")."""
    if s.status in BUSY:
        raise CutError("Video này đang chạy — chờ xong")
    if not s.prepared:
        raise CutError("Video chưa tải xong — bấm ↻ Làm lại")
    _source(s)
    rows = check_rows(s, rows)
    for p in s.parts:
        job = dub.JOBS.get(str(p.get("job_id") or ""))
        if job is not None and job.status in ("queued", "running", "rendering"):
            raise CutError(f"Video {p.get('index')} đang xuất — chờ xong rồi cắt lại")
    s.rows, s.by = rows, s.by or "manual"
    if speed is not None:  # the speed slider of the cut page (1 = back to the source's speed)
        s.speed = dub.normalize_speed(speed)
    if volume is not None:  # the volume slider of the cut page (1 = back to the source's loudness)
        s.volume = dub.normalize_volume(volume)
    if adjust is not None:  # the slider of the cut page ({} = back to untouched)
        s.adjust = dub.normalize_adjust(adjust) or {}
    if how == "manual":
        s.how = s.by = "manual"
    s.status, s.phase, s.progress, s.error, s.stop = "cutting", "Chuẩn bị cắt", 0, None, False
    persist(s)

    def go() -> None:
        try:
            _cut_all(s, rows, base=0)
        except (CutError, dub.DubError, dub_split.SplitError) as exc:
            s.status, s.error = "error", str(exc)
        except Exception as exc:  # noqa: BLE001
            s.status, s.error = "error", f"{type(exc).__name__}: {exc}"
            logger.exception("video_cut: cutting %s crashed", s.id)
        finally:
            persist(s)

    threading.Thread(target=go, name=f"cut-split-{s.id}", daemon=True).start()
    return s


def _cut_all(s: Session, rows: list[dict[str, Any]], *, base: int) -> None:
    ffmpeg = dub._ffmpeg()
    src = _source(s)
    s.status = "cutting"
    old = {int(p.get("index") or 0): p for p in s.parts}
    parts: list[dict[str, Any]] = []
    total = len(rows)
    name = (s.title or "Video").strip()[:60]
    for i, row in enumerate(rows, 1):
        _set(s, f"Đang cắt video {i}/{total}", base + (100 - base) * (i - 1) / total)
        media_id = uuid.uuid4().hex
        dst = media_service.MEDIA_CACHE_DIR / f"{media_id}.mp4"
        dub_split._cut(ffmpeg, src, row["start"], row["end"], dst, f"{TAG_PREFIX}{s.id}", stop=lambda: s.stop)
        with get_session() as db:
            db.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(dst), mime="video/mp4"))
            db.commit()
        title = row.get("title") or (f"{name} — Phần {i}/{total}" if total > 1 else name)
        job = _part_job(s, i, total, row, title, media_id, dst, old.get(i))
        if needs_render(job):
            # the piece is raw: render it in its look now (the dubbing queue, one at a time) so it comes out finished
            try:
                dub.render_job(job, lines=None, voice=None, style=None, keep_bgm=None, name=None)
            except dub.DubError as exc:
                job.error = f"Chưa áp được kiểu đã chỉnh — mở trình chỉnh sửa, bấm Xuất lại video ({exc})"
                dub.persist(job)
        parts.append({"index": i, "start": row["start"], "end": row["end"], "title": title, "subtitle": row.get("subtitle", ""), "job_id": job.id,
                      "board_id": job.board_id, "media_id": media_id, "at": time.time()})
        s.parts = parts + [p for k, p in sorted(old.items()) if k > i]
        persist(s)
    s.parts = parts  # parts past the new count keep their clips (the seller may have edited them), not listed here
    if s.adjust == {}:  # "back to untouched" was put on every part: nothing left to remember
        s.adjust = None
    if s.speed == 1.0:
        s.speed = None
    if s.volume == 1.0:
        s.volume = None
    s.status, s.phase, s.progress, s.error = "done", f"Đã cắt {total} video", 100, None


def needs_render(job: dub.Job) -> bool:
    """A part just cut is the raw piece. It is rendered at once when its project has something to put on it: a
    look (the cut's preset, or what the seller set before cutting again — 9:16 frame, background, blur boxes,
    sticker), subtitles to burn, or key-moment emphasis."""
    lay = dub.normalize_layout(job.layout)
    lay["texts"] = dub.shown_texts(lay)  # a title slot that is switched off puts nothing on the picture
    return (lay != dub.normalize_layout(None) or job.sub_lang != "none" or bool((job.highlights or {}).get("on")))


def part_lines(s: Session, start: float, end: float) -> list[dub.Segment]:
    """The session's lines inside [start, end], moved to start at 0 (a line the cut clips keeps its part)."""
    out = []
    for x in s.segments:
        a, b = max(float(x["start"]), start) - start, min(float(x["end"]), end) - start
        if b - a >= MIN_LINE_S:
            out.append(dub.Segment(round(a, 3), round(b, 3), str(x["text"]), str(x["text"])))
    return out


def _part_job(s: Session, index: int, total: int, row: dict[str, Any], title: str, media_id: str, path: Path,
              old: Optional[dict[str, Any]]) -> dub.Job:
    prev = dub.find_job(str(old.get("job_id") or "")) if old else None
    info = probe_clip(path)
    job = prev or dub.Job(id=uuid.uuid4().hex[:12], url=None, source_media_id=media_id, sub_lang="none")
    # what the title layers showed before this cut: a layer still showing it follows the new title
    was = {"title": dub.default_text(job, "title"), "subtitle": dub.default_text(job, "subtitle")} if prev is not None else {}
    job.url = None
    job.kind, job.mode = "cut", "sub"
    job.source_media_id = job.media_id = media_id
    job.cut = {"session_id": s.id, "run_id": s.run_id, "index": index, "total": total, "start": row["start"],
               "end": row["end"], "source_url": s.url, "source_title": s.title, "subtitle": row.get("subtitle", ""),
               "from_media_id": s.source_media_id}  # the video it was cut from: "✂️ đã cắt" on the grab list
    job.batch_id = s.run_id
    job.name = job.title = title[:80]
    if prev is None:
        job.channel_id = s.channel_id
        if s.look:  # the cut's "★ Mẫu chỉnh sửa": the part starts (and is rendered) in that look
            dub.apply_look(job, s.look)
    if prev is not None and (job.layout or {}).get("texts"):
        lay = dub.normalize_layout(job.layout)
        lay["texts"] = [dict(t, text=dub.default_text(job, t["role"])) if t["role"] != "text" and t["text"] in ("", was.get(t["role"]))
                        else t for t in lay["texts"]]
        job.layout = lay
    if s.adjust is not None:  # "Sáng / tối" of the cut page: every part, new or cut again
        job.layout = {**dub.normalize_layout(job.layout), "adjust": dub.normalize_adjust(s.adjust)}
    if s.speed is not None:  # "Tốc độ" of the cut page: every part, new or cut again
        job.layout = {**dub.normalize_layout(job.layout), "speed": dub.normalize_speed(s.speed)}
    if s.volume is not None:  # "Âm lượng" of the cut page: every part, new or cut again
        job.layout = {**dub.normalize_layout(job.layout), "volume": dub.normalize_volume(s.volume)}
    job.language = s.language
    job.duration_s = float(info.duration) if info else float(row["end"] - row["start"])
    job.width, job.height = (int(info.width), int(info.height)) if info else (s.width, s.height)
    job.segments = part_lines(s, float(row["start"]), float(row["end"]))
    if job.sub_lang not in ("none", "orig") and job.segments:
        # cut again with subtitles in another language on: the new lines are translated too
        try:
            lines, _ = dub.subtitle_lines(job, job.sub_lang)
            for seg, line in zip(job.segments, lines):
                seg.text = line
        except dub.DubError:
            job.sub_lang = "orig"
    if prev is not None:  # same look, new moments to pick
        job.highlights = {**dub.normalize_highlights(prev.highlights), "points": [], "picked": ""}
    job.voice_key, job.outputs = "", []
    job.status, job.phase, job.progress, job.error, job.stop = "done", "Đã cắt — chưa chỉnh", 100, None, False
    job.work = dub._jobs_root() / job.id
    job.work.mkdir(parents=True, exist_ok=True)
    job.src_path = path
    job.started_at = time.time()
    if job.board_id:
        with get_session() as db:
            if db.get(Board, job.board_id) is None:
                job.board_id = None
    job.board_id = dub._save_board(job)
    _forget_download(job.board_id)
    dub.JOBS[job.id] = job
    dub.persist(job)
    return job


def _forget_download(board_id: Optional[int]) -> None:
    """A part cut again is a new video: the clip's "đã tải về" mark no longer holds."""
    if not board_id:
        return
    with get_session() as db:
        b = db.get(Board, board_id)
        qt = dict(((b.data or {}).get("quicktool") or {})) if b is not None else {}
        if b is None or "downloaded_at" not in qt:
            return
        qt.pop("downloaded_at", None)
        b.data = {**(b.data or {}), "quicktool": qt}
        db.add(b)
        db.commit()


# ── stop / again / delete ──────────────────────────────────────────────────

def stop(s: Session) -> Session:
    if s.status == "queued":
        s.status, s.error = "error", "Đã dừng theo yêu cầu"
        persist(s)
    elif s.status in ("running", "cutting"):
        s.stop = True
    return s


def again(s: Session) -> Session:
    """"↻ Làm lại" after an error: from where it stopped (a video already heard is not heard again)."""
    if s.status in BUSY:
        raise CutError("Video này đang chạy")
    s.status, s.phase, s.progress, s.error, s.stop = "queued", "Đang chờ", 0, None, False
    s.started_at = time.time()
    persist(s)
    _pump()
    return s


def delete(ids: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    """Sessions leave the list (their work folder goes); the parts — clips and their projects — stay."""
    deleted, skipped = [], []
    for sid in ids:
        s = find(sid)
        if s is None:
            continue
        if s.status in BUSY:
            skipped.append({"id": sid, "reason": "đang chạy — dừng trước rồi xoá"})
            continue
        s.hear_stop = True
        SESSIONS.pop(sid, None)
        work = s.work
        if work is not None and work.parent == _root() and work.is_dir():
            shutil.rmtree(work, ignore_errors=True)
        deleted.append(sid)
    return deleted, skipped


def running_items() -> list[dict[str, Any]]:
    out = []
    for s in sessions():
        if s.status not in BUSY:
            if s.hear == "run":
                out.append({"key": f"cuthear:{s.id}", "kind": "cut", "title": f"Nghe lời “{s.title or s.url or 'video'}”"[:90],
                            "detail": "AI đang nghe lời trong video — vẫn chọn đoạn và cắt được", "progress": s.hear_progress,
                            "started_at": s.started_at, "link": f"/tools/cut?session={s.id}"})
            continue
        out.append({"key": f"cut:{s.id}", "kind": "cut", "title": f"Cắt “{s.title or s.url or 'video'}”"[:90],
                    "detail": s.phase or "Đang chờ", "progress": s.progress if s.status != "queued" else None,
                    "started_at": s.started_at, "link": f"/tools/cut?session={s.id}"})
    return out


def outcome(session_id: str) -> dict[str, Any]:
    s = find(session_id)
    if s is None:
        return {"ok": True, "message": ""}
    if s.status == "error":
        return {"ok": False, "message": s.error or "Cắt video lỗi"}
    if s.status == "review":
        return {"ok": True, "message": f"AI chọn {len(s.rows)} đoạn — xem lại rồi bấm Cắt" if s.rows else
                "Video đã tải xong — chọn các đoạn rồi bấm Cắt"}
    return {"ok": True, "message": f"Đã cắt {len(s.parts)} video — bấm để xem"}


def hear_outcome(session_id: str) -> dict[str, Any]:
    s = find(session_id)
    if s is None or s.hear == "skip":
        return {"ok": True, "message": ""}
    if s.hear == "error":
        return {"ok": False, "message": s.hear_error or "Nghe lời lỗi"}
    return {"ok": True, "message": f"Đã nghe xong lời trong video ({len(s.segments)} câu) — AI chọn đoạn được rồi"}


def boards_of(run_id: str) -> list[int]:
    return [int(p["board_id"]) for s in sessions() if s.run_id == run_id for p in s.parts if p.get("board_id")]


def clip_media(board_ids: list[int]) -> list[dict[str, Any]]:
    """The final video of clips ("🎬 Từ Clip của tôi" of the dubbing page)."""
    from flowboard.routes.exports import _final_media

    out = []
    with get_session() as db:
        boards = {b.id: b for b in db.exec(select(Board).where(Board.id.in_(board_ids))).all()} if board_ids else {}
    for bid in board_ids:
        b = boards.get(bid)
        media_id = _final_media(bid) if b is not None else None
        if b is not None and media_id:
            out.append({"board_id": bid, "name": b.name, "media_id": media_id})
    return out
