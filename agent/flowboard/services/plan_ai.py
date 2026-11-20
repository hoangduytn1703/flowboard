"""The ad plan of a reference video / product page, as fast as the AIs allow.

``POST /api/reference-video/analyze`` and ``/analyze-link`` used to send one
Gemini model at a time, retry a 503 twice with 5 + 10 s waits, then move to
the next model, each call allowed 300 s — on an evening Google is overloaded
(18/11: every flash model 503 for hours, only 3.1-flash-lite answering) the
seller waited 5 minutes for "502".

Now: the Gemini models race (:func:`gemini_api.race`), and when none has a
usable answer after :data:`BACKUP_AFTER_S` the AI the seller picked under
Cài đặt → 🤖 AI viết (the Claude CLI on the home machine) is asked too. The
CLIs read images, not video, so a video goes to it as ONE contact sheet of
:data:`SHEET_FRAMES` frames plus what Whisper heard. The first usable plan
wins. Measured on a 14 s clip: Gemini lite 15-20 s; the backup ~85 s
(Whisper ~40 s cold, Claude Sonnet low ~45 s) — with the Whisper part
started at once, so it is mostly done by the time the backup is needed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from flowboard.services.llm import gemini_api, registry

logger = logging.getLogger(__name__)

#: no usable Gemini answer this long after the start → the picked AI is asked too
BACKUP_AFTER_S = 25.0
#: the Gemini race gives up after this; the backup CLI gets BACKUP_TIMEOUT_S
RACE_DEADLINE_S = 150.0
BACKUP_TIMEOUT_S = 150.0
#: frames on the contact sheet the CLI reads (4 x 3, in time order)
SHEET_FRAMES = 12
SHEET_TILE = "4x3"
SHEET_WIDTH = 320
#: Whisper gets this long (from the start) before the backup goes without speech
HEAR_WAIT_S = 60.0
#: videos above Gemini's inline limit are re-encoded small (Gemini samples ~1 frame a second anyway)
SMALL_FPS = 2
SMALL_HEIGHT = 480


class PlanError(RuntimeError):
    """Neither Gemini nor the backup AI produced a plan."""


def _label(model: str) -> str:
    """"gemini-3.5-flash" → "Gemini 3.5 Flash"."""
    return " ".join(w if w[:1].isdigit() else w.capitalize() for w in model.replace("-", " ").split())


def _backup_label(provider: str, *, video: bool) -> str:
    name = {"claude": "Claude", "openai": "OpenAI (Codex)", "gemini": "Gemini CLI"}.get(provider, provider)
    return f"{name} (xem {SHEET_FRAMES} khung hình + lời nghe được)" if video else name


def json_only(schema: dict) -> str:
    """What a CLI (no JSON mode) is told about the answer's shape."""
    return ("Answer with ONLY one JSON object — no prose, no code fence — that matches this JSON schema:\n"
            + json.dumps(schema, ensure_ascii=False))


# -- the video, made readable for an AI that takes images -------------------

def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def contact_sheet(video: Path, out: Path, duration: float) -> list[float]:
    """:data:`SHEET_FRAMES` frames of ``video`` evenly over ``duration``, tiled
    into one JPEG at ``out``; the time (s) of each frame, in order."""
    n = SHEET_FRAMES
    dur = max(duration, 0.5)
    subprocess.run(
        [_ffmpeg(), "-y", "-loglevel", "error", "-i", str(video), "-vf",
         f"fps={n}/{dur:.3f},scale={SHEET_WIDTH}:-2,tile={SHEET_TILE}:padding=4:color=black",
         "-frames:v", "1", "-q:v", "4", str(out)],
        check=True, capture_output=True, timeout=120,
    )
    return [round((k + 0.5) * dur / n, 1) for k in range(n)]


def small_copy(video: Path, out: Path) -> Path:
    """A low-rate copy of ``video`` small enough to send inline."""
    subprocess.run(
        [_ffmpeg(), "-y", "-loglevel", "error", "-i", str(video), "-vf", f"scale=-2:{SMALL_HEIGHT}",
         "-r", str(SMALL_FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
         "-c:a", "aac", "-b:a", "48k", "-ac", "1", "-movflags", "+faststart", str(out)],
        check=True, capture_output=True, timeout=600,
    )
    return out


def hear(video: Path, work: Path, stop: Callable[[], bool]) -> list[str]:
    """What Whisper hears in ``video`` as "[a-b] words" lines; [] when this
    machine has no Whisper, it is busy (Cắt video is listening) or fails."""
    from flowboard.services import dub, dub_addon, video_cut

    if dub_addon.runtime() is None:
        return []
    if not video_cut._WHISPER_LOCK.acquire(timeout=2.0):
        logger.info("plan_ai: Whisper is busy with another video; the backup goes without speech")
        return []
    try:
        wav, out = work / "speech16.wav", work / "asr.json"
        dub._extract_wav(dub._ffmpeg(), video, wav, 16000, True)
        dub._runner("transcribe", str(wav), str(out), "auto", "-", "", stop=stop)
        data = json.loads(out.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — speech only helps; the frames still go
        logger.info("plan_ai: no speech for the backup (%s)", str(exc)[:160])
        return []
    finally:
        video_cut._WHISPER_LOCK.release()
    return [f"[{float(x['start']):.1f}-{float(x['end']):.1f}] {str(x.get('text') or '').strip()}"
            for x in data.get("segments") or [] if str(x.get("text") or "").strip()]


class _Prep:
    """The contact sheet + speech, made in a thread from the start."""

    def __init__(self, video: Path, duration: float, work: Path) -> None:
        self.video, self.duration, self.work = video, duration, work
        self.sheet: Optional[Path] = None
        self.times: list[float] = []
        self.speech: list[str] = []
        self.sheet_ready = threading.Event()
        self.heard = threading.Event()
        self.cancel = threading.Event()
        threading.Thread(target=self._run, name="plan-prep", daemon=True).start()

    def _run(self) -> None:
        try:
            out = self.work / "sheet.jpg"
            self.times = contact_sheet(self.video, out, self.duration)
            self.sheet = out
        except Exception as exc:  # noqa: BLE001
            logger.warning("plan_ai: contact sheet failed: %s", str(exc)[:160])
        finally:
            self.sheet_ready.set()
        try:
            if not self.cancel.is_set():
                self.speech = hear(self.video, self.work, self.cancel.is_set)
        finally:
            self.heard.set()

    async def ready(self, started: float) -> None:
        await asyncio.to_thread(self.sheet_ready.wait, 30.0)
        left = HEAR_WAIT_S - (time.monotonic() - started)
        if left > 0:
            await asyncio.to_thread(self.heard.wait, left)


# -- the race + the backup -------------------------------------------------

def _why(exc: BaseException) -> str:
    return str(exc)[:240] or type(exc).__name__


async def _first(
    gemini: Optional[Callable[[asyncio.Event], Any]],
    backup: Optional[Callable[[], Any]],
    backup_name: str,
) -> tuple[dict[str, Any], str]:
    """Run the Gemini race; ask the backup when it has nothing after
    :data:`BACKUP_AFTER_S` (or has already lost); first usable plan wins."""
    errors: list[str] = []
    got = asyncio.Event()
    gem: Optional[asyncio.Task] = asyncio.create_task(gemini(got)) if gemini else None
    back: Optional[asyncio.Task] = None
    if gem is not None:
        await asyncio.wait({gem}, timeout=None if backup is None else BACKUP_AFTER_S)
        if got.is_set() and not gem.done():
            await asyncio.wait({gem})  # a plan is in hand, only held for a stronger one: no backup needed
    if backup is not None and (gem is None or not gem.done() or gem.exception() is not None):
        logger.info("plan_ai: no Gemini plan yet — asking %s too", backup_name)
        back = asyncio.create_task(backup())
    pending = {t for t in (gem, back) if t is not None}
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in sorted(done, key=lambda t: t is not gem):  # Gemini first when both land together
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None:
                    errors.append(f"{'Gemini' if task is gem else backup_name}: {_why(exc)}")
                    continue
                if task is gem:
                    res = task.result()
                    return res.value, _label(res.model)
                return task.result(), backup_name
    finally:
        for task in pending:
            task.cancel()
    raise PlanError(" · ".join(errors) or "Không có AI nào trả lời")


async def plan_from_video(
    video: Path,
    ask: str,
    *,
    system: str,
    schema: dict,
    accept: Callable[[str], dict[str, Any]],
    duration: float,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """The plan for ``video``: Gemini watches it, the picked AI (backup) reads
    a contact sheet + the speech. ``accept`` parses + checks an answer (raises
    on a bad one). The result carries ``by`` = which AI wrote it."""
    started = time.monotonic()
    backup_ai = await registry.picked_ai("vision", vision=True)
    if not gemini_api.configured() and backup_ai is None:
        raise PlanError("Chưa có AI xem được video: thêm Gemini API key ở Cài đặt → 🔑 Gemini key, "
                        "hoặc chọn AI đọc ảnh ở Cài đặt → 🤖 AI viết.")
    work = Path(tempfile.mkdtemp(prefix="dflow-plan-"))
    prep = _Prep(video, duration, work) if backup_ai else None

    async def gemini(got: asyncio.Event):
        media = video
        if media.stat().st_size > gemini_api.INLINE_LIMIT_BYTES:
            media = await asyncio.to_thread(small_copy, video, work / "small.mp4")
            if media.stat().st_size > gemini_api.INLINE_LIMIT_BYTES:
                raise gemini_api.GeminiAPIError("video quá dài để gửi Gemini một lần")
        parts = [gemini_api.inline_part(media), gemini_api.text_part(ask)]
        models = list(gemini_api.RACE_MODELS)
        if model and model != gemini_api.DEFAULT_MODEL and model not in {m for m, _ in models}:
            models.insert(0, (model, None))  # a model the caller named runs too
        return await gemini_api.race(parts, accept, system=system, response_schema=schema, models=models,
                                     deadline_s=RACE_DEADLINE_S, got_answer=got)

    async def backup() -> dict[str, Any]:
        assert prep is not None
        await prep.ready(started)
        if prep.sheet is None:
            raise PlanError("không cắt được khung hình của video")
        frames = ", ".join(f"{k + 1}: {t:g}s" for k, t in enumerate(prep.times))
        text = (
            f"You cannot watch the video, so you get ONE image: {SHEET_FRAMES} frames of the reference ad video in "
            f"time order (read left to right, top to bottom; {duration:.1f} s long — frame times {frames}), and the "
            "speech heard in it.\n\nSPEECH (Whisper):\n" + ("\n".join(prep.speech) or "(no speech heard)") +
            "\n\n" + ask + "\n\n" + json_only(schema)
        )
        out = await registry.run_llm("vision", text, system_prompt=system, attachments=[str(prep.sheet)],
                                     timeout=BACKUP_TIMEOUT_S, effort="low", gemini_backup=False)
        return accept(out)

    try:
        analysis, by = await _first(gemini if gemini_api.configured() else None,
                                    backup if backup_ai else None,
                                    _backup_label(backup_ai or "", video=True))
    finally:
        if prep is not None:
            prep.cancel.set()  # Whisper stops; the folder goes once it has let go of its files

        def tidy() -> None:
            if prep is not None:
                prep.heard.wait(120)
            shutil.rmtree(work, ignore_errors=True)

        threading.Thread(target=tidy, name="plan-tidy", daemon=True).start()
    logger.info("plan_ai: video plan by %s in %.1fs", by, time.monotonic() - started)
    return {**analysis, "by": by}


async def plan_from_text(
    ask: str,
    *,
    system: str,
    schema: dict,
    accept: Callable[[str], dict[str, Any]],
    model: Optional[str] = None,
) -> dict[str, Any]:
    """The plan from text only (a product page): same race + backup."""
    started = time.monotonic()
    backup_ai = await registry.picked_ai("auto_prompt")
    if not gemini_api.configured() and backup_ai is None:
        raise PlanError("Chưa có AI nào: thêm Gemini API key ở Cài đặt → 🔑 Gemini key, hoặc chọn AI ở Cài đặt → 🤖 AI viết.")

    async def gemini(got: asyncio.Event):
        models = list(gemini_api.RACE_MODELS)
        if model and model != gemini_api.DEFAULT_MODEL and model not in {m for m, _ in models}:
            models.insert(0, (model, None))
        return await gemini_api.race([gemini_api.text_part(ask)], accept, system=system, response_schema=schema,
                                     models=models, deadline_s=RACE_DEADLINE_S, got_answer=got)

    async def backup() -> dict[str, Any]:
        out = await registry.run_llm("auto_prompt", ask + "\n\n" + json_only(schema), system_prompt=system,
                                     timeout=BACKUP_TIMEOUT_S, effort="low", gemini_backup=False)
        return accept(out)

    analysis, by = await _first(gemini if gemini_api.configured() else None,
                                backup if backup_ai else None,
                                _backup_label(backup_ai or "", video=False))
    logger.info("plan_ai: page plan by %s in %.1fs", by, time.monotonic() - started)
    return {**analysis, "by": by}
