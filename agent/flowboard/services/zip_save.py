"""Save finished videos straight into this machine's save folder (Settings → 🖥 Máy này, else Downloads):
one video as its own .mp4, several as one .zip.

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
    #: videos named by the page rather than through a clip: (media id, file name without extension)
    media: tuple[tuple[str, str], ...] = ()
    #: a folder picked for this one save ("ask every time"), else the machine's save folder
    target: str = ""
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
        return {"id": self.id, "ids": list(self.ids), "media": [m for m, _n in self.media], "status": self.status, "phase": self.phase,
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


#: Settings → 🖥 Máy này: where saved videos go (a path on this machine) and whether to ask for a folder each time.
SAVE_DIR_KEY = "FLOWBOARD_SAVE_DIR"
SAVE_ASK_KEY = "FLOWBOARD_SAVE_ASK"


def system_downloads() -> Path:
    """The system's Downloads folder, else ``<data>/exports``."""
    for found in (_known_downloads(), _xdg_downloads(), Path.home() / "Downloads"):
        if found is not None and found.is_dir() and os.access(found, os.W_OK):
            return found
    return Path(config.HOME or config.ROOT) / "exports"


def chosen_dir() -> str:
    return os.environ.get(SAVE_DIR_KEY, "").strip().strip('"')


def ask_each_time() -> bool:
    return os.environ.get(SAVE_ASK_KEY, "").strip() == "1"


def downloads_dir() -> Path:
    """``FLOWBOARD_DOWNLOADS_DIR`` (tests), else the folder chosen in Settings, else the system's Downloads folder."""
    raw = os.environ.get("FLOWBOARD_DOWNLOADS_DIR", "").strip()
    if raw:
        return Path(raw)
    chosen = chosen_dir()
    if chosen and Path(chosen).is_absolute():
        return Path(chosen)
    return system_downloads()


def usable_folder(raw: str) -> Path:
    """A folder a save may write into (created when missing) — ValueError with the reason otherwise."""
    path = Path(raw.strip().strip('"'))
    if not path.is_absolute():
        raise ValueError(f"Cần đường dẫn đầy đủ, ví dụ D:\\Video (nhận được: {raw})")
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".dflow-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise ValueError(f"Không ghi được vào thư mục {path} ({exc.strerror or exc})")
    return path


def pick_folder(start: str = "", title: str = "Chọn thư mục lưu video") -> Optional[str]:
    """The Windows folder picker, on this machine (the agent runs on the user's own computer); None when cancelled.
    A separate PowerShell process so the dialog is a real window even from the app's hidden agent; an owner form
    kept on top so it does not open behind the DFlow window."""
    if sys.platform != "win32":
        raise ValueError("Chỉ chọn thư mục bằng hộp thoại được trên Windows — gõ đường dẫn vào ô.")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$o = New-Object System.Windows.Forms.Form; $o.TopMost = $true; $o.ShowInTaskbar = $false;"
        "$o.StartPosition = 'CenterScreen'; $o.Size = New-Object System.Drawing.Size(1,1); $o.Opacity = 0; $o.Show(); $o.Activate();"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.ShowNewFolderButton = $true;"
        "$d.Description = $env:DFLOW_PICK_TITLE;"
        "if ($env:DFLOW_PICK_START -and (Test-Path -LiteralPath $env:DFLOW_PICK_START)) { $d.SelectedPath = $env:DFLOW_PICK_START };"
        "$r = $d.ShowDialog($o); $o.Close();"
        "if ($r -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::OutputEncoding = [Text.Encoding]::UTF8; Write-Output $d.SelectedPath }"
    )
    env = {**os.environ, "DFLOW_PICK_TITLE": title[:120], "DFLOW_PICK_START": start or str(downloads_dir())}
    try:
        done = subprocess.run(["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script],
                              capture_output=True, timeout=15 * 60, env=env)
    except subprocess.TimeoutExpired:
        return None
    out = done.stdout.decode("utf-8", "replace").strip().splitlines()
    return out[-1].strip() if out and out[-1].strip() else None


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


def _norm_media(media: Optional[list[dict[str, Any]]]) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for m in media or []:
        mid = str((m or {}).get("media_id") or "").strip().removeprefix("media/")
        if mid and all(c.isalnum() or c in "-_" for c in mid) and mid not in (x for x, _ in out):
            out.append((mid, str((m or {}).get("name") or "").strip()[:120]))
    return tuple(out[:MAX_CLIPS])


def start(ids: list[int], page: str = "", media: Optional[list[dict[str, Any]]] = None, folder: str = "") -> ZipJob:
    board_ids = _norm_ids(ids)
    items = _norm_media(media)
    if not board_ids and not items:
        raise ValueError("Chưa chọn video nào.")
    target = str(usable_folder(folder)) if folder.strip() else ""
    page = page if page.startswith("/") and len(page) <= 200 else ""
    with _LOCK:
        for j in JOBS.values():
            if j.status == "running" and j.ids == board_ids and j.media == items:
                return j  # a second click on the same clips: the save already under way
        job = ZipJob(id=uuid.uuid4().hex[:12], ids=board_ids, media=items, target=target, page=page, owner=_owner())
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
        names = clip_names(ids) if ids else {}
        medias = final_media(ids) if ids else {}
        today = date.today().isoformat()
        # (board id or 0, file name in the folder / zip, source)
        files: list[tuple[int, str, Path]] = []
        used: set[str] = set()
        total = len(ids) + len(job.media)

        def add(bid: int, media: Optional[str], name: str, n: int) -> None:
            if job.stop:
                raise _Stopped()
            job.phase = f"Đang lấy video {n}/{total}"
            path = media_service.cached_path(media) if media else None  # may fetch it from the cloud bucket
            if path is None or not Path(path).is_file():
                if bid:
                    job.skipped.append(bid)
                return
            while name in used:
                name = name.replace(".mp4", "_.mp4")
            used.add(name)
            files.append((bid, name, Path(path)))

        for n, bid in enumerate(ids, 1):
            base = (names.get(bid) or "").split(" — ")[0]
            add(bid, medias.get(bid) if bid in names else None, f"{slug(base)}_{today}_{bid}.mp4", n)
        for n, (mid, label) in enumerate(job.media, len(ids) + 1):
            add(0, mid, f"{slug(label) if label else 'video'}_{today}.mp4", n)
        if not files:
            raise RuntimeError("Video chưa có trên máy này (chưa ghép xong, hoặc làm ở máy khác mà chưa lên cloud).")
        job.clips = len(files)
        job.total_bytes = sum(p.stat().st_size for _, _, p in files)
        folder = Path(job.target) if job.target else downloads_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Không tạo được thư mục lưu {folder} ({exc.strerror or exc}) — đổi ở Cài đặt → 🖥 Máy này.")
        free = shutil.disk_usage(folder).free
        if free < job.total_bytes + SPARE_BYTES:
            raise RuntimeError(f"Ổ chứa thư mục {folder} chỉ còn {_gb(free)} trống, cần khoảng {_gb(job.total_bytes)}.")
        single = len(files) == 1
        with _LOCK:  # two saves finishing together must not pick the same name
            if single:
                target = free_name(folder, Path(files[0][1]).stem, ".mp4")
            else:
                target = free_name(folder, f"DFlow_{today}_{len(files)}clip")
            part = target.with_name(target.name + ".part")
            part.touch()
        job.folder, job.name = str(folder), target.name
        if single:
            job.phase = "Đang lưu video"
            with files[0][2].open("rb") as fin, part.open("wb") as fout:
                while True:
                    if job.stop:
                        raise _Stopped()
                    buf = fin.read(CHUNK)
                    if not buf:
                        break
                    fout.write(buf)
                    job.done_bytes += len(buf)
        else:
            # Stored, not deflated: mp4 is already compressed.
            with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
                for k, (_, name, src) in enumerate(files, 1):
                    job.phase = f"Đang lưu video {k}/{len(files)}"
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
            _mark_downloaded([bid for bid, _, _ in files if bid])
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
        n = len(j.ids) + len(j.media)
        out.append({"key": f"zip:{j.id}", "kind": "zip", "title": f"Lưu {n} video vào thư mục lưu video",
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
