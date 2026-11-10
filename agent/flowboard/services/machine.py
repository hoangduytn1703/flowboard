"""What this machine can do — checked once, remembered in a file.

The NVIDIA card is asked for with ``nvidia-smi`` (it comes with the driver). That costs a process start, so the answer
is kept in ``machine.json`` next to the app's data (per machine, not per account) and the tool does not ask again on
every start. It asks again only when

* there is no answer yet (the first start),
* the driver changed — the *signature* (where nvidia-smi is, its size and date: one ``stat``, no process) differs from
  the one the answer was made with, so a card or driver installed later is picked up by itself,
* the seller presses "Kiểm tra lại" (Cài đặt → 🖥 Máy này).

Without a card the features that need one are switched off or marked slow (:func:`limits`) instead of failing halfway.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from flowboard import config

logger = logging.getLogger(__name__)

#: cuDNN 9 / cuBLAS 12 (the dubbing add-on's wheels) need at least this Windows driver
MIN_DRIVER = 528
VERSION = 1

_lock = threading.Lock()
_mem: Optional[dict[str, Any]] = None


def machine_file() -> Path:
    custom = os.getenv("FLOWBOARD_MACHINE_FILE")
    return Path(custom) if custom else (config.HOME or config.ROOT) / "machine.json"


def _smi() -> Optional[str]:
    exe = shutil.which("nvidia-smi")
    if exe is None and sys.platform == "win32":
        guess = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
        exe = str(guess) if guess.is_file() else None
    return exe


def signature() -> str:
    """Changes when an NVIDIA driver is installed, removed or updated — without starting any process."""
    exe = _smi()
    if not exe:
        return "none"
    try:
        st = os.stat(exe)
        return f"{exe}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        return f"{exe}|?"


def probe_gpu() -> Optional[dict[str, Any]]:
    """``{name, driver, vram_mb, old_driver}`` from nvidia-smi, None without a card (or a driver that does not answer)."""
    exe = _smi()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10)
        line = (out.stdout or "").strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2 or not parts[0]:
            return None
        try:
            major = int(parts[1].split(".")[0])
        except ValueError:
            major = 0
        vram = int(float(parts[2])) if len(parts) > 2 and parts[2].replace(".", "", 1).isdigit() else 0
        return {"name": parts[0], "driver": parts[1], "vram_mb": vram,
                "old_driver": sys.platform == "win32" and 0 < major < MIN_DRIVER}
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def _read() -> Optional[dict[str, Any]]:
    try:
        data = json.loads(machine_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != VERSION or "gpu" not in data:
        return None
    return data


def _write(data: dict[str, Any]) -> None:
    path = machine_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.part")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:  # noqa: BLE001 — the answer still lives in memory for this run
        logger.warning("machine: could not save %s: %s", path, exc)


def profile(refresh: bool = False) -> dict[str, Any]:
    """``{gpu, checked_at, signature, version}`` — from memory, else the file (when the driver did not change), else a
    fresh check that is then remembered."""
    global _mem
    with _lock:
        sig = signature()
        if not refresh:
            if _mem is not None and _mem.get("signature") == sig:
                return _mem
            saved = _read()
            if saved is not None and saved.get("signature") == sig:
                _mem = saved
                return saved
        data = {"version": VERSION, "gpu": probe_gpu(), "checked_at": time.time(), "signature": sig}
        _write(data)
        _mem = data
        logger.info("machine: checked — %s", (data["gpu"] or {}).get("name") or "no NVIDIA card")
        return data


def gpu(refresh: bool = False) -> Optional[dict[str, Any]]:
    return profile(refresh).get("gpu")


def has_gpu() -> bool:
    return gpu() is not None


#: what a machine without an NVIDIA card loses: "off" = switched off, "slow" = works on the CPU, slower
NO_GPU_LIMITS = (
    {"key": "ai_erase", "state": "off", "label": "Xoá phụ đề cứng bằng AI",
     "reason": "Máy này không có card màn hình NVIDIA — xoá chữ bằng AI (LaMa) chạy bằng CPU mất hàng giờ cho một video nên "
               "đã tắt. Dùng chế độ khoanh vùng (làm mờ / xoá logo)."},
    {"key": "whisper", "state": "slow", "label": "AI nghe lời trong video (lồng tiếng, phụ đề, cắt video theo nội dung)",
     "reason": "Máy này không có card màn hình NVIDIA nên AI nghe lời bằng CPU — chậm hơn khoảng 5–10 lần (video 10 phút "
               "mất chừng 5–10 phút). Video dài nên để chạy nền."},
)


def limits() -> list[dict[str, str]]:
    return [] if has_gpu() else [dict(x) for x in NO_GPU_LIMITS]


def limit(key: str) -> Optional[dict[str, str]]:
    return next((x for x in limits() if x["key"] == key), None)


def public(refresh: bool = False) -> dict[str, Any]:
    p = profile(refresh)
    return {"gpu": p.get("gpu"), "checked_at": p.get("checked_at"), "limits": limits()}


def warm() -> None:
    """Called once at start, off the event loop: the first start checks, later starts only read the file."""
    try:
        profile()
    except Exception:  # noqa: BLE001 — never stops the app from starting
        logger.exception("machine: check failed")
