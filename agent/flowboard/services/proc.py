"""Child processes that stop the moment the seller presses "Dừng" (yt-dlp downloading, ffmpeg cutting…).

``subprocess.run`` only comes back when the child is done, so a stop pressed half-way used to wait for the download or
the encode to finish first. :func:`run_stoppable` polls a ``stop()`` callback a few times a second and kills the child
— and whatever it started (yt-dlp runs ffmpeg) — like "End task" does.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from typing import Callable, Optional

#: how often a running child is asked whether it should stop (seconds)
POLL_S = 0.15


class Stopped(Exception):
    """The child was killed because ``stop()`` said so."""


def kill_tree(proc: "subprocess.Popen") -> None:
    """Kill ``proc`` and its children now. Windows: ``taskkill /T /F`` (``Popen.kill`` leaves the children running)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, check=False, creationflags=0x08000000)
        except (OSError, subprocess.SubprocessError):
            pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.SubprocessError:
        pass


def run_stoppable(cmd: list[str], timeout: float, stop: Optional[Callable[[], bool]] = None, **popen: object) -> "subprocess.CompletedProcess[bytes]":
    """``subprocess.run(cmd, capture_output=True)`` that ends early: :class:`Stopped` when ``stop()`` turns true,
    ``subprocess.TimeoutExpired`` after ``timeout`` seconds — the child (and its children) killed either way."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdout=out, stderr=err, **popen)  # type: ignore[call-overload]
        deadline = time.time() + timeout
        try:
            while proc.poll() is None:
                if stop is not None and stop():
                    kill_tree(proc)
                    raise Stopped()
                if time.time() > deadline:
                    kill_tree(proc)
                    raise subprocess.TimeoutExpired(cmd, timeout)
                time.sleep(POLL_S)
        except BaseException:
            kill_tree(proc)
            raise
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(cmd, proc.returncode, out.read(), err.read())


def remove_soon(path: "os.PathLike[str] | str") -> None:
    """Delete what a killed child was writing. Windows lets go of the file a moment after the process dies: a few
    tries, then leave it (a stray partial file is harmless)."""
    for _ in range(20):
        try:
            os.unlink(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.1)
