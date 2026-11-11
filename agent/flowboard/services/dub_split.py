"""✂️ Cắt một video lồng tiếng thành nhiều video nhỏ (tab "✂️ Cắt" của trình chỉnh sửa).

VieDub cuts the *source* before dubbing (rows of name / start / end, "⏱" from the playhead, "Chia đều", re-encoded
so a cut is exact to the tenth of a second). Here the cut is of the finished video — the latest export, voice and
subtitles already in — so each part comes out ready to post. Rows are typed, set from the playhead, spread evenly
(:func:`suggest_even`, cut in the pause between two lines nearest the length asked for) or suggested by the AI
(:func:`suggest_ai`: each part one whole idea that stands on its own, with a title); the AI failing falls back to
the even split. Every part becomes a clip of its own (board ``template_id: "dub_part"``) — library, "Hôm nay",
schedule, Facebook — and re-cutting reuses the clips of the parts with the same number.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Asset, Board, Node
from flowboard.services import dub
from flowboard.services import media as media_service
from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError
from flowboard.services.video_export import _encode_args, _run
from flowboard.short_id import generate_unique_short_id

logger = logging.getLogger(__name__)

#: shortest part (seconds), most parts in one cut
CUT_MIN = 3.0
MAX_PARTS = 30
#: "Chia đều": a cut moves to the pause between two lines when one is this close to the length asked for
EVEN_SLACK = 0.4
SNAP_S = 2.5
CUT_TIMEOUT_S = 30 * 60

#: job id → {status: running|done|error, phase, progress, done, total, error, parts}
SPLITS: dict[str, dict[str, Any]] = {}


class SplitError(RuntimeError):
    pass


def _clean_title(t: Any) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip()[:80]


SUBTITLE_MAX = 120


def _clean_subtitle(t: Any) -> str:
    """A part's second line under its name ("✂️ Cắt video" → Tự cắt): optional."""
    return re.sub(r"\s+", " ", str(t or "")).strip()[:SUBTITLE_MAX]


def base_name(job: dub.Job) -> str:
    return (job.name or job.title or "Video").strip()[:60]


def normalize_rows(raw: Any, duration: float = 0.0) -> list[dict[str, Any]]:
    """``[{start, end, title}]`` (seconds, rounded to 0.01; end kept inside the video), at most :data:`MAX_PARTS`.
    Rows that are not numbers are dropped; bad times are kept so the page can say what is wrong."""
    rows: list[dict[str, Any]] = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        try:
            a, b = float(r.get("start")), float(r.get("end"))
        except (TypeError, ValueError):
            continue
        a = round(max(0.0, a), 2)
        b = round(min(b, duration) if duration > 0 else b, 2)
        row = {"start": a, "end": b, "title": _clean_title(r.get("title"))}
        if _clean_subtitle(r.get("subtitle")):
            row["subtitle"] = _clean_subtitle(r.get("subtitle"))
        rows.append(row)
    return rows[:MAX_PARTS]


def row_problem(row: dict[str, Any], duration: float) -> str:
    """What is wrong with one row ("" = fine)."""
    a, b = row["start"], row["end"]
    if duration > 0 and a >= duration - 0.05:
        return "bắt đầu đã quá cuối video"
    if b - a < CUT_MIN:
        return f"ngắn hơn {CUT_MIN:g} giây"
    return ""


def cut_points(job: dub.Job) -> list[float]:
    """Good places to cut: the middle of the pause between two lines (inside the video)."""
    segs = sorted((s for s in job.segments if s.end > s.start), key=lambda s: s.start)
    pts = []
    for a, b in zip(segs, segs[1:]):
        mid = (a.end + b.start) / 2 if b.start > a.end else a.end
        if 0 < mid < (job.duration_s or 10 ** 9):
            pts.append(round(mid, 2))
    return pts


def snap(t: float, points: list[float], within: float = SNAP_S) -> float:
    """``t`` moved to the nearest pause between lines when one is within ``within`` seconds."""
    best = min(points, key=lambda p: abs(p - t), default=None)
    return best if best is not None and abs(best - t) <= within else t


def _titled(job: dub.Job, spans: list[tuple[float, float]]) -> list[dict[str, Any]]:
    base = base_name(job)
    n = len(spans)
    return [{"start": round(a, 2), "end": round(b, 2), "title": f"{base} — Phần {i}/{n}" if n > 1 else base}
            for i, (a, b) in enumerate(spans, 1)]


def suggest_even(job: dub.Job, target_s: float) -> list[dict[str, Any]]:
    """Parts of about ``target_s`` seconds, each ended in the pause between two lines nearest that length (within
    ±:data:`EVEN_SLACK`); a short tail joins the last part."""
    dur = float(job.duration_s or 0)
    if dur <= 0:
        return []
    target = max(CUT_MIN * 2, float(target_s))
    pts = cut_points(job)
    spans: list[tuple[float, float]] = []
    start = 0.0
    while dur - start > target * (1 + EVEN_SLACK):
        want = start + target
        near = [p for p in pts if start + target * (1 - EVEN_SLACK) <= p <= start + target * (1 + EVEN_SLACK)]
        cut = min(near, key=lambda p: abs(p - want)) if near else want
        spans.append((start, cut))
        start = cut
        if len(spans) >= MAX_PARTS - 1:
            break
    spans.append((start, dur))
    return _titled(job, spans)


_AI_SYSTEM = (
    "You split the transcript of one Vietnamese video (already dubbed) into several short videos for TikTok / Facebook "
    "Reels. Rules: every part must be one whole idea that makes sense on its own (a viewer who never saw the other "
    "parts understands it), cut only BETWEEN lines (a part is a run of whole consecutive lines), keep the original "
    "order, parts do not overlap; skip nothing unless it is an intro / outro that does not stand alone; each part "
    "around the length asked for (never under 15 seconds unless the whole video is shorter). Give each part a catchy "
    "Vietnamese title (<= 60 chars) that makes people want to watch that part — about that part's content, no "
    "clickbait lies, no hashtags. Output ONLY one JSON object: "
    "{\"parts\": [{\"from\": <first line number>, \"to\": <last line number>, \"title\": str}]}"
)


def _json_obj(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise SplitError("AI không trả JSON")
    try:
        d = json.loads(m.group(0))
    except ValueError as exc:
        raise SplitError(f"AI trả JSON hỏng: {exc}") from exc
    if not isinstance(d, dict):
        raise SplitError("AI trả sai dạng")
    return d


def parts_from_ai(job: dub.Job, data: dict[str, Any]) -> list[dict[str, Any]]:
    """The AI's line ranges → rows, cut in the middle of the pause around each range; checked for order and size."""
    segs = job.segments
    n = len(segs)
    dur = float(job.duration_s or (segs[-1].end if segs else 0))
    rows: list[dict[str, Any]] = []
    last_to = 0
    for p in data.get("parts") or []:
        try:
            a, b = int(p.get("from")), int(p.get("to"))
        except (TypeError, ValueError, AttributeError):
            continue
        a, b = max(1, a), min(n, b)
        if b < a or a <= last_to:
            continue
        start = 0.0 if a == 1 else (segs[a - 2].end + segs[a - 1].start) / 2
        end = dur if b == n else (segs[b - 1].end + segs[b].start) / 2
        rows.append({"start": round(max(0.0, start), 2), "end": round(min(dur, end), 2), "title": _clean_title(p.get("title"))})
        last_to = b
    rows = [r for r in rows if r["end"] - r["start"] >= CUT_MIN][:MAX_PARTS]
    if not rows:
        raise SplitError("AI không chia được đoạn nào hợp lệ")
    return rows


async def suggest_ai(job: dub.Job, target_s: float) -> list[dict[str, Any]]:
    segs = job.segments
    if not segs:
        raise SplitError("video chưa có câu nào")
    lines = [f"[{i}] ({s.start:.1f}s-{s.end:.1f}s) {s.text or s.src}" for i, s in enumerate(segs, 1)]
    prompt = (f"Video length: {job.duration_s:.0f} s. Video title: {job.name or job.title or '-'}.\n"
              f"Wanted length of each part: about {target_s:.0f} s.\nTRANSCRIPT ({len(lines)} lines):\n" + "\n".join(lines))
    try:
        text = await run_llm("auto_prompt", prompt, system_prompt=_AI_SYSTEM, timeout=180)
    except LLMError as exc:
        raise SplitError(str(exc)) from exc
    return parts_from_ai(job, _json_obj(text))


async def suggest(job: dub.Job, target_s: float, use_ai: bool) -> dict[str, Any]:
    """``{rows, by: "ai" | "even", note}`` — the AI when asked (its failure falls back to the even split)."""
    if use_ai:
        try:
            return {"rows": await suggest_ai(job, target_s), "by": "ai", "note": ""}
        except SplitError as exc:
            logger.warning("dub_split %s: AI suggestion failed, even split instead: %s", job.id, exc)
            return {"rows": suggest_even(job, target_s), "by": "even", "note": f"AI chưa gợi ý được ({str(exc)[:160]}) — đã chia theo chỗ ngắt câu"}
    return {"rows": suggest_even(job, target_s), "by": "even", "note": ""}


def save_rows(job: dub.Job, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    job.cuts = normalize_rows(rows, job.duration_s)
    dub.persist(job)
    return job.cuts


# ── cutting ───────────────────────────────────────────────────────────────

def state(job_id: str) -> dict[str, Any]:
    st = SPLITS.get(job_id)
    return dict(st) if st else {"status": "idle"}


def _source(job: dub.Job) -> Path:
    if not job.media_id:
        raise SplitError("Video chưa xuất lần nào — bấm \"Xuất lại video\" trước rồi mới cắt")
    p = media_service.cached_path(job.media_id)
    if not p or not Path(p).is_file():
        raise SplitError("Không thấy file video đã xuất trên máy này")
    return Path(p)


def start(job: dub.Job, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Check the rows, keep them on the job, cut in a thread. Returns the starting state."""
    if SPLITS.get(job.id, {}).get("status") == "running":
        raise SplitError("Đang cắt video này rồi — chờ xong")
    if job.status in ("queued", "running", "rendering"):
        raise SplitError("Video đang xuất — chờ xuất xong rồi cắt")
    src = _source(job)
    rows = normalize_rows(rows, job.duration_s)
    if not rows:
        raise SplitError("Chưa có đoạn nào để cắt")
    bad = [f"Đoạn {i}: {row_problem(r, job.duration_s)}" for i, r in enumerate(rows, 1) if row_problem(r, job.duration_s)]
    if bad:
        raise SplitError("; ".join(bad[:4]))
    job.cuts = rows
    dub.persist(job)
    st = {"status": "running", "phase": "Chuẩn bị cắt", "progress": 0, "done": 0, "total": len(rows), "error": None,
          "parts": [], "started_at": time.time(), "title": base_name(job)}
    SPLITS[job.id] = st
    threading.Thread(target=_run_split, args=(job, src, rows), name=f"dub-split-{job.id}", daemon=True).start()
    return dict(st)


def _cut(ffmpeg: str, src: Path, start: float, end: float, dst: Path, tag: str, stop: Optional[Any] = None) -> None:
    # -ss before -i + re-encode: exact to the frame (as VieDub does), and fast to seek on a long video
    cmd = [ffmpeg, "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{end - start:.3f}",
           "-map", "0:v:0", "-map", "0:a:0?", *_encode_args(ffmpeg), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
           "-metadata", f"comment={tag}", "-movflags", "+faststart", str(dst)]
    if stop is not None:
        # "Dừng" while a part is being cut: ffmpeg is killed at once (not after the part is done)
        from flowboard.services.proc import Stopped, remove_soon, run_stoppable

        try:
            proc = run_stoppable(cmd, CUT_TIMEOUT_S, stop)
        except Stopped:
            remove_soon(dst)
            raise SplitError("Đã dừng theo yêu cầu") from None
        except subprocess.TimeoutExpired:
            remove_soon(dst)
            raise SplitError(f"ffmpeg cắt quá {CUT_TIMEOUT_S}s") from None
        err = None if proc.returncode == 0 else ((proc.stderr or b"").decode("utf-8", "replace").strip()[-500:] or f"exit code {proc.returncode}")
    else:
        err = _run(cmd, CUT_TIMEOUT_S)
    if err or not dst.is_file() or dst.stat().st_size == 0:
        raise SplitError(f"ffmpeg cắt lỗi: {err or 'file rỗng'}")


def _part_board(job: dub.Job, index: int, total: int, row: dict[str, Any], media_id: str,
                reuse: Optional[int]) -> int:
    """Part ``index`` as a clip: one video node (its lines as narration) + an export node holding the mp4."""
    name = row["title"] or f"{base_name(job)} — Phần {index}/{total}"
    narration = " ".join(s.text for s in job.segments if s.text.strip() and s.end > row["start"] and s.start < row["end"])
    qt = {"template_id": "dub_part", "step": 5, "source_url": job.url, "channel_id": job.channel_id,
          "dub_part": {"job_id": job.id, "index": index, "total": total, "start": row["start"], "end": row["end"]}}
    with get_session() as s:
        board = s.get(Board, reuse) if reuse else None
        if board is not None and ((board.data or {}).get("quicktool") or {}).get("template_id") != "dub_part":
            board = None
        if board is None:
            board = Board(name=name[:80], data={"quicktool": qt})
            s.add(board)
            s.commit()
            s.refresh(board)
            s.add(Node(board_id=board.id, short_id=generate_unique_short_id(s, board.id), type="video", x=0, y=0,
                       data={"title": f"Phần {index}", "narration": narration, "mediaId": media_id, "dubbed": True}, status="done"))
            s.add(Node(board_id=board.id, short_id=generate_unique_short_id(s, board.id), type="export", x=320, y=0,
                       data={"title": "Xuất", "mediaId": media_id}, status="done"))
        else:
            board.name = name[:80]
            qt_old = (board.data or {}).get("quicktool") or {}
            # a new cut is a new video: the old "đã tải" mark no longer holds
            board.data = {**(board.data or {}), "quicktool": {**{k: v for k, v in qt_old.items() if k != "downloaded_at"}, **qt}}
            s.add(board)
            for n in s.exec(select(Node).where(Node.board_id == board.id)).all():
                if n.type in ("video", "export"):
                    n.data = {**(n.data or {}), "mediaId": media_id, **({"narration": narration, "title": f"Phần {index}"} if n.type == "video" else {})}
                    n.status = "done"
                    s.add(n)
        s.commit()
        return int(board.id)


def _run_split(job: dub.Job, src: Path, rows: list[dict[str, Any]]) -> None:
    st = SPLITS[job.id]
    old = {int(p.get("index", 0)): p.get("board_id") for p in job.parts}
    parts: list[dict[str, Any]] = []
    try:
        ffmpeg = dub._ffmpeg()
        total = len(rows)
        for i, row in enumerate(rows, 1):
            st.update(phase=f"Đang cắt phần {i}/{total}", progress=int((i - 1) * 100 / total))
            media_id = uuid.uuid4().hex
            dst = media_service.MEDIA_CACHE_DIR / f"{media_id}.mp4"
            _cut(ffmpeg, src, row["start"], row["end"], dst, dub.output_tag(job))
            with get_session() as s:
                s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(dst), mime="video/mp4"))
                s.commit()
            board_id = _part_board(job, i, total, row, media_id, old.get(i))
            part = {"index": i, "start": row["start"], "end": row["end"], "title": row["title"] or f"{base_name(job)} — Phần {i}/{total}",
                    "media_id": media_id, "board_id": board_id, "at": time.time()}
            parts.append(part)
            st.update(done=i, parts=list(parts))
            job.parts = list(parts)
            dub.persist(job)
        st.update(status="done", phase=f"Đã cắt {total} video", progress=100)
        if job.board_id:  # the clip keeps the project snapshot (rows + parts) for reopening anywhere
            try:
                dub._save_board(job)
            except Exception as exc:  # noqa: BLE001 — the parts are made already
                logger.warning("dub_split %s: snapshot not updated: %s", job.id, exc)
    except SplitError as exc:
        st.update(status="error", error=str(exc))
    except Exception as exc:  # noqa: BLE001 — never die silently
        logger.exception("dub_split %s crashed", job.id)
        st.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        st["finished_at"] = time.time()
