"""Download several finished clips at once.

``GET /api/exports/zip?ids=3,5,8`` → one .zip with each clip's final video,
named after its product (or clip name) and the day, e.g.
``com-chay-sieu-cha-bong_2026-10-24_5.mp4``. The clips are marked as
downloaded (``quicktool.downloaded_at``), which "Hôm nay" reads.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import time
import unicodedata
import zipfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import select
from starlette.background import BackgroundTask

from flowboard.db import get_session
from flowboard.db.models import Board, Node
from flowboard.services import media as media_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exports", tags=["exports"])

MAX_CLIPS = 50


def slug(text: str, limit: int = 60) -> str:
    """ASCII file-name part: "Cơm cháy siêu chà bông!" → "com-chay-sieu-cha-bong"."""
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return (text[:limit].rstrip("-")) or "clip"


def _final_media(board_id: int) -> str | None:
    with get_session() as s:
        rows = s.exec(select(Node.data).where(Node.board_id == board_id, Node.type.in_(["export", "merge"]))).all()
    ids = [d.get("mediaId") for d in rows if isinstance(d, dict) and d.get("mediaId")]
    return ids[-1] if ids else None


@router.get("/zip")
def download_zip(ids: str = Query(..., description="comma-separated clip (board) ids")):
    try:
        board_ids = [int(x) for x in ids.split(",") if x.strip()][:MAX_CLIPS]
    except ValueError:
        raise HTTPException(400, "ids must be numbers")
    if not board_ids:
        raise HTTPException(400, "no clip ids")
    with get_session() as s:
        boards = {b.id: b for b in s.exec(select(Board).where(Board.id.in_(board_ids))).all()}
    today = date.today().isoformat()
    fd, tmp = tempfile.mkstemp(prefix="flowboard_clips_", suffix=".zip")
    os.close(fd)
    added: list[int] = []
    missing: list[int] = []
    used: set[str] = set()
    try:
        # Stored, not deflated: mp4 is already compressed.
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
            for bid in board_ids:
                board = boards.get(bid)
                media = _final_media(bid) if board else None
                path = media_service.cached_path(media) if media else None
                if board is None or path is None or not Path(path).is_file():
                    missing.append(bid)
                    continue
                base = (board.name or "").split(" — ")[0]
                name = f"{slug(base)}_{today}_{bid}.mp4"
                while name in used:
                    name = name.replace(".mp4", "_.mp4")
                used.add(name)
                zf.write(path, arcname=name)
                added.append(bid)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    if not added:
        Path(tmp).unlink(missing_ok=True)
        raise HTTPException(404, "Chưa có clip nào đã ghép trong số đã chọn.")
    stamp = int(time.time() * 1000)
    with get_session() as s:
        for bid in added:
            b = s.get(Board, bid)
            if b is None:
                continue
            data = dict(b.data or {})
            data["quicktool"] = {**(data.get("quicktool") or {}), "downloaded_at": stamp}
            b.data = data
            s.add(b)
        s.commit()
    if missing:
        logger.info("exports.zip: %d clip(s) skipped (no final video): %s", len(missing), missing)
    return FileResponse(tmp, media_type="application/zip", filename=f"flowboard_{today}_{len(added)}clip.zip",
                        headers={"X-Skipped-Clips": ",".join(map(str, missing))},
                        background=BackgroundTask(lambda: Path(tmp).unlink(missing_ok=True)))
