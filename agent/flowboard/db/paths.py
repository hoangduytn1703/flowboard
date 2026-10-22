"""File paths stored in the database, portable between machines.

``Asset.local_path`` used to hold an absolute path (``D:\\codes\\…\\storage\\
media\\x.mp4``). With an account's database in the cloud, the same row is
read on Windows at home and on Ubuntu at the office, so the column stores
the path **relative to the account's data folder** with forward slashes
(``media/x.mp4``) and hands back an absolute path under the data folder of
the machine reading it — every call site keeps using ``Path(row.local_path)``.

Old absolute values are still read: when the file is not where they say,
the part after ``media/`` (or ``chat_uploads/``) is looked up under the
current data folder. :func:`normalize_asset_paths` rewrites them once.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional

from sqlalchemy.types import String, TypeDecorator

from flowboard import config

#: Sub-folders of the data folder that hold files an Asset can point at.
_MARKERS = ("media", "chat_uploads")


def _storage() -> Path:
    return Path(config.STORAGE_DIR)


def _parts(value: str) -> tuple[str, ...]:
    """Path parts of a Windows or POSIX path string, whatever OS reads it."""
    if "\\" in value or (len(value) > 1 and value[1] == ":"):
        return PureWindowsPath(value).parts
    return PurePosixPath(value).parts


def is_relative(value: str) -> bool:
    return not (value.startswith(("/", "\\")) or (len(value) > 1 and value[1] == ":"))


def relative_tail(value: str) -> Optional[str]:
    """``…/media/tts/a.wav`` → ``media/tts/a.wav`` (last marker wins)."""
    parts = _parts(value)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] in _MARKERS:
            return "/".join(parts[i:])
    return None


def to_stored(value: Optional[str]) -> Optional[str]:
    """Absolute path under the data folder → ``media/x.mp4``; else unchanged."""
    if value is None or value == "":
        return value
    value = str(value)
    if is_relative(value):
        return value.replace("\\", "/")
    try:
        rel = Path(value).resolve().relative_to(_storage().resolve())
        return rel.as_posix()
    except (ValueError, OSError):
        pass
    # Outside the data folder (a test's temp file, an external drive): keep
    # the absolute path — only reads of OLD rows use the marker fallback.
    return value


def from_stored(value: Optional[str]) -> Optional[str]:
    """Stored value → absolute path on this machine."""
    if value is None or value == "":
        return value
    if is_relative(value):
        return str(_storage() / Path(*PurePosixPath(value).parts))
    try:
        if Path(value).exists():
            return value
    except OSError:
        pass
    tail = relative_tail(value)
    if tail is not None:
        return str(_storage() / Path(*PurePosixPath(tail).parts))
    return value


class StoragePath(TypeDecorator):
    """A path column stored relative to the account's data folder."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: D401
        return to_stored(value)

    def process_result_value(self, value, dialect):
        return from_stored(value)


def normalize_asset_paths(engine) -> int:
    """Rewrite absolute ``asset.local_path`` values whose file is found
    under the current data folder into the relative form. Returns how many
    rows changed. Raw SQL on purpose: the ORM type would hide the old value."""
    from sqlalchemy import inspect, text

    with engine.connect() as conn:
        if not inspect(conn).has_table("asset"):
            return 0
        rows = conn.execute(text("SELECT id, local_path FROM asset WHERE local_path IS NOT NULL AND local_path != ''")).fetchall()
        changed = 0
        for rid, value in rows:
            if is_relative(value):
                continue
            tail = relative_tail(value)
            if tail is None:
                continue
            if not (_storage() / Path(*PurePosixPath(tail).parts)).exists():
                continue
            conn.execute(text("UPDATE asset SET local_path = :p WHERE id = :i"), {"p": tail, "i": rid})
            changed += 1
        conn.commit()
        return changed
