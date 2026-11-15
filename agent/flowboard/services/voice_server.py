"""A resident VieNeu for the "vieneu:" voices and the cloned ones (15/11, "lồng tiếng vẫn chậm, nghe thử cũng chậm").

Every VieNeu call used to start ``dub_runner.py vieneu`` and load the model (~20–30 s) before reading a single line:
"▶ Nghe thử" took ~23 s, every dub paid it again. ``dub_runner.py serve`` keeps the model loaded: requests go one per
stdin line, answers come back one per stdout line (``dub_runner.SERVE_MARK``). One request at a time — when it is
busy, the caller falls back to the one-shot runner (``Busy``), so nothing ever waits behind a long dub. The server
stops after ``IDLE_S`` without a request (the model holds ~1 GB of RAM) and when the agent goes (its stdin closes).
``warm()`` loads it ahead of time (the voice field asks when a VieNeu voice is picked).
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: seconds without a request before the server (and its ~1 GB model) goes
IDLE_S = float(os.environ.get("FLOWBOARD_VOICE_IDLE_S") or 600)
MARK = "@@DFLOW "
#: the model load (first request after a start)
LOAD_TIMEOUT_S = 240


class VoiceServerError(RuntimeError):
    pass


class Busy(VoiceServerError):
    """Another request is being read: use the one-shot runner instead of waiting."""


class Stopped(VoiceServerError):
    pass


def enabled() -> bool:
    return os.environ.get("FLOWBOARD_VOICE_SERVER", "1") != "0"


class _Server:
    def __init__(self, cmd: list[str], env: dict[str, str], cwd: Path) -> None:
        self.cmd = cmd
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env=env, cwd=str(cwd))
        self.answers: dict[str, dict[str, Any]] = {}
        self.progress: dict[str, Callable[[int, int], None]] = {}
        self.tail: list[str] = []
        self.loaded = False
        self.cond = threading.Condition()
        threading.Thread(target=self._read_out, name="voice-server-out", daemon=True).start()
        threading.Thread(target=self._read_err, name="voice-server-err", daemon=True).start()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def _read_out(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith(MARK):
                continue
            try:
                ans = json.loads(line[len(MARK):])
            except ValueError:
                continue
            with self.cond:
                self.answers[str(ans.get("id") or "")] = ans
                self.cond.notify_all()
        with self.cond:
            self.cond.notify_all()

    def _read_err(self) -> None:
        assert self.proc.stderr is not None
        for raw in self.proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            if line.startswith("SPROGRESS "):
                parts = line.split()
                cb = self.progress.get(parts[1]) if len(parts) == 4 else None
                if cb is not None:
                    try:
                        cb(int(parts[2]), int(parts[3]))
                    except (ValueError, Exception):  # noqa: BLE001 — a progress callback never breaks the reading
                        pass
            elif line:
                self.tail.append(line)
                del self.tail[:-12]

    def send(self, req: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(req) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def ask(self, req: dict[str, Any], timeout: float, stop: Optional[Callable[[], bool]] = None) -> dict[str, Any]:
        """Send one request, wait for its answer. ``stop()`` → the request's ``cancel_file`` is made: the server ends it
        between two lines (it reads stdin only between requests — see ``dub_runner.serve``)."""
        rid = str(req["id"])
        cancel = Path(tempfile.gettempdir()) / f"dflow-voice-cancel-{rid}"
        if stop is not None:
            req = {**req, "cancel_file": str(cancel)}
        try:
            self.send(req)
        except OSError as exc:
            raise VoiceServerError(f"không gửi được tới tiến trình giọng đọc: {exc}") from exc
        deadline = time.time() + timeout
        cancelled = False
        try:
            with self.cond:
                while rid not in self.answers:
                    if not self.alive():
                        from flowboard.services.dub import runner_error

                        raise VoiceServerError(runner_error(self.tail) or f"tiến trình giọng đọc dừng ({self.proc.returncode})")
                    if stop is not None and not cancelled and stop():
                        cancelled = True
                        try:
                            cancel.write_bytes(b"")
                        except OSError:
                            pass
                        deadline = min(deadline, time.time() + 30)  # the line being read finishes first
                    if time.time() > deadline:
                        raise VoiceServerError("tiến trình giọng đọc không trả lời" if not cancelled else "dừng giọng đọc quá lâu")
                    self.cond.wait(0.2)
                ans = self.answers.pop(rid)
        finally:
            cancel.unlink(missing_ok=True)
        if ans.get("cancelled"):
            raise Stopped("Đã dừng theo yêu cầu")
        if not ans.get("ok"):
            raise VoiceServerError(str(ans.get("error") or "VieNeu lỗi"))
        return ans

    def close(self) -> None:
        try:
            self.send({"op": "quit", "id": "quit"})
            self.proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        if self.alive():
            from flowboard.services.proc import kill_tree

            kill_tree(self.proc)


_busy = threading.Lock()   # one request at a time (a dub's lines are shared out between the servers inside it)
_guard = threading.Lock()  # the server objects themselves
_servers: list[Optional[_Server]] = []
_last_used = 0.0
_reaper: Optional[threading.Thread] = None

#: lines handed to a server at a time — the servers take the next chunk when done, so a second one that is still
#: loading its model (~20 s) simply joins in later
CHUNK = 3
#: a request this long uses a second server that is loaded already (a line to hear: one is enough)
POOL_FROM_LINES = 6
#: …and starts one that is not: its model load (~20 s of CPU) slows the first server meanwhile, so it pays off only on
#: a long run — measured 15/11, 30 long lines: one server 88.6 s, a second starting cold 72.0 s, both loaded 63.9 s
POOL_START_LINES = 20


def total_ram_gb() -> float:
    """The machine's RAM in GB (0 when unknown)."""
    try:
        if os.name == "nt":
            import ctypes

            class _Mem(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            m = _Mem()
            m.dwLength = ctypes.sizeof(_Mem)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore[attr-defined]
            return m.ullTotalPhys / 1024 ** 3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except (OSError, ValueError, AttributeError):
        return 0.0


def pool_size() -> int:
    """How many VieNeu servers a long request may use. Measured 15/11 (Ryzen 7 5800H, 16 threads): 8 lines 16.8 s with
    one, 11.3 s with two, 9.8 s with three; a loaded server holds ~1.7 GB of RAM — two on a machine with 8+ threads and
    16 GB, one otherwise. ``FLOWBOARD_VOICE_POOL`` sets it."""
    env = os.environ.get("FLOWBOARD_VOICE_POOL")
    if env and env.isdigit():
        return max(1, min(4, int(env)))
    return 2 if (os.cpu_count() or 1) >= 8 and total_ram_gb() >= 15 else 1


def _command() -> Optional[tuple[list[str], dict[str, str], Path]]:
    """``(cmd, env, cwd)`` of the server — the same runtime the one-shot runner uses (VieDub or the add-on)."""
    from flowboard.services import dub, dub_addon

    rt = dub_addon.runtime()
    if rt is None:
        return None
    root, python, extra = rt
    env = dub_addon.clean_env(FLOWBOARD_ERASE_ROOT=str(root), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", **extra)
    return [str(python), str(dub.RUNNER_PATH), "serve"], env, root


def _ensure(k: int = 0) -> _Server:
    """Server ``k``, started (or started again: the runtime changed, it died) when needed. Under ``_guard``."""
    global _reaper
    cmd = _command()
    if cmd is None:
        from flowboard.services.dub import NO_RUNTIME

        raise VoiceServerError(NO_RUNTIME)
    while len(_servers) <= k:
        _servers.append(None)
    srv = _servers[k]
    if srv is not None and (not srv.alive() or srv.cmd != cmd[0]):
        srv.close()
        srv = _servers[k] = None
    if srv is None:
        logger.info("voice_server: starting VieNeu #%d (%s)", k + 1, cmd[0][0])
        srv = _servers[k] = _Server(*cmd)
    if _reaper is None or not _reaper.is_alive():
        _reaper = threading.Thread(target=_reap, name="voice-server-idle", daemon=True)
        _reaper.start()
    return srv


def _reap() -> None:
    """Stops the servers after IDLE_S without a request; ends once there is none."""
    while True:
        time.sleep(min(30.0, max(1.0, IDLE_S / 4)))
        with _guard:
            if not any(_servers):
                return
        if _busy.acquire(blocking=False):
            try:
                if time.time() - _last_used > IDLE_S:
                    logger.info("voice_server: idle for %.0f s — stopping", IDLE_S)
                    shutdown()
                    return
            finally:
                _busy.release()


def running() -> bool:
    with _guard:
        return any(s is not None and s.alive() for s in _servers)


def _first() -> Optional[_Server]:
    return _servers[0] if _servers else None


def speak(voice: str, items: list[dict[str, str]], *, progress: Optional[Callable[[int, int], None]] = None,
          stop: Optional[Callable[[], bool]] = None, timeout: Optional[float] = None,
          run_lines: Optional[int] = None) -> dict[str, Any]:
    """Read ``items`` (``[{"text", "out"}]``) with ``voice`` (a VieNeu name, or ``@<voice.json>`` for a cloned one).
    → ``{"done", "missing", "servers"}`` like the one-shot runner (``missing`` = 1-based line numbers). A long request
    is shared out in chunks between ``pool_size()`` servers; ``run_lines`` = the whole run this request is a batch of
    (a dub read 8 lines at a time) — what decides whether starting a second server pays off. ``Busy`` when another
    request is being read."""
    global _last_used
    if not _busy.acquire(blocking=False):
        raise Busy("tiến trình giọng đọc đang bận")
    try:
        n = pool_size() if len(items) >= POOL_FROM_LINES else 1
        if n > 1 and max(len(items), run_lines or 0) < POOL_START_LINES:
            with _guard:  # a shorter run only uses the extra servers already loaded
                n = 1 + sum(1 for s in _servers[1:n] if s is not None and s.alive() and s.loaded)
        chunks = [(i, items[i:i + CHUNK]) for i in range(0, len(items), CHUNK)] if n > 1 else [(0, items)]
        lock = threading.Lock()
        done_by: dict[int, int] = {}
        missing: list[int] = []
        errors: list[BaseException] = []
        used: set[int] = set()
        total = {"done": 0}

        def note(start: int, k: int) -> None:
            with lock:
                done_by[start] = k
                count = sum(done_by.values())
            if progress is not None:
                progress(count, len(items))

        def work(k: int) -> None:
            try:
                with _guard:
                    srv = _ensure(k)
                if not srv.loaded:
                    srv.ask({"op": "load", "id": uuid.uuid4().hex[:10]}, LOAD_TIMEOUT_S, stop)
                    srv.loaded = True
            except VoiceServerError as exc:
                if k == 0:
                    errors.append(exc)
                else:  # the second server could not start (memory…): the first one reads everything
                    logger.warning("voice_server: server #%d unavailable: %s", k + 1, exc)
                return
            while True:
                with lock:
                    if errors or not chunks:
                        return
                    start, part = chunks.pop(0)
                rid = uuid.uuid4().hex[:10]
                srv.progress[rid] = lambda a, _b, s=start: note(s, a)
                try:
                    ans = srv.ask({"op": "speak", "id": rid, "voice": voice, "lines": part},
                                  timeout or max(600.0, 30.0 * len(part)), stop)
                except BaseException as exc:  # noqa: BLE001 — reported below; the other workers stop taking chunks
                    with lock:
                        errors.append(exc)
                    return
                finally:
                    srv.progress.pop(rid, None)
                with lock:
                    used.add(k)
                    total["done"] += int(ans.get("done") or 0)
                    missing.extend(start + int(m) for m in ans.get("missing") or [] if str(m).isdigit())

        workers = [threading.Thread(target=work, args=(k,), name=f"voice-server-work-{k}", daemon=True) for k in range(n)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        _last_used = time.time()
        if errors:
            stopped = next((e for e in errors if isinstance(e, Stopped)), None)
            raise stopped or errors[0]
        if chunks:  # nobody could take them (no server came up)
            raise VoiceServerError("không khởi động được tiến trình giọng đọc")
        return {"ok": True, "done": total["done"], "missing": sorted(missing), "servers": len(used)}
    finally:
        _busy.release()


def warm() -> bool:
    """Start the first server and load the model in the background, so the next line is read at once.
    False when it cannot (no runtime); True when it is warm or warming (busy = in use = warm)."""
    if not enabled() or _command() is None:
        return False
    first = _first()
    if first is not None and first.alive() and first.loaded:
        global _last_used
        _last_used = time.time()
        return True

    def run() -> None:
        global _last_used
        if not _busy.acquire(blocking=False):
            return
        try:
            with _guard:
                srv = _ensure(0)
            if not srv.loaded:
                srv.ask({"op": "load", "id": uuid.uuid4().hex[:10]}, LOAD_TIMEOUT_S)
                srv.loaded = True
            _last_used = time.time()
        except VoiceServerError as exc:
            logger.warning("voice_server: warm-up failed: %s", exc)
        finally:
            _busy.release()

    threading.Thread(target=run, name="voice-server-warm", daemon=True).start()
    return True


def shutdown() -> None:
    """Stop the servers (agent exit, the add-on removed, idle)."""
    with _guard:
        olds = [s for s in _servers if s is not None]
        _servers.clear()
    for srv in olds:
        srv.close()


atexit.register(shutdown)
