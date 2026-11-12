"""The "Gói Remotion": one click installs the second subtitle engine on a machine without the repo's ``frontend/``.

The Remotion engine (``services/dub_remotion``) runs ``frontend/remotion/render.mjs`` with Node next to the Remotion
packages of ``frontend/node_modules``. The installed app has neither (the web UI is shipped already built), so every
machine that installed DFlow from the .exe saw "Remotion · … (chưa dùng được)". This module builds the same thing next
to the user's data:

    <DFlowData>/addons/remotion/
        node/                     a portable Node.js (the official zip / tar.xz from nodejs.org, SHA-256 checked)
        app/package.json          only the Remotion + React packages, the exact versions the web UI was built with
        app/remotion/render.mjs   the render script and the composition sources, copied from the app (and refreshed
        app/src/remotion/*        before each render, so an app update brings its new subtitle styles along)
        app/node_modules/         npm install of the above, + Chrome Headless Shell (Remotion's own download)
        addon.json                written last: what was installed

Everything comes from public servers (nodejs.org, the npm registry, Google's Chrome for Testing). "Huỷ" stops between
steps and kills npm; "Cài lại" starts over where it can (the Node archive is kept until the end).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Optional

from flowboard import config
from flowboard.services import dub_addon

logger = logging.getLogger(__name__)

ADDON_VERSION = 1
NODE_VERSION = "22.12.0"
#: SHA-256 of the official archives (https://nodejs.org/dist/v22.12.0/SHASUMS256.txt)
NODE_SHA256 = {
    "win32": ("node-v22.12.0-win-x64.zip", "2b8f2256382f97ad51e29ff71f702961af466c4616393f767455501e6aece9b8"),
    "linux": ("node-v22.12.0-linux-x64.tar.xz", "22982235e1b71fa8850f82edd09cdae7e3f32df1764a9ec298c72d25ef2c164f"),
}
NODE_MIRRORS = ("https://nodejs.org/dist/v{v}/{f}", "https://npmmirror.com/mirrors/node/v{v}/{f}")
#: the packages render.mjs and src/remotion import, at the versions of frontend/package.json's lock
REMOTION_VERSION = "4.0.538"
PACKAGES = {
    "remotion": REMOTION_VERSION,
    "@remotion/bundler": REMOTION_VERSION,
    "@remotion/renderer": REMOTION_VERSION,
    "@remotion/google-fonts": REMOTION_VERSION,
    "react": "18.3.1",
    "react-dom": "18.3.1",
}
#: rough sizes for the progress bar (MB)
SIZE_MB = {"node": 35, "packages": 160, "browser": 110, "bundle": 5}
NEED_FREE_MB = 1500  # ~918 MB once installed (measured), + the archive and npm cache while installing


class _Cancelled(Exception):
    pass


# ── where it lives ─────────────────────────────────────────────────────────

def addon_dir() -> Path:
    custom = os.getenv("FLOWBOARD_REMOTION_ADDON_DIR")
    if custom:
        return Path(custom)
    return (config.HOME or config.ROOT) / "addons" / "remotion"


def app_dir(root: Optional[Path] = None) -> Path:
    return (root or addon_dir()) / "app"


def node_exe(root: Optional[Path] = None) -> Path:
    root = root or addon_dir()
    return root / "node" / ("node.exe" if sys.platform == "win32" else "bin/node")


def npm_cli(root: Optional[Path] = None) -> Path:
    root = root or addon_dir()
    base = root / "node" / ("node_modules" if sys.platform == "win32" else "lib/node_modules")
    return base / "npm" / "bin" / "npm-cli.js"


def kit_dir() -> Optional[Path]:
    """Where the app keeps render.mjs + src/remotion: shipped next to the package in the installed app
    (``flowboard/remotion_kit``), the repo's ``frontend/`` when running from a checkout."""
    shipped = Path(__file__).resolve().parent.parent / "remotion_kit"
    if (shipped / "remotion" / "render.mjs").is_file():
        return shipped
    repo = config.ROOT / "frontend"
    if (repo / "remotion" / "render.mjs").is_file():
        return repo
    return None


def info() -> dict[str, Any]:
    try:
        data = json.loads((addon_dir() / "addon.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def ready() -> bool:
    root = addon_dir()
    return (bool(info().get("version")) and node_exe(root).is_file()
            and (app_dir(root) / "node_modules" / "@remotion" / "renderer" / "package.json").is_file())


def sync_sources(root: Optional[Path] = None) -> None:
    """Copy render.mjs and src/remotion from the app into the add-on when they differ (an app update may change the
    subtitle styles; render.mjs rebuilds its bundle when a source file changes)."""
    kit = kit_dir()
    if kit is None:
        raise RuntimeError("Bản app này thiếu mã nguồn phụ đề Remotion (remotion_kit).")
    dst = app_dir(root)
    pairs = [(kit / "remotion" / "render.mjs", dst / "remotion" / "render.mjs")]
    src_dir = kit / "src" / "remotion"
    for f in sorted(src_dir.iterdir()):
        if f.is_file() and f.suffix in (".ts", ".tsx", ".css"):
            pairs.append((f, dst / "src" / "remotion" / f.name))
    wanted = {p[1].name for p in pairs[1:]}
    old_dir = dst / "src" / "remotion"
    if old_dir.is_dir():
        for f in old_dir.iterdir():
            if f.is_file() and f.name not in wanted:
                f.unlink(missing_ok=True)
    for a, b in pairs:
        try:
            if b.is_file() and b.read_bytes() == a.read_bytes():
                continue
        except OSError:
            pass
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(a, b)


def runtime() -> Optional[tuple[str, Path]]:
    """``(node, project dir)`` for render.mjs from the add-on, or None when it is not installed."""
    if not ready():
        return None
    return str(node_exe()), app_dir()


def child_env(root: Optional[Path] = None, **extra: str) -> dict[str, str]:
    """The environment of node / npm: our Node first on PATH (npm's install scripts call ``node``)."""
    root = root or addon_dir()
    env = dict(os.environ)
    bin_dir = node_exe(root).parent
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env.setdefault("REMOTION_DISABLE_TELEMETRY", "1")
    env.update(extra)
    return env


# ── state ──────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_stop = threading.Event()
_proc: dict[str, Optional[subprocess.Popen]] = {"p": None}
_state: dict[str, Any] = {"running": False, "phase": "", "done_mb": 0, "total_mb": 0, "error": "",
                          "started_at": None, "finished_at": None, "last": ""}


def _set(**kw: Any) -> None:
    with _lock:
        _state.update(kw)


def plan_mb() -> int:
    return sum(SIZE_MB.values())


def progress() -> int:
    with _lock:
        total = _state["total_mb"] or plan_mb()
        return max(0, min(99 if _state["running"] else 100, int(100 * _state["done_mb"] / total)))


def status() -> dict[str, Any]:
    root = addon_dir()
    with _lock:
        st = dict(_state)
    out: dict[str, Any] = {
        "supported": sys.platform in NODE_SHA256 and kit_dir() is not None,
        "installed": ready(),
        "info": info(),
        "dir": str(root),
        "download_mb": plan_mb(),
        "need_mb": NEED_FREE_MB,
        "free_mb": dub_addon._free_mb(root),
        **st,
        "progress": progress() if st["running"] or st["done_mb"] else 0,
    }
    if out["installed"]:
        out["size_mb"] = int(out["info"].get("size_mb") or 0)
    return out


def running_item() -> Optional[dict[str, Any]]:
    with _lock:
        if not _state["running"]:
            return None
        phase, started = _state["phase"], _state["started_at"]
    return {"key": "remotionaddon:install", "kind": "addon", "title": "Đang cài gói Remotion", "detail": phase,
            "progress": progress(), "started_at": started, "link": "/tools/dub"}


def outcome() -> dict[str, Any]:
    with _lock:
        err = _state["error"]
    if err:
        return {"ok": False, "message": err}
    return {"ok": True, "message": "Đã cài xong gói Remotion — phụ đề Remotion dùng được trên máy này"}


# ── the steps ──────────────────────────────────────────────────────────────

def _run(cmd: list[str], cwd: Path, env: dict[str, str], timeout: int = 3600,
         on_line: Optional[Any] = None) -> str:
    if _stop.is_set():
        raise _Cancelled()
    logger.info("remotion add-on: %s", " ".join(cmd[:4]))
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0)
    _proc["p"] = proc
    lines: list[str] = []

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                lines.append(line)
                _set(last=line[-200:])
                if on_line:
                    on_line(line)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    deadline = time.time() + timeout
    try:
        while proc.poll() is None:
            if _stop.is_set():
                proc.kill()
                raise _Cancelled()
            if time.time() > deadline:
                proc.kill()
                raise RuntimeError("quá lâu, đã dừng: " + " ".join(cmd[1:3]))
            time.sleep(0.4)
        reader.join(timeout=5)
    finally:
        _proc["p"] = None
    if proc.returncode != 0:
        tail = " / ".join(lines[-4:])[-600:]
        raise RuntimeError(tail or f"thoát mã {proc.returncode}")
    return "\n".join(lines)


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _install_node(root: Path) -> None:
    if node_exe(root).is_file() and npm_cli(root).is_file():
        _set(done_mb=SIZE_MB["node"])
        return
    name, sha = NODE_SHA256[sys.platform]
    _set(phase=f"Tải Node.js {NODE_VERSION}")
    archive = root / "downloads" / name
    got = {"b": 0}

    def on_bytes(n: int) -> None:
        got["b"] += n
        _set(done_mb=min(SIZE_MB["node"], int(got["b"] / (1 << 20))))

    try:
        dub_addon.download([m.format(v=NODE_VERSION, f=name) for m in NODE_MIRRORS], archive, on_bytes, stop=_stop)
    except dub_addon._Cancelled as exc:
        raise _Cancelled() from exc
    if _sha256(archive) != sha:
        archive.unlink(missing_ok=True)
        raise RuntimeError(f"File {name} tải về không khớp chữ ký SHA-256 — đã bỏ, bấm Cài lại.")
    _set(phase="Giải nén Node.js")
    tmp = root / "node.part"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
    else:
        with tarfile.open(archive) as t:
            try:
                t.extractall(tmp, filter="data")
            except TypeError:  # Python < 3.11.4
                t.extractall(tmp)
    inner = next(p for p in tmp.iterdir() if p.is_dir() and p.name.startswith("node-v"))
    shutil.rmtree(root / "node", ignore_errors=True)
    os.replace(inner, root / "node")
    shutil.rmtree(tmp, ignore_errors=True)
    _set(done_mb=SIZE_MB["node"])


def _write_package(root: Path) -> None:
    app = app_dir(root)
    app.mkdir(parents=True, exist_ok=True)
    pkg = {"name": "dflow-remotion", "private": True, "type": "module", "version": "1.0.0",
           "description": "DFlow — Remotion subtitle engine (installed by the app)",
           "dependencies": dict(PACKAGES)}
    (app / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")
    sync_sources(root)


def _npm_install(root: Path) -> None:
    app = app_dir(root)
    _set(phase="Tải các gói Remotion (npm)")
    done = threading.Event()
    base = SIZE_MB["node"]

    def loop() -> None:
        while not done.wait(2.0):
            _set(done_mb=base + min(SIZE_MB["packages"], dub_addon._dir_mb(app / "node_modules")))

    threading.Thread(target=loop, name="remotion-addon-watch", daemon=True).start()
    env = child_env(root, npm_config_cache=str(root / "npm-cache"), npm_config_update_notifier="false",
                    npm_config_fund="false", npm_config_audit="false")
    try:
        _run([str(node_exe(root)), str(npm_cli(root)), "install", "--omit=dev", "--no-audit", "--no-fund",
              "--loglevel=error"], app, env, timeout=3600)
    finally:
        done.set()
    _set(done_mb=base + SIZE_MB["packages"])


def _prepare(root: Path) -> None:
    """Chrome Headless Shell + the webpack bundle, through the very script that renders (``render.mjs --prepare``)."""
    app = app_dir(root)
    base = SIZE_MB["node"] + SIZE_MB["packages"]
    _set(phase="Tải trình duyệt vẽ phụ đề (Chrome Headless Shell)")

    def on_line(line: str) -> None:
        if line.startswith("BROWSER "):
            try:
                pct = int(line.split()[1])
            except (IndexError, ValueError):
                return
            _set(done_mb=base + int(SIZE_MB["browser"] * min(100, pct) / 100))
        elif line.startswith("PHASE bundle"):
            _set(phase="Đóng gói phụ đề (lần đầu ~10 giây)", done_mb=base + SIZE_MB["browser"])

    _run([str(node_exe(root)), str(app / "remotion" / "render.mjs"), "--prepare"], app, child_env(root),
         timeout=3600, on_line=on_line)


def _install() -> None:
    root = addon_dir()
    root.mkdir(parents=True, exist_ok=True)
    free = dub_addon._free_mb(root)
    if free and free < NEED_FREE_MB:
        raise RuntimeError(f"Ổ đĩa chỉ còn {free} MB — cần khoảng {NEED_FREE_MB} MB trống.")
    _set(total_mb=plan_mb(), done_mb=0)
    (root / "addon.json").unlink(missing_ok=True)
    _install_node(root)
    _write_package(root)
    _npm_install(root)
    _prepare(root)
    _set(phase="Hoàn tất")
    shutil.rmtree(root / "downloads", ignore_errors=True)
    shutil.rmtree(root / "npm-cache", ignore_errors=True)
    data = {"version": ADDON_VERSION, "node": NODE_VERSION, "remotion": REMOTION_VERSION,
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "size_mb": dub_addon._dir_mb(root)}
    tmp = root / "addon.json.part"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, root / "addon.json")
    _set(done_mb=plan_mb())


def _worker() -> None:
    try:
        _install()
        _set(error="", phase="Đã cài xong")
    except _Cancelled:
        _set(error="Đã huỷ — bấm Cài lại để cài tiếp", phase="Đã huỷ")
    except Exception as exc:  # noqa: BLE001 — every failure ends up on the card
        logger.exception("remotion add-on install failed")
        msg = str(exc) or exc.__class__.__name__
        _set(error=f"Cài gói Remotion lỗi: {msg[:500]}", phase="Lỗi")
    finally:
        _set(running=False, finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"))


def install() -> dict[str, Any]:
    if sys.platform not in NODE_SHA256:
        raise RuntimeError("Gói Remotion chỉ có cho Windows (và Linux).")
    if kit_dir() is None:
        raise RuntimeError("Bản app này thiếu mã nguồn phụ đề Remotion — cập nhật DFlow bản mới rồi cài.")
    with _lock:
        if _state["running"]:
            return dict(_state)
        _stop.clear()
        _state.update(running=True, error="", phase="Bắt đầu", done_mb=0, total_mb=plan_mb(), last="",
                      started_at=time.strftime("%Y-%m-%dT%H:%M:%S"), finished_at=None)
    threading.Thread(target=_worker, name="remotion-addon-install", daemon=True).start()
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
            raise RuntimeError("Đang cài — huỷ trước rồi gỡ.")
    root = addon_dir()
    if not root.is_dir():
        return
    if root.name != "remotion" or root.parent.name != "addons":
        raise RuntimeError(f"Không gỡ thư mục lạ: {root}")
    shutil.rmtree(root, ignore_errors=True)
    _set(error="", phase="", done_mb=0, total_mb=0)
