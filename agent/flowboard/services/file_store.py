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

Phase C (8/11): an app that logs in through the DFlow website (cloud_api.py)
never holds the bucket key — :class:`_ApiBucket` stands in for the boto3
client: the website signs a short-lived link per upload / download and lists
the account's own folder.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
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
#: Their sizes, from the last listing (used to spot a copy that differs from the file on this machine).
_remote_sizes: dict[str, int] = {}
_stats = {"uploaded": 0, "downloaded": 0, "upload_errors": 0, "download_errors": 0, "last_error": None,
          "broken_skipped": 0}
#: Files up to this size go up from one read of their bytes (size and content always agree); bigger ones stream.
READ_WHOLE_MAX = 64 * 1024 * 1024
#: Backblaze B2 refuses every download for the rest of the day once the bucket's daily download-bandwidth / Class B cap is
#: reached (403 "… cap exceeded"). Until the caps reset (00:00 UTC) downloads are not even tried — each picture on screen
#: used to ask again, and the Data tab showed a raw signed URL (14/11).
_downloads_paused_until = 0.0
DOWNLOAD_CAP_MESSAGE = ("Kho file (Backblaze B2) đã hết hạn mức tải xuống trong ngày — ảnh, video chưa có trên máy này sẽ tải được "
                        "sau 7 giờ sáng (giờ Việt Nam). Người quản lý DFlow có thể tăng hạn mức ở Backblaze → Caps & Alerts.")
UPLOAD_CAP_MESSAGE = ("Kho file (Backblaze B2) đã hết hạn mức (dung lượng hoặc lượt gửi) — file mới chưa lên được cloud. Người quản lý "
                      "DFlow tăng hạn mức ở Backblaze → Caps & Alerts hoặc dọn bớt file.")


def _cap_exceeded(exc: BaseException) -> bool:
    """B2's answer when a cap is reached (botocore puts the message in str(exc); _BucketRefused carries it too)."""
    return "cap exceeded" in str(exc).lower()


def _short_error(exc: BaseException) -> str:
    """The error without the signed link's query string (long, and nobody needs the signature in the Data tab)."""
    import re

    return re.sub(r"\?X-Amz-[^'\"\s]*", "", str(exc))


def _next_utc_midnight() -> float:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    return (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()


def config() -> Optional[dict[str, str]]:
    from flowboard import cloud_api

    if cloud_api.enabled():
        return {"endpoint": cloud_api.site() or "", "bucket": "DFlow", "keyId": "", "secret": "", "region": "", "via": "api"}
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
    _remote_sizes.clear()
    global _downloads_paused_until
    _downloads_paused_until = 0.0


def make_client(cfg: dict):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3", endpoint_url=cfg["endpoint"], region_name=cfg.get("region") or region_from_endpoint(cfg["endpoint"]),
        aws_access_key_id=cfg["keyId"], aws_secret_access_key=cfg["secret"],
        config=Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=10, read_timeout=120),
    )


class _NotInBucket(RuntimeError):
    """download_file of a missing key, shaped like botocore's error (file_store.download reads ``response``)."""

    def __init__(self, key: str) -> None:
        super().__init__(f"{key}: not found")
        self.response = {"Error": {"Code": "404"}}


class _BucketRefused(RuntimeError):
    """A signed link the bucket answered with an error: status + the bucket's own <Message> (e.g. "… cap exceeded")."""


def _bucket_message(body: str) -> str:
    import re

    m = re.search(r"<Message>(.*?)</Message>", body or "", re.S)
    return (m.group(1) if m else (body or "")).strip()[:200]


def _raise_for(resp) -> None:  # noqa: ANN001 — httpx.Response
    if resp.status_code >= 400:
        try:
            body = resp.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
        raise _BucketRefused(f"HTTP {resp.status_code}: {_bucket_message(body) or resp.reason_phrase}")


class _ApiBucket:
    """The calls file_store makes on a boto3 client, done through the DFlow website (Phase C): signed links, never the key."""

    def _owner(self) -> str:
        return prefix().rstrip("/")

    def _api(self, body: dict) -> dict:
        from flowboard import cloud_api

        return cloud_api.account_call(self._owner(), "POST", "/api/app/media", body=body)

    def _link(self, op: str, key: str) -> str:
        url = (self._api({"op": op, "keys": [key]}).get("urls") or {}).get(key)
        if not url:
            raise RuntimeError("máy chủ DFlow chưa có kho file")
        return url

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> None:  # noqa: N803 — boto3's names
        import httpx

        _raise_for(httpx.put(self._link("put", Key), content=Body, timeout=httpx.Timeout(300.0, connect=15.0)))

    def upload_file(self, Filename: str, Bucket: str, Key: str) -> None:  # noqa: N803
        import httpx

        with open(Filename, "rb") as fh:  # a file object: httpx sends its length (signed links refuse chunked uploads)
            _raise_for(httpx.put(self._link("put", Key), content=fh, timeout=httpx.Timeout(3600.0, connect=15.0)))

    def download_file(self, Bucket: str, Key: str, Filename: str) -> None:  # noqa: N803
        import httpx

        with httpx.stream("GET", self._link("get", Key), timeout=httpx.Timeout(600.0, connect=15.0)) as resp:
            if resp.status_code == 404:
                raise _NotInBucket(Key)
            _raise_for(resp)
            with open(Filename, "wb") as out:
                for chunk in resp.iter_bytes(1 << 20):
                    out.write(chunk)

    def list_objects_v2(self, Bucket: str, Prefix: str, MaxKeys: int = 1000, ContinuationToken: Optional[str] = None) -> dict:  # noqa: N803
        data = self._api({"op": "list", "prefix": Prefix, "token": ContinuationToken})
        nxt = data.get("next")
        return {"Contents": [{"Key": i["key"], "Size": i.get("size") or 0} for i in data.get("items") or []],
                "IsTruncated": bool(nxt), "NextContinuationToken": nxt}

    def delete_object(self, Bucket: str, Key: str) -> None:  # noqa: N803
        self._api({"op": "delete", "key": Key})


def client():
    global _client, _client_cfg
    cfg = config()
    if cfg is None:
        return None
    if cfg.get("via") == "api":
        return _ApiBucket()
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
    from flowboard.services.media import _IMAGE_SUFFIXES, image_ok

    c = client()
    key = key_for(local_path)
    p = Path(local_path)
    if c is None or key is None or not p.is_file():
        return False
    try:
        if p.stat().st_size <= READ_WHOLE_MAX:
            # One read: a file swapped in place mid-upload (the Gemini-mark cleaner) can no longer go up as the
            # old length of the new bytes — that stored pictures cut short (30/10).
            data = p.read_bytes()
            if p.suffix.lower() in _IMAGE_SUFFIXES and not image_ok(data):
                _stats["broken_skipped"] += 1
                logger.warning("file_store: %s is a picture cut short — not uploaded", key)
                return False
            c.put_object(Bucket=_bucket(), Key=key, Body=data)
            _remote_sizes[key] = len(data)
        else:
            c.upload_file(str(p), _bucket(), key)
        _remote_keys.add(key)
        _stats["uploaded"] += 1
        return True
    except Exception as exc:  # noqa: BLE001
        _stats["upload_errors"] += 1
        _stats["last_error"] = UPLOAD_CAP_MESSAGE if _cap_exceeded(exc) else f"upload {key}: {_short_error(exc)}"[:300]
        logger.warning("file_store: upload %s failed: %s", key, _short_error(exc))
        return False


def requeue(local_path: str | Path) -> None:
    """Upload again a file that was rewritten in place (the bucket holds the old bytes)."""
    key = key_for(local_path)
    if key is not None:
        _remote_keys.discard(key)
    queue_upload(local_path)


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
    end = time.time() + timeout
    while _queue.unfinished_tasks and time.time() < end:
        time.sleep(0.05)


# ── download ────────────────────────────────────────────────────────────────

def download(key: str, dest: Optional[Path] = None) -> bool:
    global _downloads_paused_until
    if time.time() < _downloads_paused_until:
        return False
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
            if _cap_exceeded(exc):
                _downloads_paused_until = _next_utc_midnight()
                _stats["last_error"] = DOWNLOAD_CAP_MESSAGE
                logger.warning("file_store: the bucket's daily download cap is reached — downloads paused until 00:00 UTC")
            else:
                _stats["last_error"] = f"download {key}: {_short_error(exc)}"[:300]
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
            _remote_sizes[obj["Key"]] = int(obj.get("Size") or 0)
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


def _memo_path() -> Path:
    return Path(app_config.STORAGE_DIR) / "media_checked.json"


def _load_memo() -> dict[str, str]:
    import json

    try:
        return json.loads(_memo_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_memo(memo: dict[str, str]) -> None:
    import json

    try:
        _memo_path().write_text(json.dumps(memo), encoding="utf-8")
    except OSError:
        pass


def repair_images() -> dict[str, Any]:
    """Pictures cut short (an upload once read the old size and the new bytes, 30/10): a broken file here is fetched
    again when the bucket's copy is whole; a whole file here whose bucket copy has another size goes up again (the
    bucket copy may be the broken one — or the one still wearing the Gemini mark). Each (file, size) is handled once
    per machine (``media_checked.json``), so two machines with different copies do not trade uploads forever."""
    from flowboard.services.media import _IMAGE_SUFFIXES, image_ok

    out: dict[str, Any] = {"checked": 0, "fixed_here": 0, "uploaded": 0, "broken": []}
    if not enabled():
        return out
    remote = _remote_keys or list_keys()
    memo = _load_memo()
    for path in _asset_paths():
        p = Path(path)
        if p.suffix.lower() not in _IMAGE_SUFFIXES or not p.is_file():
            continue
        key = key_for(p)
        if key is None:
            continue
        out["checked"] += 1
        size = p.stat().st_size
        if image_ok(p):
            rsize = _remote_sizes.get(key)
            if key in remote and rsize is not None and rsize != size and memo.get(key) != f"up:{size}":
                if upload_now(p):
                    out["uploaded"] += 1
                memo[key] = f"up:{size}"
            continue
        rsize = _remote_sizes.get(key)
        if key in remote and rsize and rsize != size and memo.get(key) != f"down:{rsize}":
            tmp = p.with_name(p.name + ".check")
            if download(key, tmp) and image_ok(tmp.read_bytes()):
                os.replace(tmp, p)
                out["fixed_here"] += 1
                continue
            try:
                tmp.unlink()
            except OSError:
                pass
            memo[key] = f"down:{rsize}"
        out["broken"].append(p.stem)
    _save_memo(memo)
    if out["broken"] or out["fixed_here"] or out["uploaded"]:
        logger.info("file_store: pictures — %d fixed here, %d sent up again, still broken: %s",
                    out["fixed_here"], out["uploaded"], ", ".join(out["broken"]) or "none")
    return out


def reconcile() -> dict[str, int]:
    try:
        pushed = push_missing()
        pulled = pull_missing()
        repaired = repair_images()
        logger.info("file_store: queued %d upload(s), downloaded %d file(s) for %s", pushed, pulled, prefix())
        return {"queued": pushed, "downloaded": pulled, "repaired": repaired["fixed_here"], "reuploaded": repaired["uploaded"]}
    except Exception as exc:  # noqa: BLE001 — offline start must not fail
        _stats["last_error"] = f"reconcile: {exc}"[:300]
        logger.warning("file_store: reconcile failed: %s", exc)
        return {"queued": 0, "downloaded": 0, "repaired": 0, "reuploaded": 0}


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
        "downloads_paused": _downloads_paused_until > time.time(),
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
