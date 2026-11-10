"""Entry point of the desktop app's agent: PyInstaller builds this into resources/agent/dflow-agent.exe
(agent/packaging/dflow-agent.spec) and DFlow.exe (desktop/src-tauri) starts it with:

* FLOWBOARD_HOME — the app's own folder (%LOCALAPPDATA%\\DFlowData): .env, logs, data;
* FLOWBOARD_WEB_DIR / FLOWBOARD_EXTENSION_DIR — the built UI and the extension shipped next to it;
* FLOWBOARD_PARENT_PID — DFlow.exe, so the agent never outlives it (an update can then replace its files);
* PATH with the bundled ffmpeg first.

Run from the repo it works too: ``python agent/packaging/dflow_agent.py`` (then FLOWBOARD_HOME defaults to
%LOCALAPPDATA%\\DFlowData — set it to a scratch folder for a test run).
"""
from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import threading
from pathlib import Path

LOG_MAX_BYTES = 5 * 1024 * 1024
CREATE_NO_WINDOW = 0x08000000


def _home() -> Path:
    raw = os.environ.get("FLOWBOARD_HOME")
    if raw:
        return Path(raw)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "DFlowData"


def _log_to_file(home: Path) -> None:
    """stdout / stderr (uvicorn, logging, prints) into logs/agent.log — the app has no console to show them."""
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / "agent.log"
    try:
        if log.is_file() and log.stat().st_size > LOG_MAX_BYTES:
            os.replace(log, logs / "agent.1.log")
    except OSError:
        pass
    stream = open(log, "a", encoding="utf-8", buffering=1, errors="replace")  # noqa: SIM115 — lives as long as the process
    sys.stdout = sys.stderr = stream


def _hide_child_consoles() -> None:
    """ffmpeg, ffprobe, yt-dlp, the Claude CLI… are console programs: started from a windowless app each would
    flash a black window. Every subprocess (asyncio's too — it subclasses Popen) starts without one."""
    if sys.platform != "win32":
        return
    original = subprocess.Popen.__init__

    def init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = init  # type: ignore[method-assign]


def _exit_with_parent() -> None:
    """Quit when DFlow.exe goes away (killed by an installer, crashed): otherwise this process keeps the ports and
    locks the files an update has to replace."""
    raw = os.environ.get("FLOWBOARD_PARENT_PID")
    if not raw or sys.platform != "win32":
        return
    import ctypes

    synchronize, infinite = 0x00100000, 0xFFFFFFFF
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, int(raw))
    if not handle:
        return

    def wait() -> None:
        ctypes.windll.kernel32.WaitForSingleObject(handle, infinite)
        os._exit(0)

    threading.Thread(target=wait, name="parent-watch", daemon=True).start()


def _temp_in_home(home: Path) -> None:
    """Python's temp files (an uploaded video is spooled there before the agent copies it — gigabytes for "Cắt video")
    in the data folder, not in %TEMP% on drive C. Leftovers older than a day (a crash mid-upload) are removed."""
    import tempfile
    import time

    tmp = home / "tmp"
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        for old in tmp.iterdir():
            if old.is_file() and time.time() - old.stat().st_mtime > 86400:
                old.unlink(missing_ok=True)
    except OSError:
        return
    tempfile.tempdir = str(tmp)


def main() -> None:
    multiprocessing.freeze_support()
    home = _home()
    home.mkdir(parents=True, exist_ok=True)
    _temp_in_home(home)
    os.environ.setdefault("FLOWBOARD_HOME", str(home))
    os.environ.setdefault("FLOWBOARD_APP", "1")
    if getattr(sys, "frozen", False) or os.environ.get("FLOWBOARD_LOG_TO_FILE") == "1":
        _log_to_file(home)
    _hide_child_consoles()
    _exit_with_parent()

    import uvicorn

    from flowboard.main import app

    port = int(os.environ.get("FLOWBOARD_HTTP_PORT", "8434"))
    print(f"DFlow agent: http://127.0.0.1:{port}  home={home}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
