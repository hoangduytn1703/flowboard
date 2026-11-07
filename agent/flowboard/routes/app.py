"""Settings → 🖥 Máy này: what only this machine knows — the Flow plan, the cloud database line, where data and
the dubbing kit live — and, in the desktop app, opening its folders and restarting the agent.

The desktop shell (desktop/src-tauri) starts the agent again when it exits with :data:`RESTART_CODE`."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from flowboard import config
from flowboard.services import app_env

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
    }


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
        url = body.central_db_url.strip()
        if url.startswith("FLOWBOARD_CENTRAL_DB_URL="):  # the whole line pasted
            url = url.split("=", 1)[1].strip()
        if url and not url.startswith(("postgresql://", "postgres://")):
            raise HTTPException(400, "Dòng kết nối phải bắt đầu bằng postgresql:// (chép nguyên dòng chủ DFlow gửi)")
        updates["FLOWBOARD_CENTRAL_DB_URL"] = url or None
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
