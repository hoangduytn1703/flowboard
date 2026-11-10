"""Settings → 🖥 Máy này: what only this machine knows — the Flow plan, the cloud database line, where data and
the dubbing kit live — and, in the desktop app, opening its folders and restarting the agent.

The desktop shell (desktop/src-tauri) starts the agent again when it exits with :data:`RESTART_CODE`.

``/api/app/connect`` is open (no login): a fresh install has only its own empty account store, so the accounts the
admin made on the cloud database cannot log in until the cloud line is pasted — the login page offers that box.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from flowboard import config
from flowboard.services import app_env
from flowboard.services import machine

router = APIRouter(prefix="/api/app", tags=["app"])

RESTART_CODE = 75
#: What the agent started with: a restart-only key that differs from the file means "restart to apply".
_STARTED = {k: os.getenv(k, "") for k in app_env.RESTART_KEYS}


def _storage_root() -> Path:
    from flowboard import accounts

    return Path(getattr(accounts, "_ROOT_STORAGE", config.STORAGE_DIR))


@router.get("/status")
def status() -> dict[str, Any]:
    values = app_env.read_values()
    tier = app_env.current_tier()
    db = values.get("FLOWBOARD_CENTRAL_DB_URL", "")
    pending = [k for k in app_env.RESTART_KEYS if values.get(k, "") != _STARTED.get(k, "")]
    ext = app_env.extension_dir()
    return {
        "app": config.APP_MODE,
        "can_restart": config.APP_MODE,
        "can_open": sys.platform == "win32",
        "env_file": str(app_env.env_file()),
        "home": str(config.HOME or config.ROOT),
        "storage_dir": str(_storage_root()),
        "storage_custom": values.get("FLOWBOARD_STORAGE", ""),
        "logs_dir": str(app_env.logs_dir()),
        "extension_dir": str(ext) if ext else None,
        "paygate_tier": tier,
        "plan": app_env.TIERS.get(tier, ""),
        "cloud_db": {"set": bool(db), "host": app_env.db_host(db), "active": bool(_STARTED.get("FLOWBOARD_CENTRAL_DB_URL"))},
        "erase_root": values.get("FLOWBOARD_ERASE_ROOT", ""),
        "erase_python": values.get("FLOWBOARD_ERASE_PYTHON", ""),
        "capcut_drafts": values.get("FLOWBOARD_CAPCUT_DRAFTS", ""),
        "restart_pending": pending,
        "machine": machine.public(),
    }


@router.post("/machine/recheck")
def recheck_machine() -> dict[str, Any]:
    """"Kiểm tra lại" — ask the NVIDIA driver again (a card or driver installed after the first start)."""
    return machine.public(refresh=True)


class SettingsBody(BaseModel):
    paygate_tier: Optional[str] = Field(default=None, pattern="^PAYGATE_TIER_(ONE|TWO)$")
    # "" removes the line (back to data on this machine)
    central_db_url: Optional[str] = Field(default=None, max_length=1000)
    storage_dir: Optional[str] = Field(default=None, max_length=400)
    erase_root: Optional[str] = Field(default=None, max_length=400)
    erase_python: Optional[str] = Field(default=None, max_length=400)
    capcut_drafts: Optional[str] = Field(default=None, max_length=400)


def _folder(raw: str, label: str, *, create: bool = False) -> str:
    path = Path(raw.strip().strip('"'))
    if not path.is_absolute():
        raise HTTPException(400, f"{label}: cần đường dẫn đầy đủ, ví dụ D:\\DFlow-data")
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".dflow-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise HTTPException(400, f"{label}: không ghi được vào {path} ({exc})")
    elif not path.exists():
        raise HTTPException(400, f"{label}: không thấy {path}")
    return str(path)


@router.put("/settings")
def save_settings(body: SettingsBody) -> dict[str, Any]:
    updates: dict[str, Optional[str]] = {}
    if body.paygate_tier:
        updates["FLOWBOARD_PAYGATE_TIER"] = body.paygate_tier
    if body.central_db_url is not None:
        updates["FLOWBOARD_CENTRAL_DB_URL"] = _db_line(body.central_db_url) or None
    if body.storage_dir is not None:
        updates["FLOWBOARD_STORAGE"] = _folder(body.storage_dir, "Thư mục dữ liệu", create=True) if body.storage_dir.strip() else None
    if body.erase_root is not None:
        updates["FLOWBOARD_ERASE_ROOT"] = _folder(body.erase_root, "Thư mục VieDub") if body.erase_root.strip() else None
    if body.erase_python is not None:
        updates["FLOWBOARD_ERASE_PYTHON"] = _folder(body.erase_python, "Python của VieDub") if body.erase_python.strip() else None
    if body.capcut_drafts is not None:
        updates["FLOWBOARD_CAPCUT_DRAFTS"] = _folder(body.capcut_drafts, "Thư mục dự án CapCut") if body.capcut_drafts.strip() else None
    if not updates:
        return status()
    app_env.write_values(updates)
    if body.paygate_tier:
        app_env.apply_tier(body.paygate_tier)
    # the dubbing kit / CapCut paths are read on every call: in effect at once
    for key in ("FLOWBOARD_ERASE_ROOT", "FLOWBOARD_ERASE_PYTHON", "FLOWBOARD_CAPCUT_DRAFTS"):
        if key in updates:
            if updates[key]:
                os.environ[key] = updates[key] or ""
            else:
                os.environ.pop(key, None)
    return status()


def _db_line(raw: str) -> str:
    """The cloud line as pasted: the URL alone or the whole ``FLOWBOARD_CENTRAL_DB_URL=…`` line ("" = none)."""
    url = raw.strip().strip('"').strip()
    if url.startswith("FLOWBOARD_CENTRAL_DB_URL="):  # the whole line pasted
        url = url.split("=", 1)[1].strip().strip('"')
    if url and not url.startswith(("postgresql://", "postgres://")):
        raise HTTPException(400, "Dòng kết nối phải bắt đầu bằng postgresql:// (chép nguyên dòng chủ DFlow gửi)")
    return url


_LOCAL_CALLERS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _probe_cloud(url: str) -> None:
    """Connects once before saving, and insists on an existing DFlow account store (a typo'd or wrong database is
    refused instead of silently starting an empty one). Never echoes the password."""
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.pool import NullPool

    dsn = url.replace("postgres://", "postgresql+psycopg://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
    try:
        eng = create_engine(dsn, poolclass=NullPool, connect_args={"connect_timeout": 12})
    except Exception as exc:  # noqa: BLE001 — a malformed URL
        raise HTTPException(400, f"Dòng kết nối không đúng dạng ({type(exc).__name__}). Chép lại nguyên dòng được gửi.")
    try:
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
            has_accounts = inspect(c).has_table("account_user")
    except Exception as exc:  # noqa: BLE001 — wrong password / host / no network
        import re

        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        first = re.sub(r"^\([\w.]+\)\s*", "", first)  # SQLAlchemy's "(psycopg.errors.X) " prefix
        raise HTTPException(400, f"Không kết nối được tới dữ liệu cloud: {first[:200]}. Kiểm tra mạng và chép lại nguyên dòng được gửi.")
    finally:
        eng.dispose()
    if not has_accounts:
        raise HTTPException(400, "Kết nối được nhưng cơ sở dữ liệu này chưa có tài khoản DFlow nào — kiểm tra lại dòng kết nối với người quản lý DFlow.")


class ConnectBody(BaseModel):
    central_db_url: str = Field(max_length=1000)


@router.get("/connect")
def connect_status() -> dict[str, Any]:
    """Open: does this machine use the cloud database yet (the login page shows the paste box when not)."""
    from flowboard import accounts

    from flowboard import cloud_api

    saved = bool(app_env.read_values().get("FLOWBOARD_CENTRAL_DB_URL"))
    cloud = accounts.central_url() is not None
    site = cloud_api.site() if cloud_api.enabled() else None
    return {"app": config.APP_MODE, "cloud": cloud or site is not None, "restart_pending": saved and not cloud,
            "site": {"url": site, "host": cloud_api.host(), "signup": f"{site}/dang-ky", "forgot": f"{site}/dang-nhap"} if site else None}


@router.post("/connect")
def connect(body: ConnectBody, request: Request) -> dict[str, Any]:
    """Open, from the login page of a fresh install only: save the cloud line after a test connection, then restart
    the agent (the app does it; start.ps1 users run it again). Once the machine is on the cloud the line changes
    only from Settings → 🖥 Máy này, after logging in."""
    from flowboard import accounts

    if accounts.central_url() is not None:
        raise HTTPException(409, "Máy này đã nối dữ liệu cloud. Muốn đổi: đăng nhập rồi vào Cài đặt → 🖥 Máy này.")
    caller = request.client.host if request.client else ""
    if caller not in _LOCAL_CALLERS:
        raise HTTPException(403, "Chỉ dán được trên chính máy chạy DFlow.")
    url = _db_line(body.central_db_url)
    if not url:
        raise HTTPException(400, "Dán dòng kết nối được gửi (bắt đầu bằng postgresql://).")
    _probe_cloud(url)
    app_env.write_values({"FLOWBOARD_CENTRAL_DB_URL": url})
    if config.APP_MODE:
        threading.Timer(0.6, lambda: os._exit(RESTART_CODE)).start()
        return {"ok": True, "restarting": True}
    return {"ok": True, "restarting": False}


class OpenBody(BaseModel):
    what: str = Field(pattern="^(extension|data|logs|settings)$")


@router.post("/open")
def open_folder(body: OpenBody) -> dict[str, Any]:
    """Opens a folder in Explorer (the agent runs on the user's own machine)."""
    if sys.platform != "win32":
        raise HTTPException(400, "Chỉ mở được trên Windows")
    if body.what == "extension":
        target = app_env.extension_dir()
    elif body.what == "data":
        target = _storage_root()
    elif body.what == "logs":
        target = app_env.logs_dir()
        target.mkdir(parents=True, exist_ok=True)
    else:
        target = app_env.env_file()
        if not target.exists():
            app_env.write_values({})
    if target is None or not Path(target).exists():
        raise HTTPException(404, "Không thấy thư mục đó")
    if body.what == "settings":
        import subprocess

        subprocess.Popen(["notepad.exe", str(target)])  # noqa: S603,S607 — the user's own settings file
    else:
        os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606
    return {"ok": True, "path": str(target)}


class RestartBody(BaseModel):
    force: bool = False


@router.post("/restart")
def restart(body: RestartBody) -> dict[str, Any]:
    """The desktop app starts the agent again (settings that need it). Refused while work is running."""
    if not config.APP_MODE:
        raise HTTPException(400, "Chỉ bản app tự khởi động lại được — chạy lại start.ps1")
    if not body.force:
        from flowboard.routes.running import running

        busy = running().get("items") or []
        if busy:
            names = ", ".join(str(i.get("title") or i.get("kind") or "?") for i in busy[:3])
            raise HTTPException(409, f"Đang có việc chạy ({names}) — đợi xong rồi khởi động lại.")
    threading.Timer(0.6, lambda: os._exit(RESTART_CODE)).start()
    return {"ok": True, "restarting": True}
