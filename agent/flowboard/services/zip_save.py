"""Save several finished clips as one .zip straight into this machine's Downloads folder.

The agent runs on the user's own machine, so it writes the file itself instead of building the
whole archive and only then handing it to the browser: ten clips (~800 MB) took tens of seconds
before the first byte left, the desktop app (WebView2) showed nothing meanwhile, and the button
looked dead — people clicked again and again (four identical copies in Downloads, 15/11). Now
the page gets a job at once, reads how far it is, and is offered "show the file" at the end.

  start(ids, page)  → a job (the same running job again when those clips are already being saved)
  job(id) / view    → {status running|done|error|stopped, phase, done_bytes, total_bytes, name, …}
  stop(id), reveal(id)

Jobs live in RAM; a restart forgets them (a half-written file is a ``.part`` and is removed).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

from sqlmodel import select

from flowboard import config
from flowboard.db import get_session
from flowboard.db.models import Board, Node
from flowboard.services import media as media_service

logger = logging.getLogger(__name__)

MAX_CLIPS = 50
CHUNK = 4 * 1024 * 1024
#: Room left on the disk after the zip (a full disk breaks everything else too).
SPARE_BYTES = 64 * 1024 * 1024
KEEP_JOBS = 20

_LOCK = threading.Lock()
JOBS: dict[str, "ZipJob"] = {}


@dataclass
class ZipJob:
    id: str
    ids: tuple[int, ...]
    page: str = ""
    owner: str = ""
    status: str = "running"
    phase: str = "Đang chuẩn bị"
    done_bytes: int = 0
    total_bytes: int = 0
    clips: int = 0
    name: str = ""
    folder: str = ""
    path: str = ""
    skipped: list[int] = field(default_factory=list)
    error: str = ""
    stop: bool = False
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0

    def view(self) -> dict[str, Any]:
        pct = int(self.done_bytes * 100 / self.total_bytes) if self.total_bytes else 0
        return {"id": self.id, "ids": list(self.ids), "status": self.status, "phase": self.phase,
                "progress": min(100, pct) if self.status == "running" else (100 if self.status == "done" else pct),
                "done_bytes": self.done_bytes, "total_bytes": self.total_bytes, "clips": self.clips,
                "name": self.name, "folder": self.folder, "skipped": list(self.skipped), "error": self.error,
                "stopping": self.stop and self.status == "running", "page": self.page,
                "started_at": self.started_at, "finished_at": self.finished_at or None}


# ── where the file goes ─────────────────────────────────────────────────────────────────────────

def _known_downloads() -> Optional[Path]:
    """Windows' own Downloads folder (it can be moved to another drive, so not just ~/Downloads)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", wintypes.BYTE * 8)]

        # FOLDERID_Downloads {374DE290-123F-4565-9164-39C4925E467B}
        fid = GUID(0x374DE290, 0x123F, 0x4565, (wintypes.BYTE * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) != 0:
            return None
        try:
            return Path(out.value) if out.value else None
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
    except Exception:  # noqa: BLE001 — any failure falls back to the plain guess
        return None


def _xdg_downloads() -> Optional[Path]:
    try:
        done = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=5)
        raw = done.stdout.strip()
        return Path(raw) if raw and raw != str(Path.home()) else None
    except Exception:  # noqa: BLE001
        return None


def downloads_dir() -> Path:
    """``FLOWBOARD_DOWNLOADS_DIR`` (tests), else the system's Downloads folder, else ``<data>/exports``."""
    raw = os.environ.get("FLOWBOARD_DOWNLOADS_DIR", "").strip()
    if raw:
        return Path(raw)
    for found in (_known_downloads(), _xdg_downloads(), Path.home() / "Downloads"):
        if found is not None and found.is_dir() and os.access(found, os.W_OK):
            return found
    return Path(config.HOME or config.ROOT) / "exports"


def free_name(folder: Path, stem: str, ext: str = ".zip") -> Path:
    """``stem.zip``, else ``stem (2).zip``… — never over a file already there (or one being written)."""
    n = 1
    while True:
        name = f"{stem}{ext}" if n == 1 else f"{stem} ({n}){ext}"
        p = folder / name
        if not p.exists() and not p.with_name(p.name + ".part").exists():
            return p
        n += 1


# ── the clips ───────────────────────────────────────────────────────────────────────────────────

def final_media(board_ids: list[int]) -> dict[int, str]:
    """Each clip's last joined video (the export / merge node's media), in one query."""
    with get_session() as s:
        rows = s.exec(select(Node.board_id, Node.data)
                      .where(Node.board_id.in_(board_ids), Node.type.in_(["export", "merge"]))
                      .order_by(Node.id)).all()
    out: dict[int, str] = {}
    for bid, data in rows:
        if isinstance(data, dict) and data.get("mediaId"):
            out[bid] = data["mediaId"]  # the last one wins, as exports._final_media does
    return out


def clip_names(board_ids: list[int]) -> dict[int, str]:
    with get_session() as s:
        return {b.id: (b.name or "") for b in s.exec(select(Board).where(Board.id.in_(board_ids))).all()}


def _mark_downloaded(board_ids: list[int]) -> None:
    stamp = int(time.time() * 1000)
    with get_session() as s:
        for bid in board_ids:
            b = s.get(Board, bid)
            if b is None:
                continue
            data = dict(b.data or {})
            data["quicktool"] = {**(data.get("quicktool") or {}), "downloaded_at": stamp}
            b.data = data
            s.add(b)
        s.commit()


def _owner() -> str:
    """The account whose data folder is open — a save started for another account is not marked in this one."""
    return str(media_service.MEDIA_CACHE_DIR)


# ── the job ─────────────────────────────────────────────────────────────────────────────────────

def _norm_ids(ids: list[int]) -> tuple[int, ...]:
    seen: list[int] = []
    for i in ids:
        try:
            n = int(i)
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in seen:
            seen.append(n)
    return tuple(seen[:MAX_CLIPS])


def start(ids: list[int], page: str = "") -> ZipJob:
    board_ids = _norm_ids(ids)
    if not board_ids:
        raise ValueError("Chưa chọn clip nào.")
    page = page if page.startswith("/") and len(page) <= 200 else ""
    with _LOCK:
        for j in JOBS.values():
            if j.status == "running" and j.ids == board_ids:
                return j  # a second click on the same clips: the save already under way
        job = ZipJob(id=uuid.uuid4().hex[:12], ids=board_ids, page=page, owner=_owner())
        JOBS[job.id] = job
        for old in sorted((x for x in JOBS.values() if x.status != "running"), key=lambda x: x.started_at)[:-KEEP_JOBS]:
            JOBS.pop(old.id, None)
    threading.Thread(target=_run, args=(job,), name=f"zip-save-{job.id}", daemon=True).start()
    return job


def get(job_id: str) -> Optional[ZipJob]:
    return JOBS.get(job_id)


def stop(job_id: str) -> Optional[ZipJob]:
    job = JOBS.get(job_id)
    if job is not None and job.status == "running":
        job.stop = True
    return job


class _Stopped(Exception):
    pass


def _gb(n: int) -> str:
    return f"{n / 1024 ** 3:.1f}".replace(".", ",") + " GB"


def _run(job: ZipJob) -> None:
    from flowboard.routes.exports import slug  # one naming rule for both download paths

    part: Optional[Path] = None
    try:
        ids = list(job.ids)
        names = clip_names(ids)
        medias = final_media(ids)
        today = date.today().isoformat()
        files: list[tuple[int, str, Path]] = []
        used: set[str] = set()
        for n, bid in enumerate(ids, 1):
            if job.stop:
                raise _Stopped()
            media = medias.get(bid) if bid in names else None
            job.phase = f"Đang lấy clip {n}/{len(ids)}"
            path = media_service.cached_path(media) if media else None  # may fetch it from the cloud bucket
            if path is None or not Path(path).is_file():
                job.skipped.append(bid)
                continue
            base = (names.get(bid) or "").split(" — ")[0]
            name = f"{slug(base)}_{today}_{bid}.mp4"
            while name in used:
                name = name.replace(".mp4", "_.mp4")
            used.add(name)
            files.append((bid, name, Path(path)))
        if not files:
            raise RuntimeError("Chưa có clip nào đã ghép trong số đã chọn.")
        job.clips = len(files)
        job.total_bytes = sum(p.stat().st_size for _, _, p in files)
        folder = downloads_dir()
        folder.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(folder).free
        if free < job.total_bytes + SPARE_BYTES:
            raise RuntimeError(f"Ổ chứa thư mục {folder} chỉ còn {_gb(free)} trống, cần khoảng {_gb(job.total_bytes)}.")
        with _LOCK:  # two saves finishing together must not pick the same name
            target = free_name(folder, f"DFlow_{today}_{len(files)}clip")
            part = target.with_name(target.name + ".part")
            part.touch()
        job.folder, job.name = str(folder), target.name
        # Stored, not deflated: mp4 is already compressed.
        with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            for k, (_, name, src) in enumerate(files, 1):
                job.phase = f"Đang lưu clip {k}/{len(files)}"
                info = zipfile.ZipInfo(name, date_time=time.localtime(src.stat().st_mtime)[:6])
                info.compress_type = zipfile.ZIP_STORED
                info.file_size = src.stat().st_size
                with src.open("rb") as fin, zf.open(info, "w", force_zip64=info.file_size >= 2 ** 31) as fout:
                    while True:
                        if job.stop:
                            raise _Stopped()
                        buf = fin.read(CHUNK)
                        if not buf:
                            break
                        fout.write(buf)
                        job.done_bytes += len(buf)
        os.replace(part, target)
        part = None
        job.path = str(target)
        if job.owner == _owner():
            _mark_downloaded([bid for bid, _, _ in files])
        job.phase = "Đã lưu"
        job.status = "done"
        if job.skipped:
            logger.info("zip_save: %d clip(s) skipped (no final video): %s", len(job.skipped), job.skipped)
    except _Stopped:
        job.status, job.phase = "stopped", "Đã dừng"
    except Exception as e:  # noqa: BLE001 — the page shows the reason
        logger.warning("zip_save %s failed: %s", job.id, e)
        job.status, job.phase = "error", "Lỗi"
        job.error = str(e) or e.__class__.__name__
    finally:
        if part is not None:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
        job.finished_at = time.time()


def reveal(job_id: str) -> bool:
    """Show the saved file in Explorer (selected), or open its folder elsewhere."""
    job = JOBS.get(job_id)
    if job is None or job.status != "done" or not job.path or not Path(job.path).is_file():
        return False
    if sys.platform == "win32":
        # One string: explorer reads "/select," and the quoted path itself (a list would quote the comma too).
        subprocess.Popen(f'explorer /select,"{job.path}"')  # noqa: S602 — our own file name, no quotes in it
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", job.path])
    else:
        subprocess.Popen(["xdg-open", str(Path(job.path).parent)])
    return True


# ── the "đang chạy" badge ───────────────────────────────────────────────────────────────────────

def running_items() -> list[dict[str, Any]]:
    out = []
    for j in list(JOBS.values()):
        if j.status != "running":
            continue
        n = len(j.ids)
        out.append({"key": f"zip:{j.id}", "kind": "zip", "title": f"Lưu {n} clip vào thư mục Tải về",
                    "detail": j.phase, "progress": j.view()["progress"] if j.total_bytes else None,
                    "started_at": j.started_at, "link": j.page or "/clips"})
    return out


def outcome(job_id: str) -> dict[str, Any]:
    j = JOBS.get(job_id)
    if j is None:
        return {"ok": True, "message": "Đã xong"}
    if j.status == "done":
        return {"ok": True, "message": f"Đã lưu {j.name} vào {j.folder}"}
    if j.status == "stopped":
        return {"ok": True, "message": "Đã dừng"}
    return {"ok": False, "message": j.error or "Lưu file .zip bị lỗi"}
