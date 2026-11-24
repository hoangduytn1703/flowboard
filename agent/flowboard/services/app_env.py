"""The settings file (.env) the desktop app and start.ps1 share, edited from Settings → 🖥 Máy này.

The agent reads ``config.ENV_FILE`` once at import (``config._load_dotenv``). Most keys therefore need a
restart; the Flow plan is applied at once (``flow_sdk.DEFAULT_PAYGATE_TIER`` is read per call). Lines the
user wrote by hand — comments, keys we do not know — are kept as they are.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from flowboard import config

#: Keys Settings may write, and which of them only take effect after a restart.
EDITABLE = ("FLOWBOARD_PAYGATE_TIER", "FLOWBOARD_CENTRAL_DB_URL", "FLOWBOARD_STORAGE",
            "FLOWBOARD_ERASE_ROOT", "FLOWBOARD_ERASE_PYTHON", "FLOWBOARD_CAPCUT_DRAFTS",
            "FLOWBOARD_SAVE_DIR", "FLOWBOARD_SAVE_ASK")
RESTART_KEYS = ("FLOWBOARD_CENTRAL_DB_URL", "FLOWBOARD_STORAGE")
TIERS = {"PAYGATE_TIER_ONE": "Pro", "PAYGATE_TIER_TWO": "Ultra"}

_KEY = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def env_file() -> Path:
    return config.ENV_FILE


def read_values(path: Optional[Path] = None) -> dict[str, str]:
    """The keys written in the file (not the process environment)."""
    path = path or env_file()
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in raw.splitlines():
        m = _KEY.match(line)
        if not m or line.strip().startswith("#"):
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[m.group(1)] = value
    return out


def write_values(updates: dict[str, Optional[str]], path: Optional[Path] = None) -> None:
    """Set (or, with ``None`` / "", remove) keys in the file, keeping every other line; UTF-8 without a BOM
    (the agent and start.ps1 both read it). The file is created when missing."""
    path = path or env_file()
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        lines = ["# DFlow settings — written by Settings → Máy này (you may edit it by hand too)"]
    left = dict(updates)
    out: list[str] = []
    for line in lines:
        m = _KEY.match(line)
        if m and not line.strip().startswith("#") and m.group(1) in left:
            value = left.pop(m.group(1))
            if value:
                out.append(f"{m.group(1)}={value}")
            continue
        out.append(line)
    for key, value in left.items():
        if value:
            out.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def apply_tier(tier: str) -> None:
    """The Flow plan, at once: flow_sdk reads its module-level default on every call."""
    from flowboard.services import flow_sdk

    config.DEFAULT_PAYGATE_TIER = tier
    flow_sdk.DEFAULT_PAYGATE_TIER = tier
    os.environ["FLOWBOARD_PAYGATE_TIER"] = tier


def current_tier() -> str:
    from flowboard.services import flow_sdk

    return flow_sdk.DEFAULT_PAYGATE_TIER


def web_dir() -> Optional[Path]:
    """The built web UI the agent serves itself (the app; ``frontend/dist`` from the repo works too)."""
    raw = os.getenv("FLOWBOARD_WEB_DIR")
    if not raw:
        return None
    path = Path(raw)
    return path if (path / "index.html").is_file() else None


def extension_dir() -> Optional[Path]:
    raw = os.getenv("FLOWBOARD_EXTENSION_DIR")
    if raw and Path(raw, "manifest.json").is_file():
        return Path(raw)
    repo = config.ROOT / "extension"
    return repo if (repo / "manifest.json").is_file() else None


def logs_dir() -> Path:
    return (config.HOME or config.ROOT / "storage") / "logs"


def db_host(url: str) -> str:
    """Only the host of a connection string, for display — never the password."""
    m = re.match(r"^[a-z+]+://(?:[^@/]*@)?([^/:?]+)", url or "")
    return m.group(1) if m else ""
