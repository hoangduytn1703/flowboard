"""🧬 Giọng nhân bản — the seller's own voice (or one they may use) learnt from a short recording.

VieNeu-TTS v3 Turbo (the model behind the 25 VieNeu voices, Apache-2.0) clones a voice from a few seconds of
speech: ``encode_reference`` turns the recording into a 192-number speaker embedding + reference codes, and
``infer(text, voice={...})`` reads any text with it. The runner (``dub_runner vieneu-enroll``) does the learning in
the dubbing runtime (VieDub's venv or the "gói lồng tiếng" add-on — the same place VieNeu already runs).

A cloned voice is a ``VoiceClone`` row in the account's data (the ~9 KB embedding, not the recording), so every
machine signed in to the account has it. Its voice id is ``vieneu:clone:<uid>`` — a VieNeu voice to the rest of the
tool (``tts.voice_kind`` → "vieneu"): the dub, clip export, previews and the cache take it like a preset voice; only
the runner call differs (``@<voice.json>``, written from the row by :func:`voice_file`).

Tried 14/11 on the home machine (CPU): learning 8 s warm (27 s the first time), a 6 s line in ~5 s; speaker-embedding
cosine to the recording 0.63–0.82 against 0.25 for a preset voice.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import VoiceClone

logger = logging.getLogger(__name__)

PREFIX = "vieneu:clone:"
_UID_RE = re.compile(r"^[0-9a-f]{12}$")
MAX_CLONES = 30
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
#: what is kept of a recording (VieNeu Turbo hears at most 8 s of speech; the rest only costs time)
KEEP_S = 30
GENDERS = {"male": "nam", "female": "nữ", "": ""}
ENROLL_TIMEOUT_S = 600


class CloneError(Exception):
    pass


def is_clone(voice: str) -> bool:
    return isinstance(voice, str) and voice.startswith(PREFIX) and bool(_UID_RE.fullmatch(voice[len(PREFIX):]))


def voice_id(uid: str) -> str:
    return PREFIX + uid


def _uid(voice_or_uid: str) -> str:
    return voice_or_uid[len(PREFIX):] if voice_or_uid.startswith(PREFIX) else voice_or_uid


def _get(uid: str) -> Optional[VoiceClone]:
    if not _UID_RE.fullmatch(uid or ""):
        return None
    with get_session() as db:
        return db.exec(select(VoiceClone).where(VoiceClone.uid == uid)).first()


def exists(voice: str) -> bool:
    try:
        return is_clone(voice) and _get(_uid(voice)) is not None
    except Exception:  # noqa: BLE001 — no account open yet: no cloned voices
        return False


def label(row: VoiceClone) -> str:
    g = GENDERS.get(row.gender or "", "")
    return f"{row.name or 'Giọng nhân bản'}{f' ({g})' if g else ''}"


def row(r: VoiceClone) -> dict[str, Any]:
    return {"uid": r.uid, "voice": voice_id(r.uid), "name": r.name, "gender": r.gender or "", "label": label(r),
            "speech_s": round(float(r.speech_s or 0), 1),
            "created_at": r.created_at.isoformat() if r.created_at else None}


def list_clones() -> list[dict[str, Any]]:
    try:
        with get_session() as db:
            rows = db.exec(select(VoiceClone).order_by(VoiceClone.id.desc())).all()  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 — no account open (the voice list must still answer)
        return []
    return [row(r) for r in rows]


def _voices_dir() -> Path:
    from flowboard.services import tts

    d = tts.TTS_DIR / "voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def voice_file(voice: str) -> Path:
    """The cloned voice as the JSON file the runner reads (written from the account's data: a machine that never
    saw this voice still reads with it)."""
    r = _get(_uid(voice))
    if r is None or not (r.data or {}).get("speaker_emb"):
        raise CloneError("Không thấy giọng nhân bản này nữa (đã xoá?) — chọn giọng khác")
    path = _voices_dir() / f"{r.uid}.json"
    text = json.dumps(r.data)
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        tmp = path.with_suffix(".part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    return path


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name or "").strip()[:40]


def _prepare(src: Path, out: Path) -> None:
    """The recording as 24 kHz mono WAV, at most ``KEEP_S`` seconds, loudness evened out (phone memos are quiet)."""
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise CloneError("ffmpeg không có trên máy")
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src), "-t", str(KEEP_S), "-vn", "-ac", "1", "-ar", "24000",
           "-af", "loudnorm=I=-18:TP=-2:LRA=11", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise CloneError("Đọc file ghi âm quá lâu") from exc
    if r.returncode != 0 or not out.is_file() or out.stat().st_size < 4000:
        msg = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise CloneError(f"Không đọc được file ghi âm (cần mp3 / m4a / wav / ogg / webm). {msg[0][:160]}".strip())


async def create(src: Path, *, name: str, gender: str = "", consent: bool = False) -> dict[str, Any]:
    """Learn a voice from the recording at ``src`` → the saved voice (its "Nghe thử" sample is ready too)."""
    from flowboard.services import dub, tts

    if not consent:
        raise CloneError("Hãy xác nhận đây là giọng của bạn hoặc bạn được chủ giọng cho phép dùng")
    name = clean_name(name)
    if not name:
        raise CloneError("Đặt tên cho giọng (VD: Giọng của mình)")
    if gender not in GENDERS:
        gender = ""
    ok, why = tts.vieneu_available()
    if not ok:
        raise CloneError(f"Máy này chưa nhân bản giọng được: {why}")
    with get_session() as db:
        count = len(db.exec(select(VoiceClone.id)).all())
    if count >= MAX_CLONES:
        raise CloneError(f"Đã có {MAX_CLONES} giọng nhân bản — xoá bớt giọng không dùng rồi thêm")
    uid = secrets.token_hex(6)
    voice = voice_id(uid)
    work = Path(tempfile.mkdtemp(prefix="clone-", dir=str(_voices_dir())))
    ref, out = work / "ref.wav", work / "voice.json"
    key = tts._cache_key(tts.PREVIEW_TEXT, voice, 0, "")
    sample = tts.TTS_DIR / tts._audio_name(voice, key)
    try:
        await asyncio.to_thread(_prepare, src, ref)
        try:
            res = await asyncio.to_thread(dub._runner, "vieneu-enroll", str(ref), str(out), str(sample),
                                          tts.PREVIEW_TEXT, timeout=ENROLL_TIMEOUT_S)
        except dub.DubError as exc:
            raise CloneError(f"Không nhân bản được giọng: {exc}") from exc
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CloneError("VieNeu không trả giọng — thử file ghi âm khác") from exc
        if not data.get("speaker_emb"):
            raise CloneError("VieNeu không trả giọng — thử file ghi âm khác")
        now = datetime.now(timezone.utc)
        r = VoiceClone(uid=uid, name=name, gender=gender, data=data, speech_s=float(res.get("speech_s") or 0),
                       consent_at=now, created_at=now)
        with get_session() as db:
            db.add(r)
            db.commit()
            db.refresh(r)
        if sample.is_file() and sample.stat().st_size > 200:
            tts._finish(sample, key)
        logger.info("voice clone %s (%s) learnt from %.1fs of speech", uid, name, r.speech_s)
        return row(r)
    finally:
        for f in work.glob("*"):
            f.unlink(missing_ok=True)
        work.rmdir()


def update(uid: str, *, name: Optional[str] = None, gender: Optional[str] = None) -> dict[str, Any]:
    with get_session() as db:
        r = db.exec(select(VoiceClone).where(VoiceClone.uid == uid)).first()
        if r is None:
            raise CloneError("Không thấy giọng này")
        if name is not None:
            n = clean_name(name)
            if not n:
                raise CloneError("Tên giọng không được trống")
            r.name = n
        if gender is not None:
            r.gender = gender if gender in GENDERS else ""
        db.add(r)
        db.commit()
        db.refresh(r)
        return row(r)


def delete(uid: str) -> bool:
    with get_session() as db:
        r = db.exec(select(VoiceClone).where(VoiceClone.uid == uid)).first()
        if r is None:
            return False
        db.delete(r)
        db.commit()
    try:
        (_voices_dir() / f"{uid}.json").unlink(missing_ok=True)
    except OSError:
        pass
    return True
