"""The "gói lồng tiếng": one click installs what dubbing needs on a machine without VieDub.

The installed app (191 MB) carries no speech AI. Dubbing, "chỉ chèn phụ đề", cutting by the words and the VieNeu
voices all run ``dub_runner.py`` inside a Python that has faster-whisper / sherpa-onnx / vieneu — until now only the
home machine had one (VieDub's ``.venv``). This module builds that Python next to the user's data:

    <DFlowData>/addons/dub/
        uv/uv.exe                  uv itself (its wheel from PyPI)
        python/                    the interpreter uv downloads (python-build-standalone)
        .venv/                     faster-whisper, ctranslate2, sherpa-onnx, vieneu, rapidocr (+ cuBLAS / cuDNN wheels
                                   when an NVIDIA card is there — Whisper on the card without torch)
        models/<WHISPER_DIR>/      Whisper large-v3-turbo (CTranslate2, ~1.6 GB from HuggingFace)
        models/onnx/               spleeter vocals / accompaniment (music kept under the Vietnamese voice)
        hf/                        HF_HOME of the runner (VieNeu fetches its model here, not in the user profile on C:)
        addon.json                 written last: what was installed, and whether Whisper ran on the card

Everything comes from public mirrors (PyPI, GitHub via uv, HuggingFace) — no server of ours. Downloads resume after
a failure or a restart (``.part`` files, uv's cache), so "Thử lại" continues where it stopped. AI subtitle erasing
(LaMa, needs torch ~8 GB) is not part of it.
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
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from flowboard import config

logger = logging.getLogger(__name__)

ADDON_VERSION = 1
UV_VERSION = "0.13.2"
PYTHON_VERSION = "3.11"
#: same folder name dub_runner looks for under ``<root>/models``
WHISPER_DIR = "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
WHISPER_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
WHISPER_FILES = ("config.json", "preprocessor_config.json", "tokenizer.json", "vocabulary.json", "model.bin")
HF_HOSTS = ("https://huggingface.co", "https://hf-mirror.com")
SPLEETER_FILES = ("vocals.fp16.onnx", "accompaniment.fp16.onnx")
SPLEETER_URLS = ("https://huggingface.co/mortimerme/repocollect/resolve/main/onnx/{}",
                 "https://www.modelscope.cn/models/himyworld/videotrans/resolve/master/onnx/{}")
#: the versions VieDub runs on the home machine (known to work together)
PACKAGES = ["faster-whisper==1.2.1", "ctranslate2==4.8.0", "sherpa-onnx==1.13.0", "vieneu==3.8.3",
            "rapidocr-onnxruntime==1.4.4", "zhconv==1.4.3", "soundfile", "numpy"]
#: CUDA 12 libraries for ctranslate2 4.8 (cuBLAS 12 + cuDNN 9) — the ones torch 2.8 / cu128 ships
GPU_WHEELS = (("nvidia-cudnn-cu12", "9.10.2.21"), ("nvidia-cublas-cu12", "12.8.4.1"))
#: rough download sizes (MB) for the progress bar and the "tải khoảng …" line
#: The Microsoft Visual C++ 2015–2022 runtime (x64). ctranslate2.dll and onnxruntime load MSVCP140.dll,
#: VCRUNTIME140.dll and VCRUNTIME140_1.dll from System32 — the Python uv downloads does not carry MSVCP140 — and Windows
#: does not always have them (a fresh install, or only the 2015 / 2017 runtime, without VCRUNTIME140_1). Then importing
#: faster_whisper fails with "Could not find module …\ctranslate2.dll (or one of its dependencies)" (a friend's
#: machine, 10/11). Microsoft's own installer, checked for its signature, run once with the user's go-ahead (UAC).
VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
VC_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")
#: vc_redist exit codes that mean the runtime is there: done / a newer or the same one already in / done, restart later
VC_OK_CODES = (0, 1638, 3010, 1641)
#: what a job does first: load every native library of the add-on (a missing one is not a DLL problem)
PROBE = (
    "import importlib\n"
    "bad = []\n"
    "for name in ('ctranslate2', 'onnxruntime', 'sherpa_onnx'):\n"
    "    try:\n"
    "        importlib.import_module(name)\n"
    "    except ModuleNotFoundError:\n"
    "        pass\n"
    "    except BaseException as exc:\n"
    "        bad.append(f'{name}: {exc}')\n"
    "print(' | '.join(bad) or 'ok')\n"
)
SIZE_MB = {"uv": 16, "python": 30, "gpu": 1261, "packages": 330, "whisper": 1620, "spleeter": 40, "vieneu": 600}
#: free space asked for before starting (the venv unpacks bigger than its downloads)
NEED_FREE_MB = {True: 9000, False: 5000}
#: CUDA 12 needs an R528+ driver on Windows
MIN_DRIVER = 528

DownloadHook = Callable[[int], None]


class AddonError(RuntimeError):
    pass


class _Cancelled(Exception):
    pass


# ── where it lives ─────────────────────────────────────────────────────────

def addon_dir() -> Path:
    """``<DFlowData>/addons/dub`` in the app, ``<repo>/addons/dub`` from a checkout. Not ``config.STORAGE_DIR``
    (that one moves to the account's folder on login)."""
    custom = os.getenv("FLOWBOARD_DUB_ADDON_DIR")
    if custom:
        return Path(custom)
    return (config.HOME or config.ROOT) / "addons" / "dub"


def venv_python(root: Optional[Path] = None) -> Path:
    root = root or addon_dir()
    return root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def info() -> dict[str, Any]:
    try:
        data = json.loads((addon_dir() / "addon.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def ready() -> bool:
    """Installed and complete: ``addon.json`` is only written once every step passed."""
    root = addon_dir()
    return (bool(info().get("version")) and venv_python(root).is_file()
            and (root / "models" / WHISPER_DIR / "model.bin").is_file())


def runtime() -> Optional[tuple[Path, Path, dict[str, str]]]:
    """``(root, python, extra env)`` that ``dub_runner.py`` runs with, or None.

    A VieDub set in Cài đặt → 🖥 Máy này (or the home machine's ``D:\\codes\\pyvideotrans``) wins — it also has the
    torch / LaMa pieces; otherwise the add-on."""
    from flowboard.services.video_clean import erase_python, erase_root

    python = erase_python()
    if python is not None:
        return erase_root(), python, {}
    if ready():
        root = addon_dir()
        return root, venv_python(root), {"HF_HOME": str(root / "hf"), "HF_HUB_DISABLE_TELEMETRY": "1"}
    return None


# ── the machine ────────────────────────────────────────────────────────────

_gpu_cache: dict[str, Any] = {"at": 0.0, "value": None}


def nvidia_gpu(refresh: bool = False) -> Optional[dict[str, Any]]:
    """``{name, driver, vram_mb, old_driver}`` from nvidia-smi (comes with the NVIDIA driver), None without a card."""
    if not refresh and time.time() - _gpu_cache["at"] < 600:
        return _gpu_cache["value"]
    value: Optional[dict[str, Any]] = None
    exe = shutil.which("nvidia-smi")
    if exe is None and sys.platform == "win32":
        guess = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
        exe = str(guess) if guess.is_file() else None
    if exe:
        try:
            out = subprocess.run([exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10)
            line = (out.stdout or "").strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2 and parts[0]:
                try:
                    major = int(parts[1].split(".")[0])
                except ValueError:
                    major = 0
                vram = int(float(parts[2])) if len(parts) > 2 and parts[2].replace(".", "", 1).isdigit() else 0
                value = {"name": parts[0], "driver": parts[1], "vram_mb": vram,
                         "old_driver": sys.platform == "win32" and 0 < major < MIN_DRIVER}
        except (OSError, subprocess.SubprocessError, IndexError):
            value = None
    _gpu_cache.update(at=time.time(), value=value)
    return value


def _free_mb(path: Path) -> int:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return int(shutil.disk_usage(probe).free / (1 << 20))
    except OSError:
        return 0


def _dir_mb(path: Path) -> int:
    total = 0
    if path.is_dir():
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return int(total / (1 << 20))


def plan_mb(gpu: bool) -> int:
    return sum(v for k, v in SIZE_MB.items() if gpu or k != "gpu")


# ── state ──────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_stop = threading.Event()
_proc: dict[str, Optional[subprocess.Popen]] = {"p": None}
_state: dict[str, Any] = {"running": False, "phase": "", "done_mb": 0, "total_mb": 0, "error": "",
                          "started_at": None, "finished_at": None, "last": ""}


def _set(**kw: Any) -> None:
    with _lock:
        _state.update(kw)


def progress() -> int:
    with _lock:
        total = _state["total_mb"] or 1
        return max(0, min(99 if _state["running"] else 100, int(100 * _state["done_mb"] / total)))


def status() -> dict[str, Any]:
    root = addon_dir()
    gpu = nvidia_gpu()
    with _lock:
        st = dict(_state)
    want_gpu = bool(gpu)
    out: dict[str, Any] = {
        "supported": sys.platform in ("win32", "linux"),
        "installed": ready(),
        "info": info(),
        "dir": str(root),
        "gpu": gpu,
        "download_mb": plan_mb(want_gpu),
        "need_mb": NEED_FREE_MB[want_gpu],
        "free_mb": _free_mb(root),
        **st,
        "progress": progress() if st["running"] or st["done_mb"] else 0,
    }
    if out["installed"]:
        out["size_mb"] = int(out["info"].get("size_mb") or 0)  # measured once at the end of the install (walking .venv takes seconds)
    return out


def running_item() -> Optional[dict[str, Any]]:
    with _lock:
        if not _state["running"]:
            return None
        phase, started = _state["phase"], _state["started_at"]
    return {"key": "dubaddon:install", "kind": "addon", "title": "Đang cài gói lồng tiếng", "detail": phase,
            "progress": progress(), "started_at": started, "link": "/tools/dub"}


def outcome() -> dict[str, Any]:
    with _lock:
        err = _state["error"]
    if err:
        return {"ok": False, "message": err}
    return {"ok": True, "message": "Đã cài xong gói lồng tiếng — giờ lồng tiếng được trên máy này"}


# ── downloads ──────────────────────────────────────────────────────────────

def _client() -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0),
                        headers={"User-Agent": "DFlow (dub add-on)"})


def download(urls: list[str] | tuple[str, ...], dest: Path, on_bytes: Optional[DownloadHook] = None,
             expect: int = 0, attempts: int = 4) -> Path:
    """Fetch ``dest`` from the first of ``urls`` that works, resuming a ``.part`` left by an earlier try.
    ``on_bytes(n)`` is told every chunk received (for the progress bar). A file already in place is kept."""
    if dest.is_file() and (not expect or dest.stat().st_size == expect):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    last: Exception | None = None
    with _client() as client:
        for url in urls:
            for attempt in range(attempts):
                if _stop.is_set():
                    raise _Cancelled()
                have = part.stat().st_size if part.is_file() else 0
                headers = {"Range": f"bytes={have}-"} if have else {}
                try:
                    with client.stream("GET", url, headers=headers) as r:
                        if r.status_code == 416 and have:  # the part is already whole
                            break
                        if r.status_code not in (200, 206):
                            raise AddonError(f"{r.status_code} khi tải {url.split('?')[0]}")
                        if r.status_code == 200 and have:  # server ignored the range: start over
                            have = 0
                        total = 0
                        rng = r.headers.get("content-range", "")
                        if "/" in rng and rng.rsplit("/", 1)[1].isdigit():
                            total = int(rng.rsplit("/", 1)[1])
                        elif r.headers.get("content-length", "").isdigit():
                            total = have + int(r.headers["content-length"])
                        with open(part, "ab" if have else "wb") as fh:
                            for chunk in r.iter_bytes(1 << 20):
                                if _stop.is_set():
                                    raise _Cancelled()
                                fh.write(chunk)
                                if on_bytes:
                                    on_bytes(len(chunk))
                    size = part.stat().st_size
                    want = expect or total
                    if want and size != want:
                        if size > want:
                            part.unlink(missing_ok=True)
                        raise AddonError(f"tải chưa đủ {dest.name} ({size}/{want} byte)")
                    break
                except _Cancelled:
                    raise
                except (httpx.HTTPError, OSError, AddonError) as exc:
                    last = exc
                    logger.warning("dub add-on: %s (%s, lần %d)", exc, url.split("?")[0], attempt + 1)
                    time.sleep(min(20, 2 * (attempt + 1)))
            else:
                continue  # every attempt at this url failed → next mirror
            os.replace(part, dest)
            return dest
    raise AddonError(f"Không tải được {dest.name}: {last}")


def pypi_wheel(name: str, version: str, platform_tag: str) -> tuple[str, int, str]:
    """``(url, size, filename)`` of the wheel of ``name==version`` for this platform (from PyPI's JSON API)."""
    with _client() as client:
        r = client.get(f"https://pypi.org/pypi/{name}/{version}/json")
        r.raise_for_status()
        for f in r.json().get("urls", []):
            fn = f.get("filename", "")
            if fn.endswith(".whl") and platform_tag in fn and ("win" in platform_tag or "x86_64" in fn):
                return f["url"], int(f.get("size") or 0), fn
    raise AddonError(f"PyPI không có bản {name} {version} cho máy này")


def _wheel_tag() -> str:
    return "win_amd64" if sys.platform == "win32" else "manylinux"


# ── the steps ──────────────────────────────────────────────────────────────

class _Meter:
    """Adds downloaded MB to the shared progress, counting a step's planned size at most once."""

    def __init__(self, base_mb: int, cap_mb: int) -> None:
        self.base, self.cap, self.bytes = base_mb, cap_mb, 0

    def __call__(self, n: int) -> None:
        self.bytes += n
        _set(done_mb=self.base + min(self.cap, int(self.bytes / (1 << 20))))


def _watch_dir(path: Path, base_mb: int, cap_mb: int, done: threading.Event, start_mb: int = 0) -> threading.Thread:
    """Progress for steps we cannot hook (uv, VieNeu's own download): how much the folder grew."""

    def loop() -> None:
        while not done.wait(2.0):
            grown = max(0, _dir_mb(path) - start_mb)
            _set(done_mb=base_mb + min(cap_mb, grown))

    t = threading.Thread(target=loop, name="dub-addon-watch", daemon=True)
    t.start()
    return t


def clean_env(**extra: str) -> dict[str, str]:
    """The agent's environment for a child Python, without what could point it at the app's own interpreter."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV")}
    env.update(extra)
    return env


def _uv_env(root: Path) -> dict[str, str]:
    return clean_env(UV_PYTHON_INSTALL_DIR=str(root / "python"), UV_CACHE_DIR=str(root / "uv-cache"),
                UV_PYTHON_PREFERENCE="only-managed", UV_NO_PROGRESS="1", UV_HTTP_TIMEOUT="180",
                UV_HTTP_RETRIES="5", UV_CONCURRENT_DOWNLOADS="4", PYTHONUTF8="1")


def _run(cmd: list[str], root: Path, env: Optional[dict[str, str]] = None, timeout: int = 3600) -> str:
    """Run one command of the install, killable by "Huỷ". Returns its output; raises with the last lines on failure."""
    if _stop.is_set():
        raise _Cancelled()
    logger.info("dub add-on: %s", " ".join(cmd[:4]))
    proc = subprocess.Popen(cmd, cwd=str(root), env=env or _uv_env(root), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    _proc["p"] = proc
    lines: list[str] = []
    deadline = time.time() + timeout

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                lines.append(line)
                _set(last=line[-200:])

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        while proc.poll() is None:
            if _stop.is_set():
                proc.kill()
                raise _Cancelled()
            if time.time() > deadline:
                proc.kill()
                raise AddonError("quá lâu, đã dừng: " + " ".join(cmd[1:3]))
            time.sleep(0.4)
        reader.join(timeout=5)
    finally:
        _proc["p"] = None
    text = "\n".join(lines)
    if proc.returncode != 0:
        tail = " / ".join(lines[-4:])[-600:]
        raise AddonError(tail or f"thoát mã {proc.returncode}")
    return text


def _system32() -> Path:
    return Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32"


def vc_runtime_missing() -> list[str]:
    """The Visual C++ runtime DLLs this Windows lacks (empty elsewhere / when all are there)."""
    if sys.platform != "win32":
        return []
    return [name for name in VC_DLLS if not (_system32() / name).is_file()]


def dll_problem(text: str) -> bool:
    """A library that would not load because a DLL it needs is missing / too old (Windows error 126 / 127)."""
    t = (text or "").lower()
    return any(k in t for k in ("could not find module", "dll load failed", "winerror 126", "winerror 127",
                                "specified module could not be found", "specified procedure could not be found",
                                "msvcp140", "vcruntime140"))


def _powershell(script: str, root: Path, timeout: int, **env: str) -> str:
    exe = _system32() / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return _run([str(exe) if exe.is_file() else "powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-Command", script], root, env=clean_env(**env), timeout=timeout)


def _install_vc_runtime(root: Path) -> None:
    """Download Microsoft's vc_redist.x64.exe, make sure Microsoft signed it, and run it elevated (one UAC prompt)."""
    if sys.platform != "win32":
        return
    _set(phase="Cài Microsoft Visual C++ Runtime (thư viện Windows mà AI cần) — Windows sẽ hỏi quyền: bấm Yes / Có. "
               "Không thấy hộp thoại thì nhìn thanh taskbar")
    exe = download([VC_REDIST_URL], root / "downloads" / "vc_redist.x64.exe")
    signed = _powershell("$s = Get-AuthenticodeSignature -LiteralPath $env:DFLOW_VC; "
                         "Write-Output ('SIG ' + $s.Status + ' ' + $s.SignerCertificate.Subject)",
                         root, 120, DFLOW_VC=str(exe))
    sig = next((ln for ln in signed.splitlines() if ln.startswith("SIG ")), "")
    if not sig.startswith("SIG Valid") or "O=Microsoft Corporation" not in sig:
        exe.unlink(missing_ok=True)
        raise AddonError("Bộ cài Visual C++ Runtime tải về không có chữ ký của Microsoft — đã bỏ. Thử lại sau, hoặc tự cài "
                         f"từ {VC_REDIST_URL}")
    out = _powershell("try { $p = Start-Process -FilePath $env:DFLOW_VC -ArgumentList '/install','/quiet','/norestart' "
                      "-Verb RunAs -Wait -PassThru; Write-Output ('EXIT ' + $p.ExitCode) } "
                      "catch { Write-Output ('FAIL ' + $_.Exception.Message) }",
                      root, 1200, DFLOW_VC=str(exe))
    line = next((ln for ln in reversed(out.splitlines()) if ln.startswith(("EXIT ", "FAIL "))), "")
    if line.startswith("EXIT ") and line[5:].strip().lstrip("-").isdigit() and int(line[5:]) in VC_OK_CODES:
        logger.info("dub add-on: Visual C++ runtime installed (%s)", line)
        return
    if line.startswith("FAIL ") and "cancel" in line.lower():
        raise AddonError("Bạn đã bấm Không (No) ở hộp thoại của Windows nên chưa cài được Visual C++ Runtime — bấm Cài lại "
                         f"và chọn Yes / Có, hoặc tự cài từ {VC_REDIST_URL} rồi bấm Cài lại.")
    raise AddonError(f"Cài Visual C++ Runtime không xong ({(line or out)[-200:]}) — tự cài từ {VC_REDIST_URL} rồi bấm Cài lại.")


def _probe(root: Path, python: Path) -> str:
    """'' when every native library of the add-on loads in its Python; else what failed."""
    try:
        out = _run([str(python), "-c", PROBE], root, env=clean_env(PYTHONIOENCODING="utf-8"), timeout=300)
    except AddonError as exc:
        return str(exc) or "Python của gói không chạy"
    last = next((ln.strip() for ln in reversed(out.splitlines()) if ln.strip()), "")
    return "" if last == "ok" else (last or "Python của gói không chạy")


def _ensure_libraries_load(root: Path, python: Path) -> None:
    """Right after the libraries are installed (before the 1.6 GB of Whisper): load them like a job will. A DLL problem
    on Windows gets the Visual C++ runtime installed, then one more try."""
    problem = _probe(root, python)
    if problem and dll_problem(problem) and sys.platform == "win32":
        logger.warning("dub add-on: libraries do not load (%s) — installing the Visual C++ runtime", problem)
        _install_vc_runtime(root)
        problem = _probe(root, python)
    if problem:
        raise AddonError(load_failure(problem))


def load_failure(problem: str) -> str:
    """What to tell the user when the add-on's libraries do not load."""
    msg = f"Thư viện AI của gói không nạp được trên máy này: {problem[:300]}"
    if dll_problem(problem) and sys.platform == "win32":
        msg += (f" — Cài (hoặc cài lại) Microsoft Visual C++ Runtime từ {VC_REDIST_URL} rồi bấm Cài lại. Vẫn lỗi thì phần "
                "mềm diệt virus có thể đã xoá file: thêm thư mục gói vào danh sách loại trừ rồi Gỡ gói và cài lại.")
    return msg


def _ensure_uv(root: Path) -> Path:
    exe = root / "uv" / ("uv.exe" if sys.platform == "win32" else "uv")
    if exe.is_file():
        return exe
    url, size, fn = pypi_wheel("uv", UV_VERSION, "win_amd64" if sys.platform == "win32" else "manylinux_2_17_x86_64")
    wheel = download([url], root / "downloads" / fn, _Meter(0, SIZE_MB["uv"]), expect=size)
    want = exe.name
    with zipfile.ZipFile(wheel) as zf:
        member = next((m for m in zf.namelist() if m.endswith("/scripts/" + want)), None)
        if member is None:
            raise AddonError("gói uv không có " + want)
        exe.parent.mkdir(parents=True, exist_ok=True)
        tmp = exe.with_suffix(exe.suffix + ".part")
        with zf.open(member) as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        os.replace(tmp, exe)
    if sys.platform != "win32":
        exe.chmod(0o755)
    return exe


def _check(root: Path, python: Path) -> dict[str, Any]:
    """Load Whisper the way a dub job will (on the card when there is one) and report what happened."""
    from flowboard.services.dub import RUNNER_PATH  # dub_runner.py, shipped as a real file

    env = clean_env(FLOWBOARD_ERASE_ROOT=str(root), HF_HOME=str(root / "hf"), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    out = _run([str(python), str(RUNNER_PATH), "check"], root, env=env, timeout=900)
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    raise AddonError("kiểm tra sau khi cài không trả kết quả")


def _warm_vieneu(root: Path, python: Path, base_mb: int) -> str:
    """Fetch VieNeu's model now (it would otherwise download in the middle of the first job). Not fatal."""
    from flowboard.services.dub import RUNNER_PATH

    hf = root / "hf"
    hf.mkdir(parents=True, exist_ok=True)
    wav = root / "downloads" / "vieneu-test.wav"
    lines = root / "downloads" / "vieneu-test.json"
    lines.write_text(json.dumps([{"text": "Xin chào.", "out": str(wav)}], ensure_ascii=False), encoding="utf-8")
    env = clean_env(FLOWBOARD_ERASE_ROOT=str(root), HF_HOME=str(hf), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    done = threading.Event()
    _watch_dir(hf, base_mb, SIZE_MB["vieneu"], done, start_mb=_dir_mb(hf))
    try:
        _run([str(python), str(RUNNER_PATH), "vieneu", "Ngọc Huyền", str(lines)], root, env=env, timeout=1800)
        return ""
    except AddonError as exc:
        logger.warning("dub add-on: VieNeu warm-up failed: %s", exc)
        return f"giọng VieNeu sẽ tải ở lần dùng đầu ({str(exc)[:160]})"
    finally:
        done.set()


def _install(gpu: Optional[dict[str, Any]]) -> None:
    root = addon_dir()
    use_gpu = bool(gpu)
    root.mkdir(parents=True, exist_ok=True)
    (root / "addon.json").unlink(missing_ok=True)  # not ready until every step passes again
    free = _free_mb(root)
    if free and free < NEED_FREE_MB[use_gpu]:
        raise AddonError(f"Ổ đĩa chứa {root} chỉ còn {free / 1024:.1f} GB — gói lồng tiếng cần trống khoảng "
                         f"{NEED_FREE_MB[use_gpu] / 1024:.0f} GB. Dọn bớt rồi thử lại.")
    total = plan_mb(use_gpu)
    _set(total_mb=total, done_mb=0)
    base = 0

    if vc_runtime_missing():  # ask for it now, while the user is watching, not after an hour of downloads
        _install_vc_runtime(root)

    _set(phase="Tải uv (bộ cài thư viện Python)")
    uv = _ensure_uv(root)
    base += SIZE_MB["uv"]
    _set(done_mb=base)

    _set(phase=f"Tải Python {PYTHON_VERSION}")
    python = venv_python(root)
    if not python.is_file():
        done = threading.Event()
        _watch_dir(root / "python", base, SIZE_MB["python"], done)
        try:
            _run([str(uv), "venv", str(root / ".venv"), "--python", PYTHON_VERSION, "--allow-existing"], root, timeout=1800)
        finally:
            done.set()
    base += SIZE_MB["python"]
    _set(done_mb=base)

    wheels: list[str] = []
    if use_gpu:
        _set(phase="Tải thư viện card NVIDIA (cuBLAS + cuDNN, ~1,3 GB)")
        meter = _Meter(base, SIZE_MB["gpu"])
        for name, version in GPU_WHEELS:
            url, size, fn = pypi_wheel(name, version, _wheel_tag())
            wheels.append(str(download([url], root / "downloads" / fn, meter, expect=size)))
        base += SIZE_MB["gpu"]
        _set(done_mb=base)

    _set(phase="Cài thư viện AI (faster-whisper, sherpa-onnx, VieNeu…)")
    done = threading.Event()
    cache = root / "uv-cache"
    _watch_dir(cache, base, SIZE_MB["packages"], done, start_mb=_dir_mb(cache))
    try:
        _run([str(uv), "pip", "install", "--python", str(python), *wheels, *PACKAGES], root, timeout=3600)
    finally:
        done.set()
    base += SIZE_MB["packages"]
    _set(done_mb=base)

    _set(phase="Kiểm tra thư viện AI nạp được trên máy này")
    _ensure_libraries_load(root, python)

    _set(phase="Tải mô hình Whisper large-v3-turbo (~1,6 GB)")
    meter = _Meter(base, SIZE_MB["whisper"])
    wdir = root / "models" / WHISPER_DIR
    for name in WHISPER_FILES:
        download([f"{h}/{WHISPER_REPO}/resolve/main/{name}" for h in HF_HOSTS], wdir / name, meter)
    base += SIZE_MB["whisper"]
    _set(done_mb=base)

    _set(phase="Tải mô hình tách nhạc nền")
    meter = _Meter(base, SIZE_MB["spleeter"])
    for name in SPLEETER_FILES:
        download([u.format(name) for u in SPLEETER_URLS], root / "models" / "onnx" / name, meter)
    base += SIZE_MB["spleeter"]
    _set(done_mb=base)

    _set(phase="Tải giọng VieNeu (~600 MB)")
    note = _warm_vieneu(root, python, base)
    base += SIZE_MB["vieneu"]
    _set(done_mb=base)

    _set(phase="Kiểm tra Whisper chạy được" + (" trên card NVIDIA" if use_gpu else ""))
    check = _check(root, python)
    if not check.get("ok"):
        error = check.get("error") or "Whisper không chạy được sau khi cài"
        raise AddonError(load_failure(error) if dll_problem(error) else error)

    data = {"version": ADDON_VERSION, "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "gpu": gpu,
            "device": check.get("device"), "cuda": bool(check.get("cuda")), "cuda_error": check.get("cuda_error") or "",
            "vieneu": not note, "note": note, "python": PYTHON_VERSION, "packages": PACKAGES,
            "gpu_wheels": [f"{n}=={v}" for n, v in GPU_WHEELS] if use_gpu else []}
    # downloads and uv's cache are only needed while installing
    shutil.rmtree(root / "downloads", ignore_errors=True)
    shutil.rmtree(cache, ignore_errors=True)
    data["size_mb"] = _dir_mb(root)
    tmp = root / "addon.json.part"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, root / "addon.json")
    _set(done_mb=total)


def _worker(gpu: Optional[dict[str, Any]]) -> None:
    try:
        _install(gpu)
        _set(error="", phase="Đã cài xong")
    except _Cancelled:
        _set(error="Đã huỷ — bấm Cài lại để tải tiếp chỗ dở", phase="Đã huỷ")
    except Exception as exc:  # noqa: BLE001 — every failure ends up on the card
        logger.exception("dub add-on install failed")
        msg = str(exc) or exc.__class__.__name__
        _set(error=f"Cài gói lồng tiếng lỗi: {msg[:500]}", phase="Lỗi")
    finally:
        _set(running=False, finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"))


def install() -> dict[str, Any]:
    if sys.platform not in ("win32", "linux"):
        raise AddonError("Gói lồng tiếng chỉ có cho Windows (và Linux).")
    with _lock:
        if _state["running"]:
            return dict(_state)
        _stop.clear()
        _state.update(running=True, error="", phase="Bắt đầu", done_mb=0, last="",
                      started_at=time.strftime("%Y-%m-%dT%H:%M:%S"), finished_at=None)
    gpu = nvidia_gpu(refresh=True)
    threading.Thread(target=_worker, args=(gpu,), name="dub-addon-install", daemon=True).start()
    return status()


def cancel() -> None:
    _stop.set()
    p = _proc["p"]
    if p is not None and p.poll() is None:
        try:
            p.kill()
        except OSError:
            pass


def remove() -> None:
    with _lock:
        if _state["running"]:
            raise AddonError("Đang cài — huỷ trước rồi gỡ.")
    root = addon_dir()
    if not root.is_dir():
        return
    if root.name != "dub" or root.parent.name != "addons":
        raise AddonError(f"Không gỡ thư mục lạ: {root}")
    shutil.rmtree(root, ignore_errors=True)
    _set(error="", phase="", done_mb=0, total_mb=0)
