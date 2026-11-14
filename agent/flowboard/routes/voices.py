"""🧬 Giọng nhân bản (services/voice_clone): voices learnt from the seller's short recordings.

  GET    /api/voices/clones                → [{uid, voice, name, gender, label, speech_s, created_at}]
  POST   /api/voices/clones                multipart {file, name, gender?, consent} → the new voice (≈ 10–60 s: VieNeu
                                           learns the voice and reads the "Nghe thử" sample in it)
  PATCH  /api/voices/clones/{uid}          {name?, gender?}
  DELETE /api/voices/clones/{uid}
A cloned voice's id (``vieneu:clone:<uid>``) goes wherever a voice id goes (dub, clip export, previews).
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from flowboard.services import voice_clone

router = APIRouter(prefix="/api/voices", tags=["voices"])

_AUDIO_EXT = {".mp3", ".m4a", ".wav", ".ogg", ".oga", ".opus", ".webm", ".aac", ".flac", ".mp4", ".amr", ".3gp"}


@router.get("/clones")
def list_clones() -> list[dict[str, Any]]:
    return voice_clone.list_clones()


@router.post("/clones", status_code=201)
async def create_clone(file: UploadFile = File(...), name: str = Form(""), gender: str = Form(""),
                       consent: bool = Form(False)) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix and suffix not in _AUDIO_EXT and not (file.content_type or "").startswith(("audio/", "video/")):
        raise HTTPException(400, "Cần file ghi âm (mp3, m4a, wav, ogg, webm…)")
    fd, tmp = tempfile.mkstemp(prefix="flowboard_clone_", suffix=suffix or ".webm")
    path = Path(tmp)
    try:
        size = 0
        with open(fd, "wb") as fh:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > voice_clone.MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"File ghi âm lớn hơn {voice_clone.MAX_UPLOAD_BYTES // (1024 * 1024)} MB — "
                                             "chỉ cần khoảng 10 giây nói")
                fh.write(chunk)
        if size == 0:
            raise HTTPException(400, "File rỗng")
        try:
            return await voice_clone.create(path, name=name, gender=gender, consent=consent)
        except voice_clone.CloneError as exc:
            raise HTTPException(400, str(exc))
    finally:
        path.unlink(missing_ok=True)


class CloneEdit(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    gender: Optional[str] = Field(default=None, max_length=10)


@router.patch("/clones/{uid}")
def edit_clone(uid: str, body: CloneEdit) -> dict[str, Any]:
    try:
        return voice_clone.update(uid, name=body.name, gender=body.gender)
    except voice_clone.CloneError as exc:
        raise HTTPException(404 if "Không thấy" in str(exc) else 400, str(exc))


@router.delete("/clones/{uid}")
def delete_clone(uid: str) -> dict[str, Any]:
    if not voice_clone.delete(uid):
        raise HTTPException(404, "Không thấy giọng này")
    return {"ok": True}
