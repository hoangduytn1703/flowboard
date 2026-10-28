"""✂️ Edit auto CapCut — a video made in Flowboard (or the user's own) becomes
a CapCut desktop project, ready to polish by hand (``routes/capcut``, page
``/tools/capcut``). The file side is ``services/capcut_draft``.

Sources:
- ``dub``: a dubbed video (``services/dub``) — the picture with its frame /
  blur band / sticker but no subtitles, the Vietnamese voice and the music on
  their own audio tracks, every translated line as an editable subtitle.
- ``clip``: a finished clip's final mp4 — Whisper (pyvideotrans' venv, via
  ``dub_runner``) hears the voice for the timings.
- ``upload``: the user's own video (a file, or a link fetched by ``fetch_link``) — Whisper; long pauses can be cut out.
- ``dub_new``: a new video dubbed first, exactly like "🎙 Lồng tiếng video" (``dub.start_job``), then
  handed over as ``dub`` — the editing happens in CapCut instead of the dub editor.

Then subtitles in the user's own CapCut subtitle style (TikTok-style ≤ 4 words
a line, or whole lines), and the AI (``run_llm``) picks the key moments —
about one every 12 s, ≥ 5 s apart — each one a key word in the emphasis style,
a quick zoom-in and a short sound effect from the user's own CapCut.

Jobs live in RAM (one at a time); finished projects are listed in AppSetting
``capcut_projects`` so a video exported from CapCut can be brought back onto
its clip (:func:`return_video`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from sqlmodel import select

from flowboard import config
from flowboard.db import get_session
from flowboard.db.models import AppSetting, Asset, Board, Node
from flowboard.services import capcut_draft as cc
from flowboard.services import media as media_service
from flowboard.services.key_moments import (  # noqa: F401 — re-exported for the tests and older callers
    EMPHASIS_S, LLM_TIMEOUT_S, MAX_POINTS, MIN_POINT_GAP_S, SECONDS_PER_POINT, SFX_VOLUME, ZOOM_LEVELS, Line,
    fallback_points, pick_points, place_points, point_budget, split_words as _split_words, timed_words as _timed_words,
)
from flowboard.services.key_moments import parse_points as _parse_points  # noqa: F401
from flowboard.services.llm.base import LLMError
from flowboard.services.video_export import probe_clip
from flowboard.short_id import generate_unique_short_id

logger = logging.getLogger(__name__)

PROJECTS_KEY = "capcut_projects"
MAX_PROJECTS = 100
TIKTOK_WORDS = 4          # "Phụ đề kiểu TikTok": ≤ 4 words a line (the JunOps style)
LINE_WORDS = 9            # "Cả câu": a long line still splits so it fits the frame
SILENCE_GAP_S = 0.45      # pauses longer than this are cut (with SILENCE_PAD_S kept on each side)
SILENCE_PAD_S = 0.12
MUSIC_VOLUME = 0.6        # dub.BGM_VOLUME — the dubbed mix used the same level
SUB_BOX_HALF = 0.025      # a dub subtitle's anchor is its box bottom; CapCut places a text by its centre


class CapcutAutoError(RuntimeError):
    pass


# ── the learned styles (per machine: the sounds are files in this CapCut's cache) ──

def styles_path() -> Path:
    return Path(config.STORAGE_DIR) / "capcut" / "styles.json"


def load_styles() -> Optional[dict]:
    p = styles_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a broken file means "learn again"
        return None


def save_styles(kho: dict) -> None:
    p = styles_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(kho, ensure_ascii=False), encoding="utf-8")


def public_styles(kho: Optional[dict]) -> Optional[dict]:
    if not kho:
        return None
    return {"learned_at": kho.get("learned_at"), "scanned": kho.get("scanned", 0), "base": kho.get("base"),
            "has_video": bool(kho.get("video_tpl")), "aliases": kho.get("aliases", {}),
            "texts": [{"id": i, "label": e.get("label"), "examples": e.get("examples", []), "uses": e.get("uses", 0),
                       "role": e.get("role"), "size": e.get("size"), "color": e.get("color"), "font": e.get("font")}
                      for i, e in kho.get("texts", {}).items()],
            "sounds": [{"id": i, "label": e.get("label"), "duration": e.get("duration"), "uses": e.get("uses", 0)}
                       for i, e in kho.get("sounds", {}).items()]}


def learn() -> dict:
    root = cc.drafts_root()
    if root is None:
        raise CapcutAutoError("Không thấy thư mục dự án của CapCut trên máy này — cài CapCut bản máy tính, mở một lần rồi thử lại.")
    if cc.capcut_running():
        raise CapcutAutoError("Đóng hẳn CapCut trước khi học (CapCut đang mở có thể chưa lưu chữ / âm thanh bạn vừa thêm).")
    kho = cc.learn(root)
    old = load_styles() or {}
    # Keep the styles picked before — found again by what they look like (font · size · colour), not by
    # their number: a new style in a newer project shifts t1, t2… (28/10 the user's yellow-box subtitles
    # came in as t1 and every number moved).
    by_label = {e.get("label"): i for i, e in kho["texts"].items()}
    for role, sid in (old.get("aliases") or {}).items():
        if sid == "":  # "— Không dùng —" stays off
            kho["aliases"][role] = ""
            continue
        label = (old.get("texts", {}).get(sid) or {}).get("label")
        if label in by_label:
            kho["aliases"][role] = by_label[label]
    save_styles(kho)
    return kho


def choose_styles(choice: dict[str, Optional[str]]) -> dict:
    kho = load_styles()
    if not kho:
        raise CapcutAutoError("Chưa học kiểu chữ — bấm \"Học từ CapCut\" trước.")
    for role in ("subtitle", "emphasis", "title"):
        sid = choice.get(role)
        if sid is None:
            continue
        if sid and sid not in kho["texts"]:
            raise CapcutAutoError(f"Không có kiểu chữ {sid}")
        kho["aliases"][role] = sid  # "" = "— Không dùng —"
    save_styles(kho)
    return kho


# ── what this machine can do ───────────────────────────────────────────────

_PROVIDER_LABEL = {"claude": "Claude (gói của bạn, qua Claude Code)", "gemini": "Gemini (key trong Cài đặt)",
                   "openai": "OpenAI"}


async def ai_status() -> dict[str, Any]:
    from flowboard.services.llm import registry, secrets

    entry = secrets.read_feature_config().get("auto_prompt")
    if not entry:
        return {"ok": False, "reason": "Chưa chọn AI trong Cài đặt."}
    name = entry.get("provider") or ""
    provider = registry.get_provider(name)
    label = _PROVIDER_LABEL.get(name, name)
    if provider is None:
        return {"ok": False, "provider": label, "reason": f"Không biết AI {name!r}."}
    try:
        ok = await provider.is_available()
    except Exception:  # noqa: BLE001
        ok = False
    return {"ok": bool(ok), "provider": label,
            **({} if ok else {"reason": f"{label} chưa dùng được trên máy này (chưa cài / chưa có key)."})}


async def status() -> dict[str, Any]:
    from flowboard.services import dub

    root = cc.drafts_root()
    kho = load_styles()
    d = dub.status()
    out: dict[str, Any] = {
        "windows": sys.platform == "win32",
        "capcut_root": str(root) if root else None,
        "capcut_installed": root is not None,
        "capcut_running": cc.capcut_running(),
        "capcut_projects": len(cc.project_dirs(root)) if root else 0,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "whisper": bool(d.get("whisper")),
        "whisper_reason": None if d.get("whisper") else d.get("reason"),
        "dub": bool(d.get("available")),
        "dub_reason": None if d.get("available") else d.get("reason"),
        "dub_separate": bool(d.get("separate")),
        "styles": public_styles(kho),
        "ai": await ai_status(),
    }
    out["ready"] = bool(out["windows"] and out["capcut_installed"] and out["ffmpeg"] and kho and kho.get("texts")
                        and kho.get("video_tpl"))
    return out


# ── what can go in ─────────────────────────────────────────────────────────

def _final_media(board_id: int) -> Optional[str]:
    from flowboard.routes.exports import _final_media as final

    return final(board_id)


def _iso(ts: Optional[float]) -> Optional[str]:
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat() if ts else None
    except (TypeError, ValueError, OSError):
        return None


def sources(limit: int = 60) -> dict[str, list[dict[str, Any]]]:
    from flowboard.services import dub

    dub.load_jobs()
    dubs = []
    for j in sorted(dub.JOBS.values(), key=lambda j: j.started_at, reverse=True):
        if j.status not in ("done", "review", "error") or not j.segments:
            continue
        voice = (j.work / "voice.wav") if j.work else None
        dubs.append({"id": j.id, "title": j.name or j.title or "Video lồng tiếng", "duration": j.duration_s,
                     "width": j.width, "height": j.height, "lines": len([s for s in j.segments if s.text.strip()]),
                     "board_id": j.board_id, "started_at": _iso(j.started_at),
                     "has_voice": bool(voice and voice.is_file()), "status": j.status})
        if len(dubs) >= limit:
            break
    clips = []
    with get_session() as s:
        boards = s.exec(select(Board).order_by(Board.id.desc()).limit(300)).all()
        finals = s.exec(select(Node.board_id, Node.data).where(Node.type.in_(["export", "merge"]))).all()
    have = {}
    for bid, data in finals:
        if isinstance(data, dict) and data.get("mediaId"):
            have[bid] = data["mediaId"]
    for b in boards:
        qt = (b.data or {}).get("quicktool") or {}
        if b.id not in have or qt.get("template_id") == "dub":
            continue
        clips.append({"id": b.id, "title": b.name, "media_id": have[b.id],
                      "capcut": qt.get("capcut"), "updated_at": getattr(b, "updated_at", None) and str(b.updated_at)})
        if len(clips) >= limit:
            break
    return {"dubs": dubs, "clips": clips}


def fetch_link(url: str) -> dict[str, Any]:
    """A video by link (TikTok / Douyin / YouTube / Facebook…) → a local Asset, like an upload."""
    from flowboard.services.video_fetch import FetchError, extract_url, fetch_video

    if not extract_url(url or ""):
        raise CapcutAutoError("Không thấy link video trong ô")
    media_id = uuid.uuid4().hex
    media_service.MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        path, title = fetch_video(url, media_id, media_service.MEDIA_CACHE_DIR, max_duration_s=30 * 60)
    except FetchError as exc:
        raise CapcutAutoError(f"Không tải được video: {exc}") from exc
    info = probe_clip(path)
    if info is None:
        raise CapcutAutoError("Không đọc được video vừa tải")
    mime = {".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}.get(path.suffix.lower(), "video/mp4")
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(path), mime=mime))
        s.commit()
    return {"media_id": media_id, "name": (title or "Video từ link")[:80], "duration": round(info.duration, 2),
            "width": info.width, "height": info.height, "url": f"/media/{media_id}"}


# ── timed text ─────────────────────────────────────────────────────────────

@dataclass
class Cue:
    start: float
    end: float
    text: str
    line: int


_BREAK_AFTER = re.compile(r"[,.!?;:…]$")


def _clean_chunk(words: list[str], tiktok: bool) -> str:
    text = " ".join(words)
    return re.sub(r"[.,;:]+$", "", text) if tiktok else text


def chunk_lines(lines: list[Line], mode: str) -> list[Cue]:
    """Subtitles: ``tiktok`` = ≤ 4 words, broken after punctuation; ``line`` =
    a whole line (split above 9 words). A chunk shows until the next one of
    its line starts, the last until the line ends."""
    if mode == "off":
        return []
    limit = TIKTOK_WORDS if mode == "tiktok" else LINE_WORDS
    cues: list[Cue] = []
    for li, line in enumerate(lines):
        tw = _timed_words(line)
        groups: list[list[tuple[float, float, str]]] = []
        cur: list[tuple[float, float, str]] = []
        for w in tw:
            cur.append(w)
            if len(cur) >= limit or (mode == "tiktok" and _BREAK_AFTER.search(w[2]) and len(cur) >= 1):
                groups.append(cur)
                cur = []
        if cur:
            if groups and len(cur) == 1 and mode == "line":
                groups[-1].extend(cur)  # never a lone word on its own line
            else:
                groups.append(cur)
        for gi, g in enumerate(groups):
            a = g[0][0]
            b = groups[gi + 1][0][0] if gi + 1 < len(groups) else max(line.end, g[-1][1])
            text = _clean_chunk([w[2] for w in g], mode == "tiktok")
            if text and b - a > 0.05:
                cues.append(Cue(round(a, 3), round(b, 3), text, li))
    cues.sort(key=lambda c: c.start)
    for cur, nxt in zip(cues, cues[1:]):  # one subtitle at a time: a line running long gives way to the next
        if cur.end > nxt.start:
            cur.end = max(round(cur.start + 0.1, 3), nxt.start)
            nxt.start = max(nxt.start, cur.end)
            nxt.end = max(nxt.end, round(nxt.start + 0.1, 3))
    return cues


# ── cutting the pauses out (the user's own videos) ─────────────────────────

def keep_ranges(lines: list[Line], duration_s: float, gap: float = SILENCE_GAP_S, pad: float = SILENCE_PAD_S) -> list[tuple[float, float]]:
    """The spoken parts (word timings when known), joined when the pause between is short."""
    spans: list[tuple[float, float]] = []
    for line in lines:
        if line.words:
            spans += [(w[0], w[1]) for w in line.words]
        else:
            spans.append((line.start, line.end))
    spans = sorted((max(0.0, a - pad), min(duration_s, b + pad)) for a, b in spans if b > a)
    out: list[tuple[float, float]] = []
    for a, b in spans:
        if out and a - out[-1][1] <= gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return [(round(a, 3), round(b, 3)) for a, b in out if b - a >= 0.15]


def remap(t: float, keeps: list[tuple[float, float]]) -> Optional[float]:
    """A time in the source → the same moment on the cut timeline (None if it was cut out)."""
    pos = 0.0
    for a, b in keeps:
        if a - 1e-6 <= t <= b + 1e-6:
            return round(pos + min(max(t, a), b) - a, 3)
        pos += b - a
    return None


def remap_lines(lines: list[Line], keeps: list[tuple[float, float]]) -> list[Line]:
    out = []
    for line in lines:
        words = []
        for a, b, w in line.words:
            ra, rb = remap(a, keeps), remap(b, keeps)
            if ra is not None:
                words.append((ra, rb if rb is not None and rb > ra else ra + 0.2, w))
        s = remap(line.start, keeps)
        e = remap(line.end, keeps)
        if words:
            s, e = words[0][0], max(words[-1][1], e or 0)
        if s is None:
            continue
        out.append(Line(s, e if e is not None and e > s else s + 0.5, line.text, words, line.anchor))
    return out


# ── jobs ───────────────────────────────────────────────────────────────────

@dataclass
class Job:
    id: str
    source: dict[str, Any]
    options: dict[str, Any]
    status: str = "queued"  # queued | running | done | error
    phase: str = "Chờ đến lượt"
    progress: int = 0
    error: Optional[str] = None
    result: Optional[dict] = None
    warnings: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def public(self) -> dict[str, Any]:
        from datetime import datetime, timezone

        return {"id": self.id, "source": self.source, "options": self.options, "status": self.status,
                "phase": self.phase, "progress": self.progress, "error": self.error, "result": self.result,
                "warnings": self.warnings,
                "started_at": datetime.fromtimestamp(self.started_at, tz=timezone.utc).isoformat(),
                "finished_at": (datetime.fromtimestamp(self.finished_at, tz=timezone.utc).isoformat()
                                if self.finished_at else None)}


JOBS: dict[str, Job] = {}
_RUN_LOCK = threading.Lock()


def _set(job: Job, phase: str, progress: int) -> None:
    job.phase, job.progress = phase, max(job.progress, min(99, int(progress)))


def start(source: dict[str, Any], options: dict[str, Any], dub_spec: Optional[dict[str, Any]] = None) -> Job:
    if source.get("kind") not in ("dub", "clip", "upload", "dub_new"):
        raise CapcutAutoError("Nguồn video không hợp lệ")
    source = dict(source)
    if source["kind"] == "dub_new":
        source["id"] = _start_dub(source, dub_spec or {})
    job = Job(id=uuid.uuid4().hex[:12], source=source, options=dict(options))
    JOBS[job.id] = job
    for old in sorted(JOBS.values(), key=lambda j: j.started_at)[:-30]:  # RAM: the last 30 are plenty
        if old.status in ("done", "error"):
            JOBS.pop(old.id, None)
    threading.Thread(target=_run, args=(job,), name=f"capcut-{job.id}", daemon=True).start()
    return job


def _start_dub(source: dict[str, Any], spec: dict[str, Any]) -> str:
    """The dub of "🎙 Lồng tiếng video" (Whisper → translation → Vietnamese voice → its clip), started now."""
    from flowboard.services import dub, tts

    try:
        j = dub.start_job(url=spec.get("url") or None, source_media_id=spec.get("source_media_id") or source.get("media_id") or None,
                          voice=spec.get("voice") or tts.DEFAULT_VOICE, keep_bgm=bool(spec.get("keep_bgm", True)),
                          style="box_yellow", channel_id=spec.get("channel_id"), name=(source.get("title") or "")[:80],
                          auto_render=True)
    except dub.DubError as exc:
        raise CapcutAutoError(f"Không lồng tiếng được: {exc}") from exc
    return j.id


DUB_SHARE = 70  # of the progress bar while the dub runs


def _wait_dub(job: Job) -> None:
    """Follow the dub on the CapCut job's progress, then carry on as a dubbed source."""
    from flowboard.services import dub

    did = str(job.source.get("id") or "")
    while True:
        j = dub.JOBS.get(did)
        if j is None:
            raise CapcutAutoError("Việc lồng tiếng đã biến mất (agent khởi động lại?)")
        if j.status == "done":
            break
        if j.status == "error":
            raise CapcutAutoError(f"Lồng tiếng lỗi: {j.error}")
        if j.status == "review":  # auto_render is on, so only a restart lands here
            raise CapcutAutoError("Bản dịch đang chờ xem lại ở trang Lồng tiếng — render ở đó rồi tạo dự án CapCut từ video đó.")
        phase = "Chờ đến lượt lồng tiếng" if j.status == "queued" else f"Lồng tiếng: {j.phase}"
        job.phase, job.progress = phase, max(job.progress, int((j.progress or 0) * DUB_SHARE / 100))
        time.sleep(1.0)
    job.source = {**job.source, "kind": "dub", "dubbed": True}
    job.progress = max(job.progress, DUB_SHARE)


def active() -> list[Job]:
    return [j for j in JOBS.values() if j.status in ("queued", "running")]


def _run(job: Job) -> None:
    with _RUN_LOCK:
        job.status = "running"
        try:
            _build(job)
            job.status, job.phase, job.progress = "done", "Xong", 100
        except (CapcutAutoError, cc.CapcutError) as exc:
            job.status, job.error = "error", str(exc)
        except Exception as exc:  # noqa: BLE001 — a job never dies silently
            from flowboard.services.dub import DubError

            job.status = "error"
            job.error = str(exc) if isinstance(exc, DubError) else f"{type(exc).__name__}: {exc}"
            if not isinstance(exc, DubError):
                logger.exception("capcut: job %s crashed", job.id)
        finally:
            job.finished_at = time.time()


@dataclass
class Material:
    """Everything one source brings: the picture, extra audio, timed lines."""
    title: str
    video: Path
    width: int
    height: int
    duration: float
    video_has_audio: bool
    video_volume: float
    audios: list[tuple[Path, float, str, float]] = field(default_factory=list)  # (file, seconds, lane, volume)
    lines: list[Line] = field(default_factory=list)
    board_id: Optional[int] = None


def _cc_xy(x: float, y_bottom: float) -> tuple[float, float]:
    """A dub layout anchor (bottom-centre of the box, fractions from the top-left) → CapCut's centre (-1…1, y up)."""
    return round(2 * x - 1, 4), round(1 - 2 * (y_bottom - SUB_BOX_HALF), 4)


def _from_dub(job: Job, work: Path) -> Material:
    from flowboard.services import dub

    j = dub.find_job(str(job.source.get("id") or ""))
    if j is None:
        raise CapcutAutoError("Không thấy video lồng tiếng này (thư mục làm việc đã bị xoá?)")
    voice = (j.work / "voice.wav") if j.work else None
    if voice is None or not voice.is_file():
        raise CapcutAutoError("Video lồng tiếng này chưa có giọng đọc trên máy — mở nó ở trang Lồng tiếng, bấm "
                              "\"Xuất lại video\" rồi thử lại.")
    if dub.has_picture_layers(j):
        _set(job, "Đang dựng video nền (khung, vùng mờ, nhân vật — chưa có phụ đề)", 10)
    video = dub.render_clean_video(j, work / "video.mp4")
    info = probe_clip(video)
    if info is None:
        raise CapcutAutoError("Không đọc được video nguồn")
    mat = Material(title=j.name or j.title or "Video lồng tiếng", video=video, width=info.width, height=info.height,
                   duration=info.duration, video_has_audio=bool(getattr(info, "has_audio", True)), video_volume=0.0,
                   board_id=j.board_id)
    vdur = _audio_seconds(voice) or info.duration
    mat.audios.append((voice, vdur, "voice", 1.0))
    bgm = j.work / "bgm.wav" if j.work else None
    if j.keep_bgm and bgm is not None and bgm.is_file():
        mat.audios.append((bgm, _audio_seconds(bgm) or info.duration, "music", MUSIC_VOLUME))
    lines = []
    for s in j.segments:
        if s.text.strip():
            own = dub.effective_layout(j.layout, s.look)  # where the editor placed this line
            lines.append(Line(s.start, s.end, s.text.strip(), [], _cc_xy(own["x"], own["y"])))
    mat.lines = lines
    return mat


def _audio_seconds(path: Path) -> Optional[float]:
    from flowboard.services import tts

    try:
        return tts._probe_duration(path)
    except Exception:  # noqa: BLE001
        return None


def _hear(path: Path, work: Path, job: Job, p0: int, p1: int) -> list[Line]:
    """Whisper (pyvideotrans' venv) with word timings."""
    from flowboard.services import dub

    if not dub.status().get("whisper"):
        job.warnings.append("Máy này chưa có Whisper (pyvideotrans) để nghe lời — dự án chỉ có video, chưa có phụ đề / chữ nhấn mạnh.")
        return []
    wav = work / "speech16.wav"
    dub._extract_wav(dub._ffmpeg(), path, wav, 16000, True)
    out = work / "heard.json"
    _set(job, "Đang nghe lời trong video (Whisper)", p0)
    dub._runner("transcribe", str(wav), str(out), "auto", "words",
                progress=lambda p: _set(job, "Đang nghe lời trong video (Whisper)", p0 + (p1 - p0) * p / 100))
    data = json.loads(out.read_text(encoding="utf-8"))
    lines = []
    for seg in data.get("segments", []):
        words = [(float(w["start"]), float(w["end"]), str(w["word"])) for w in seg.get("words") or [] if str(w.get("word", "")).strip()]
        text = " ".join(w[2] for w in words) if words else str(seg.get("text") or "").strip()
        if text:
            lines.append(Line(float(seg["start"]), float(seg["end"]), text, words))
    return lines


def _from_file(job: Job, work: Path, path: Path, title: str, board_id: Optional[int]) -> Material:
    info = probe_clip(path)
    if info is None:
        raise CapcutAutoError("Không đọc được video")
    mat = Material(title=title, video=path, width=info.width, height=info.height, duration=info.duration,
                   video_has_audio=True, video_volume=1.0, board_id=board_id)
    wants_text = job.options.get("subtitles", "tiktok") != "off" or job.options.get("highlights", True) \
        or job.options.get("cut_silence")
    if wants_text:
        mat.lines = _hear(path, work, job, 8, 45)
    return mat


def _from_clip(job: Job, work: Path) -> Material:
    bid = int(job.source.get("id") or 0)
    with get_session() as s:
        board = s.get(Board, bid)
    if board is None:
        raise CapcutAutoError("Không thấy clip này")
    media = _final_media(bid)
    path = media_service.cached_path(media) if media else None
    if not path or not Path(path).is_file():
        raise CapcutAutoError("Clip này chưa ghép xong video (Bước 5) hoặc file không còn trên máy.")
    return _from_file(job, work, Path(path), board.name, bid)


def _from_upload(job: Job, work: Path) -> Material:
    mid = str(job.source.get("id") or "")
    path = media_service.cached_path(mid)
    if not path or not Path(path).is_file():
        raise CapcutAutoError("Không thấy video đã tải lên — tải lại.")
    return _from_file(job, work, Path(path), str(job.source.get("title") or "Video của tôi"), None)


def _cover(video: Path, at: float, dst: Path) -> Optional[Path]:
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    try:
        subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", f"{max(0.0, at):.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", "scale='min(720,iw)':-2", "-q:v", "4", str(dst)], capture_output=True, timeout=60)
    except Exception:  # noqa: BLE001 — CapCut draws its own cover when opened
        return None
    return dst if dst.is_file() else None


def _build(job: Job) -> None:
    kho = load_styles()
    if not kho or not kho.get("texts"):
        raise CapcutAutoError("Chưa học kiểu chữ & âm thanh từ CapCut — bấm \"Học từ CapCut\" ở bước 1.")
    root = cc.drafts_root()
    if root is None:
        raise CapcutAutoError("Không thấy CapCut trên máy này.")
    if cc.capcut_running():
        raise CapcutAutoError("CapCut đang mở — đóng hẳn CapCut rồi bấm tạo lại.")
    work = media_service.MEDIA_CACHE_DIR / "capcut" / job.id
    work.mkdir(parents=True, exist_ok=True)
    if job.source["kind"] == "dub_new":
        _wait_dub(job)
        if cc.capcut_running():
            raise CapcutAutoError("Đã lồng tiếng xong nhưng CapCut đang mở — đóng hẳn CapCut rồi tạo dự án từ video vừa lồng "
                                  "(tab \"Video lồng tiếng\").")
    kind = job.source["kind"]
    _set(job, "Đang chuẩn bị video", 3)
    mat = _from_dub(job, work) if kind == "dub" else _from_clip(job, work) if kind == "clip" else _from_upload(job, work)
    opts = job.options
    lines, duration = mat.lines, mat.duration
    keeps: Optional[list[tuple[float, float]]] = None
    if opts.get("cut_silence") and kind != "dub" and lines:
        keeps = keep_ranges(lines, duration)
        cut = duration - sum(b - a for a, b in keeps)
        if keeps and cut > 0.3:
            lines = remap_lines(lines, keeps)
            duration = sum(b - a for a, b in keeps)
            job.warnings.append(f"Đã bỏ {cut:.1f} s khoảng lặng ({len(keeps)} đoạn giữ lại).")
        else:
            keeps = None
    points: list[dict[str, Any]] = []
    wants_points = opts.get("highlights", True) and (
        bool(kho.get("aliases", {}).get("emphasis")) or opts.get("zoom", True) or opts.get("sfx", True))
    if wants_points and lines:
        _set(job, "AI đang chọn chữ quan trọng", 55)
        try:
            points = asyncio.run(pick_points(lines, duration))
        except (LLMError, CapcutAutoError, ValueError) as exc:
            points = fallback_points(lines, duration)
            job.warnings.append(f"AI không chọn được chữ quan trọng ({exc}) — đã chọn theo số / câu cảm thán ({len(points)} chỗ).")
    _set(job, "Đang ghi dự án CapCut", 80)
    base = cc.base_project(root, kho)
    b = cc.DraftBuilder(kho, cc.base_content(base), mat.width, mat.height)
    if keeps:
        pos = 0.0
        for a, c in keeps:
            b.add_video(mat.video, duration_s=mat.duration, width=mat.width, height=mat.height, has_audio=mat.video_has_audio,
                        start=pos, src_start=a, dur=c - a, volume=mat.video_volume)
            pos += c - a
    else:
        b.add_video(mat.video, duration_s=mat.duration, width=mat.width, height=mat.height, has_audio=mat.video_has_audio,
                    start=0.0, volume=mat.video_volume)
    for path, secs, lane, vol in mat.audios:
        b.add_audio(path, duration_s=min(secs, mat.duration), lane=lane, volume=vol)
    same_place = opts.get("sub_position", "video") == "video"  # a dub's subtitles where the editor put them
    sub_y = None
    sub_mode = opts.get("subtitles", "tiktok") if kho.get("aliases", {}).get("subtitle") else "off"  # "— Không dùng —"
    srt_cues = chunk_lines(lines, sub_mode if sub_mode != "off" else (opts.get("subtitles") if opts.get("subtitles") != "off" else "line"))
    srt_path = work / "phu_de.srt"
    if srt_cues:  # always kept: CapCut's Captions → Import turns it into real captions (move one, all follow)
        srt_path.write_text(cc.to_srt([(c.start, c.end, c.text) for c in srt_cues]), encoding="utf-8")
    for cue in ([] if opts.get("srt_only") else chunk_lines(lines, sub_mode)):
        x, y = lines[cue.line].anchor if same_place and lines[cue.line].anchor else (None, None)
        b.add_text("subtitle", cue.start, max(0.05, cue.end - cue.start), cue.text, x=x, y=y, lane="subtitle")
        sub_y = y if y is not None else sub_y
    use_emphasis = bool(kho.get("aliases", {}).get("emphasis"))  # "— Không dùng —": zoom + sound only
    emph_y = None
    if use_emphasis:
        emph_tpl = kho["texts"][b.text_style("emphasis")]["tpl"]["segment"].get("clip") or {}
        emph_y = (emph_tpl.get("transform") or {}).get("y")
        if sub_y is not None and emph_y is not None and abs(emph_y - sub_y) < 0.15:
            emph_y = min(0.9, sub_y + 0.3)  # keep the key word clear of the subtitles
        else:
            emph_y = None
    for i, p in enumerate(points):
        end = min(duration, p["at"] + EMPHASIS_S)
        if use_emphasis:
            b.add_text("emphasis", p["at"], max(0.4, end - p["at"]), p["words"].upper(), y=emph_y, lane="emphasis")
        if opts.get("zoom", True):
            b.add_zoom(p["at"], level=ZOOM_LEVELS[i % len(ZOOM_LEVELS)])
        if opts.get("sfx", True):
            b.add_sfx(p["at"], volume=SFX_VOLUME)
    cover = _cover(mat.video, min(1.0, mat.duration / 3), work / "cover.jpg")
    name = (opts.get("name") or mat.title or "Flowboard").strip()
    res = cc.create_project(root, name, b, base, cover)
    res.update(source={**job.source, "title": mat.title}, board_id=mat.board_id, points=points[:MAX_POINTS],
               subtitles=b.counts["text"] - (len(points) if use_emphasis else 0),
               srt=str(srt_path) if srt_path.is_file() else None, srt_lines=len(srt_cues))
    job.result = res
    _record(res)


# ── projects made here, and their way back ─────────────────────────────────

def _read_projects() -> list[dict]:
    with get_session() as s:
        row = s.get(AppSetting, PROJECTS_KEY)
    if row is None:
        return []
    try:
        data = json.loads(row.value)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _write_projects(rows: list[dict]) -> None:
    from datetime import datetime, timezone

    with get_session() as s:
        row = s.get(AppSetting, PROJECTS_KEY)
        value = json.dumps(rows[:MAX_PROJECTS], ensure_ascii=False)
        if row is None:
            s.add(AppSetting(key=PROJECTS_KEY, value=value))
        else:
            row.value = value
            row.updated_at = datetime.now(timezone.utc)
            s.add(row)
        s.commit()


def _record(res: dict) -> None:
    from datetime import datetime, timezone

    rec = {"id": uuid.uuid4().hex[:12], "name": res["name"], "folder": res["folder"], "draft_id": res["draft_id"],
           "duration_s": res.get("duration_s"), "counts": res.get("counts"), "source": res.get("source"),
           "board_id": res.get("board_id"), "points": len(res.get("points") or []), "subtitles": res.get("subtitles"),
           "srt": res.get("srt"), "srt_lines": res.get("srt_lines"),
           "created_at": datetime.now(timezone.utc).isoformat(), "returned": None}
    res["project_id"] = rec["id"]
    _write_projects([rec] + _read_projects())


def projects() -> list[dict]:
    rows = _read_projects()
    for r in rows:
        r["exists"] = Path(r.get("folder") or "").is_dir()
    return rows


def project_srt(pid: str) -> tuple[str, str]:
    """``(file name, SubRip text)`` of a project: read from the CapCut project itself (so hand edits of the
    words come along), else the file kept when it was made (a project made "chỉ file .srt")."""
    rec = next((r for r in _read_projects() if r.get("id") == pid), None)
    if rec is None:
        raise CapcutAutoError("Không thấy dự án này trong danh sách")
    cues: list[tuple[float, float, str]] = []
    folder = Path(rec.get("folder") or "")
    if folder.is_dir() and (rec.get("subtitles") or 0) > 0:
        try:
            cues = cc.read_subtitles(folder)
        except Exception:  # noqa: BLE001 — a half-saved project: fall back to the kept file
            cues = []
    if cues:
        text = cc.to_srt(cues)
    elif rec.get("srt") and Path(rec["srt"]).is_file():
        text = Path(rec["srt"]).read_text(encoding="utf-8")
    else:
        raise CapcutAutoError("Dự án này không có phụ đề")
    return f"{cc.safe_name(rec.get('name') or 'phu-de')}.srt", text


def forget_project(pid: str, remove_folder: bool = False) -> bool:
    rows = _read_projects()
    rec = next((r for r in rows if r.get("id") == pid), None)
    if rec is None:
        return False
    if remove_folder:
        root = cc.drafts_root()
        if root is not None and Path(rec.get("folder") or "").is_dir():
            cc.remove_project(root, rec["folder"])
    _write_projects([r for r in rows if r.get("id") != pid])
    return True


def _board_for(rec: dict) -> int:
    """The clip the CapCut version goes back to — an own video gets a clip of its own the first time."""
    if rec.get("board_id"):
        with get_session() as s:
            if s.get(Board, int(rec["board_id"])) is not None:
                return int(rec["board_id"])
    title = ((rec.get("source") or {}).get("title") or rec.get("name") or "Video từ CapCut")[:80]
    with get_session() as s:
        board = Board(name=title, data={"quicktool": {"template_id": "capcut", "step": 5}})
        s.add(board)
        s.commit()
        s.refresh(board)
        s.add(Node(board_id=board.id, short_id=generate_unique_short_id(s, board.id), type="video", x=0, y=0,
                   data={"title": "Video từ CapCut"}, status="done"))
        s.add(Node(board_id=board.id, short_id=generate_unique_short_id(s, board.id), type="export", x=320, y=0,
                   data={"title": "Xuất"}, status="done"))
        s.commit()
        return int(board.id)


def return_video(pid: str, path: Path, mime: str = "video/mp4") -> dict[str, Any]:
    """The video exported from CapCut becomes the clip's final video (the one
    "Tải về", the schedule and Facebook posts use); the old one is kept as
    ``capcutPrev`` on the export node."""
    from datetime import datetime, timezone

    rows = _read_projects()
    rec = next((r for r in rows if r.get("id") == pid), None)
    if rec is None:
        raise CapcutAutoError("Không thấy dự án này trong danh sách")
    info = probe_clip(path)
    if info is None or info.duration <= 0:
        raise CapcutAutoError("File không phải video đọc được")
    bid = _board_for(rec)
    media_id = path.stem
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(path), mime=mime))
        board = s.get(Board, bid)
        nodes = s.exec(select(Node).where(Node.board_id == bid, Node.type.in_(["export", "merge"]))).all()
        for n in nodes:
            data = dict(n.data or {})
            if data.get("mediaId") and data.get("mediaId") != media_id and not data.get("capcutPrev"):
                data["capcutPrev"] = data["mediaId"]
            data["mediaId"] = media_id
            n.data = data
            n.status = "done"
            s.add(n)
        if board is not None:
            qt = dict((board.data or {}).get("quicktool") or {})
            qt["capcut"] = {"project": rec["name"], "media_id": media_id, "at": datetime.now(timezone.utc).isoformat()}
            qt.pop("downloaded_at", None)
            board.data = {**(board.data or {}), "quicktool": qt}
            s.add(board)
        s.commit()
    rec["board_id"] = bid
    rec["returned"] = {"media_id": media_id, "at": datetime.now(timezone.utc).isoformat(),
                       "duration_s": round(info.duration, 2)}
    _write_projects(rows)
    return {"board_id": bid, "media_id": media_id, "project": rec}
