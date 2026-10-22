"""Media files of an account in an S3-compatible bucket (Backblaze B2, R2…).

The account's rows travel through the cloud database; the files they point
at (joined clips, uploads, cleaned videos, covers, music, and the local
copies of Flow media) go to a bucket under ``<username>/<relative path>`` —
the same relative string the database stores — so any machine maps a row
to its object.

* **Upload**: every Asset row that gets a local file is queued (SQLAlchemy
  ``after_insert`` / ``after_update``) and a background thread drains the
  queue; nothing waits on the network.
* **Download**: :func:`ensure_local` fetches a missing file on demand
  (``media.cached_path`` calls it); :func:`reconcile` runs when an account
  becomes active: uploads local files the bucket lacks, fetches files this
  machine lacks.

Configuration (first match wins): env ``FLOWBOARD_S3_ENDPOINT`` /
``FLOWBOARD_S3_BUCKET`` / ``FLOWBOARD_S3_KEY_ID`` / ``FLOWBOARD_S3_SECRET``
(/ ``FLOWBOARD_S3_REGION``), else the central account store's ``s3``
setting (set once from Settings → Dữ liệu; every machine that logs in gets
it). Not configured → every function is a no-op.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from flowboard import config as app_config

logger = logging.getLogger(__name__)

_client = None
_client_cfg: Optional[dict] = None
_client_lock = threading.Lock()
_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
_worker: Optional[threading.Thread] = None
#: Keys known to be in the bucket for the active account (listing / uploads).
_remote_keys: set[str] = set()
_stats = {"uploaded": 0, "downloaded": 0, "upload_errors": 0, "download_errors": 0, "last_error": None}


def config() -> Optional[dict[str, str]]:
    env = {
        "endpoint": os.getenv("FLOWBOARD_S3_ENDPOINT"), "bucket": os.getenv("FLOWBOARD_S3_BUCKET"),
        "keyId": os.getenv("FLOWBOARD_S3_KEY_ID"), "secret": os.getenv("FLOWBOARD_S3_SECRET"),
        "region": os.getenv("FLOWBOARD_S3_REGION"),
    }
    if not all(env[k] for k in ("endpoint", "bucket", "keyId", "secret")):
        try:
            from flowboard import accounts
            stored = accounts.get_setting("s3") or {}
        except Exception:  # noqa: BLE001 — no central store yet
            stored = {}
        if isinstance(stored, dict):
            for k in env:
                env[k] = env[k] or stored.get(k)
    if not all(isinstance(env[k], str) and env[k].strip() for k in ("endpoint", "bucket", "keyId", "secret")):
        return None
    out = {k: (v.strip() if isinstance(v, str) else v) for k, v in env.items()}
    if not out["endpoint"].startswith(("http://", "https://")):
        out["endpoint"] = "https://" + out["endpoint"]
    if not out.get("region"):
        out["region"] = region_from_endpoint(out["endpoint"])
    return out  # type: ignore[return-value]


def region_from_endpoint(endpoint: str) -> str:
    # s3.us-west-004.backblazeb2.com → us-west-004; R2 and others want "auto".
    host = endpoint.split("://", 1)[-1].split("/", 1)[0]
    if "backblazeb2.com" in host and host.startswith("s3."):
        return host.split(".")[1]
    return "auto"


def enabled() -> bool:
    return config() is not None


def prefix() -> str:
    """The active account's folder in the bucket."""
    try:
        from flowboard import accounts
        user = accounts.active_user()
    except Exception:  # noqa: BLE001
        user = None
    return (user["username"] if user else "local") + "/"


def reset() -> None:
    """Forget the client (config / account changed, or tests)."""
    global _client, _client_cfg
    with _client_lock:
        _client = None
        _client_cfg = None
    _remote_keys.clear()


def make_client(cfg: dict):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3", endpoint_url=cfg["endpoint"], region_name=cfg.get("region") or region_from_endpoint(cfg["endpoint"]),
        aws_access_key_id=cfg["keyId"], aws_secret_access_key=cfg["secret"],
        config=Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=10, read_timeout=120),
    )


def client():
    global _client, _client_cfg
    cfg = config()
    if cfg is None:
        return None
    with _client_lock:
        if _client is None or _client_cfg != cfg:
            _client = make_client(cfg)
            _client_cfg = cfg
        return _client


def _bucket() -> str:
    cfg = config()
    return cfg["bucket"] if cfg else ""


def key_for(local_path: str | Path) -> Optional[str]:
    """``…/accounts/akira/media/x.mp4`` → ``akira/media/x.mp4`` (None outside the data folder)."""
    from flowboard.db.paths import is_relative, to_stored

    stored = to_stored(str(local_path))
    return prefix() + stored if stored and is_relative(stored) else None


def local_for(key: str) -> Path:
    rel = key[len(prefix()):] if key.startswith(prefix()) else key
    return Path(app_config.STORAGE_DIR) / Path(*PurePosixPath(rel).parts)


# ── upload ──────────────────────────────────────────────────────────────────

def upload_now(local_path: str | Path) -> bool:
    c = client()
    key = key_for(local_path)
    p = Path(local_path)
    if c is None or key is None or not p.is_file():
        return False
    try:
        c.upload_file(str(p), _bucket(), key)
        _remote_keys.add(key)
        _stats["uploaded"] += 1
        return True
    except Exception as exc:  # noqa: BLE001
        _stats["upload_errors"] += 1
        _stats["last_error"] = f"upload {key}: {exc}"[:300]
        logger.warning("file_store: upload %s failed: %s", key, exc)
        return False


def queue_upload(local_path: str | Path) -> None:
    if not enabled():
        return
    key = key_for(local_path)
    if key is None or key in _remote_keys:
        return
    _queue.put((key, str(local_path)))
    _ensure_worker()


def _ensure_worker() -> None:
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    _worker = threading.Thread(target=_drain, name="file-store-upload", daemon=True)
    _worker.start()


def _drain() -> None:
    while True:
        try:
            key, path = _queue.get(timeout=30)
        except queue.Empty:
            return
        if key not in _remote_keys:
            upload_now(path)
        _queue.task_done()


def wait_idle(timeout: float = 30.0) -> None:
    import time

    end = time.time() + timeout
    while _queue.unfinished_tasks and time.time() < end:
        time.sleep(0.05)


# ── download ────────────────────────────────────────────────────────────────

def download(key: str, dest: Optional[Path] = None) -> bool:
    c = client()
    if c is None:
        return False
    dest = dest or local_for(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        c.download_file(_bucket(), key, str(tmp))
        os.replace(tmp, dest)
        _stats["downloaded"] += 1
        return True
    except Exception as exc:  # noqa: BLE001 — not in the bucket, or offline
        try:
            tmp.unlink()
        except OSError:
            pass
        err = getattr(exc, "response", None) or {}
        code = (err.get("Error") or {}).get("Code") if isinstance(err, dict) else None
        if code not in ("404", "NoSuchKey"):
            _stats["download_errors"] += 1
            _stats["last_error"] = f"download {key}: {exc}"[:300]
        return False


def ensure_local(local_path: Optional[str]) -> Optional[Path]:
    """The file at ``local_path``, fetched from the bucket when missing."""
    if not local_path:
        return None
    p = Path(local_path)
    if p.is_file():
        return p
    if not enabled():
        return None
    key = key_for(p)
    if key is None:
        return None
    return p if download(key, p) else None


# ── reconciliation when an account becomes active ───────────────────────────

def list_keys() -> set[str]:
    c = client()
    if c is None:
        return set()
    keys: set[str] = set()
    token = None
    while True:
        kw: dict[str, Any] = {"Bucket": _bucket(), "MaxKeys": 1000, "Prefix": prefix()}
        if token:
            kw["ContinuationToken"] = token
        resp = c.list_objects_v2(**kw)
        for obj in resp.get("Contents", []) or []:
            keys.add(obj["Key"])
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    _remote_keys.clear()
    _remote_keys.update(keys)
    return keys


def _asset_paths() -> list[str]:
    from sqlmodel import select

    from flowboard.db import get_session
    from flowboard.db.models import Asset

    with get_session() as s:
        return [r for r in s.exec(select(Asset.local_path).where(Asset.local_path.is_not(None))).all() if r]  # type: ignore[union-attr]


def push_missing() -> int:
    if not enabled():
        return 0
    remote = list_keys()
    n = 0
    for path in _asset_paths():
        key = key_for(path)
        if key and key not in remote and Path(path).is_file():
            queue_upload(path)
            n += 1
    return n


def pull_missing(limit: Optional[int] = None) -> int:
    if not enabled():
        return 0
    remote = _remote_keys or list_keys()
    n = 0
    for path in _asset_paths():
        if Path(path).is_file():
            continue
        key = key_for(path)
        if key and key in remote and download(key, Path(path)):
            n += 1
            if limit and n >= limit:
                break
    return n


def reconcile() -> dict[str, int]:
    try:
        pushed = push_missing()
        pulled = pull_missing()
        logger.info("file_store: queued %d upload(s), downloaded %d file(s) for %s", pushed, pulled, prefix())
        return {"queued": pushed, "downloaded": pulled}
    except Exception as exc:  # noqa: BLE001 — offline start must not fail
        _stats["last_error"] = f"reconcile: {exc}"[:300]
        logger.warning("file_store: reconcile failed: %s", exc)
        return {"queued": 0, "downloaded": 0}


def reconcile_in_background() -> None:
    if enabled():
        threading.Thread(target=reconcile, name="file-store-reconcile", daemon=True).start()


def test_connection(cfg: dict) -> tuple[bool, str]:
    try:
        c = make_client({**cfg, "endpoint": cfg["endpoint"] if cfg["endpoint"].startswith("http") else "https://" + cfg["endpoint"]})
        c.put_object(Bucket=cfg["bucket"], Key=".flowboard-test", Body=b"ok")
        c.delete_object(Bucket=cfg["bucket"], Key=".flowboard-test")
        return True, f"Kho file OK — ghi/xoá thử được trên bucket {cfg['bucket']}."
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if any(t in msg for t in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "401", "403", "Unauthorized")):
            return False, "Key của kho file sai, hoặc key không có quyền ghi bucket này."
        if "NoSuchBucket" in msg:
            return False, f"Không có bucket {cfg['bucket']}."
        return False, f"Không kết nối được kho file: {msg[:200]}"


def status() -> dict[str, Any]:
    cfg = config()
    return {
        "enabled": cfg is not None,
        "endpoint": cfg["endpoint"] if cfg else None,
        "bucket": cfg["bucket"] if cfg else None,
        "prefix": prefix() if cfg else None,
        "pending_uploads": _queue.unfinished_tasks,
        **_stats,
    }


def install_hooks() -> None:
    """Queue an upload whenever an Asset row gets a local file."""
    from sqlalchemy import event

    from flowboard.db.models import Asset

    if getattr(install_hooks, "_done", False):
        return

    def _after(mapper, connection, target) -> None:  # noqa: ANN001
        if target.local_path:
            queue_upload(target.local_path)

    event.listen(Asset, "after_insert", _after)
    event.listen(Asset, "after_update", _after)
    install_hooks._done = True  # type: ignore[attr-defined]
