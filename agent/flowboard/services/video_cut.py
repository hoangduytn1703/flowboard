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
HOWS = ("ai", "prompt", "even")
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
             "rows", "by", "note", "name", "title_lang", "parts", "look", "error", "started_at", "position")

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
    """``(min, max)`` seconds of one part: 5 s … 20 min, max at least min + 5 s."""
    try:
        lo = float(min_s)
    except (TypeError, ValueError):
        lo = DEFAULT_MIN_S
    try:
        hi = float(max_s)
    except (TypeError, ValueError):
        hi = DEFAULT_MAX_S
    lo = max(5.0, min(600.0, lo))
    hi = max(lo + 5.0, min(1200.0, hi))
    return round(lo, 1), round(hi, 1)


def normalize_how(how: Any) -> str:
    return how if how in HOWS else "ai"


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
            "default_min": DEFAULT_MIN_S, "default_max": DEFAULT_MAX_S}


# ── start / queue ──────────────────────────────────────────────────────────

def start(*, links: list[str], media: list[dict[str, Any]], how: str = "ai", prompt: str = "", min_s: Any = None,
          max_s: Any = None, max_parts: Any = 0, review: bool = False, channel_id: Optional[int] = None,
          look: Optional[dict] = None, title_lang: Any = "") -> tuple[str, list[Session]]:
    """One session per link / file, all in one run (their parts are one batch in the editor). ``look`` = a saved
    "★ Mẫu chỉnh sửa" (:func:`dub.look_preset`) every part is rendered in. Returns ``(run_id, sessions)``."""
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
    if how == "prompt" and not prompt:
        raise CutError("Gõ yêu cầu cắt (VD: “mỗi đoạn một mẹo”) hoặc chọn “AI tự chọn đoạn hay”")
    lo, hi = normalize_lengths(DEFAULT_MIN_S if min_s is None else min_s, DEFAULT_MAX_S if max_s is None else max_s)
    run_id = _uid()
    now = time.time()
    made: list[Session] = []
    for i, (kind, value) in enumerate(items):
        s = Session(id=_uid(), run_id=run_id, how=how, prompt=prompt, min_s=lo, max_s=hi,
                    max_parts=normalize_max_parts(max_parts), review=bool(review), channel_id=channel_id,
                    title_lang=normalize_title_lang(title_lang),
                    look=dub.normalize_look_preset(look) if look else None, started_at=now, position=i)
        if kind == "url":
            s.url = str(value)[:2000]
        else:
            s.source_media_id = str(value["media_id"])[:64]
            s.title = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", str(value.get("name") or "")).strip()[:80]
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
    """Download (link) → probe → hear it once (Whisper)."""
    from flowboard.services.video_fetch import FetchError, extract_url, fetch_video

    ffmpeg = dub._ffmpeg()
    assert s.work is not None
    s.work.mkdir(parents=True, exist_ok=True)
    if s.url and not s.source_media_id:
        _set(s, "Đang tải video về", 3)
        media_id = uuid.uuid4().hex
        try:
            path, title = fetch_video(s.url, media_id, media_service.MEDIA_CACHE_DIR, max_duration_s=MAX_DURATION_S)
        except FetchError as exc:
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
    if info.has_audio and dub.status().get("available"):
        _set(s, "Đang tách tiếng", 6)
        wav = s.work / "speech16.wav"
        dub._extract_wav(ffmpeg, src, wav, 16000, True)
        _set(s, "Đang nghe lời trong video (Whisper)", 8)
        out = s.work / "asr.json"
        hint = dub_names.asr_hint(s.title) if s.url else ""
        dub._runner("transcribe", str(wav), str(out), "auto", "-", hint,
                    progress=lambda p: _set(s, "Đang nghe lời trong video (Whisper)", 8 + p * 0.5), stop=lambda: s.stop)
        data = json.loads(out.read_text(encoding="utf-8"))
        s.language = str(data.get("language") or "")
        s.segments = [{"start": round(float(x["start"]), 3), "end": round(float(x["end"]), 3), "text": str(x.get("text") or "").strip()}
                      for x in data.get("segments") or [] if float(x["end"]) > float(x["start"])]
        s.heard = True
        wav.unlink(missing_ok=True)
    s.prepared = True
    persist(s)


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


def even_rows(s: Session) -> list[dict[str, Any]]:
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
    want = f"Each short video: {s.min_s:.0f}-{s.max_s:.0f} seconds" + (f"; at most {s.max_parts} videos" if s.max_parts else "")
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
        raise CutError("Video chưa tải / nghe xong — bấm ↻ Làm lại")
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


def cut(s: Session, rows: Any) -> Session:
    """Cut (or cut again) with these rows, in a thread. Part n reuses the project + clip of the old part n."""
    if s.status in BUSY:
        raise CutError("Video này đang chạy — chờ xong")
    if not s.prepared:
        raise CutError("Video chưa tải / nghe xong — bấm ↻ Làm lại")
    _source(s)
    rows = check_rows(s, rows)
    for p in s.parts:
        job = dub.JOBS.get(str(p.get("job_id") or ""))
        if job is not None and job.status in ("queued", "running", "rendering"):
            raise CutError(f"Video {p.get('index')} đang xuất — chờ xong rồi cắt lại")
    s.rows, s.by = rows, s.by or "manual"
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
        dub_split._cut(ffmpeg, src, row["start"], row["end"], dst, f"{TAG_PREFIX}{s.id}")
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
        parts.append({"index": i, "start": row["start"], "end": row["end"], "title": title, "job_id": job.id,
                      "board_id": job.board_id, "media_id": media_id, "at": time.time()})
        s.parts = parts + [p for k, p in sorted(old.items()) if k > i]
        persist(s)
    s.parts = parts  # parts past the new count keep their clips (the seller may have edited them), not listed here
    s.status, s.phase, s.progress, s.error = "done", f"Đã cắt {total} video", 100, None


def needs_render(job: dub.Job) -> bool:
    """A part just cut is the raw piece. It is rendered at once when its project has something to put on it: a
    look (the cut's preset, or what the seller set before cutting again — 9:16 frame, background, blur boxes,
    sticker), subtitles to burn, or key-moment emphasis."""
    return (dub.normalize_layout(job.layout) != dub.normalize_layout(None) or job.sub_lang != "none"
            or bool((job.highlights or {}).get("on")))


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
    job.url = None
    job.kind, job.mode = "cut", "sub"
    job.source_media_id = job.media_id = media_id
    job.cut = {"session_id": s.id, "run_id": s.run_id, "index": index, "total": total, "start": row["start"],
               "end": row["end"], "source_url": s.url, "source_title": s.title}
    job.batch_id = s.run_id
    job.name = job.title = title[:80]
    if prev is None:
        job.channel_id = s.channel_id
        if s.look:  # the cut's "★ Mẫu chỉnh sửa": the part starts (and is rendered) in that look
            dub.apply_look(job, s.look)
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
        return {"ok": True, "message": f"AI chọn {len(s.rows)} đoạn — xem lại rồi bấm Cắt"}
    return {"ok": True, "message": f"Đã cắt {len(s.parts)} video — bấm để xem"}


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
