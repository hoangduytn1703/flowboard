"""Settings → Dữ liệu: where the logged-in account's data lives, the media
bucket shared by every machine, and the one-time move to the cloud.

  GET  /api/cloud/status
  PUT  /api/cloud/s3        {endpoint, bucket, keyId, secret, region?}  (tested before saving; empty body = remove)
  POST /api/cloud/files/sync
  POST /api/cloud/migrate   → copy this account's SQLite data to its Postgres schema (needs FLOWBOARD_CENTRAL_DB_URL)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from flowboard import accounts
from flowboard.services import file_store

router = APIRouter(prefix="/api/cloud", tags=["cloud"])


class S3Body(BaseModel):
    endpoint: Optional[str] = None
    bucket: Optional[str] = None
    keyId: Optional[str] = None
    secret: Optional[str] = None
    region: Optional[str] = None


def _me(request: Request) -> Optional[dict]:
    if not accounts.auth_enabled():
        return None
    return accounts.user_from_request(request)


@router.get("/status")
def cloud_status(request: Request) -> dict:
    acc = accounts.status()
    fs = file_store.status()
    fs.pop("prefix", None)
    return {"account": acc, "files": fs, "central_cloud": accounts.central_url() is not None, "via_api": accounts.via_api()}


@router.put("/s3")
def set_s3(body: S3Body, request: Request) -> dict:
    user = _me(request)
    if accounts.via_api():
        raise HTTPException(409, "Kho file do máy chủ DFlow giữ — máy này không cần (và không được) cài key.")
    if accounts.auth_enabled() and not accounts.is_admin(user):
        raise HTTPException(403, "Chỉ tài khoản quản trị mới đổi được kho file.")
    if not any([body.endpoint, body.bucket, body.keyId, body.secret]):
        accounts.set_setting("s3", None)
        file_store.reset()
        return {"ok": True, "message": "Đã bỏ kho file."}
    cur = accounts.get_setting("s3") or {}
    cfg = {
        "endpoint": (body.endpoint or cur.get("endpoint") or "").strip(),
        "bucket": (body.bucket or cur.get("bucket") or "").strip(),
        "keyId": (body.keyId or cur.get("keyId") or "").strip(),
        "secret": (body.secret or cur.get("secret") or "").strip(),
    }
    if body.region and body.region.strip():
        cfg["region"] = body.region.strip()
    if not all(cfg[k] for k in ("endpoint", "bucket", "keyId", "secret")):
        raise HTTPException(400, "Cần đủ endpoint, bucket, key ID và secret.")
    if not cfg["endpoint"].startswith(("http://", "https://")):
        cfg["endpoint"] = "https://" + cfg["endpoint"]
    ok, msg = file_store.test_connection(cfg)
    if not ok:
        raise HTTPException(400, msg)
    accounts.set_setting("s3", cfg)
    file_store.reset()
    file_store.reconcile_in_background()
    return {"ok": True, "message": msg + " Đã lưu cho mọi máy đăng nhập; đang đẩy file lên nền."}


@router.post("/files/sync")
def sync_files() -> dict:
    if not file_store.enabled():
        raise HTTPException(400, "Chưa cài kho file.")
    return {**file_store.reconcile(), "status": file_store.status()}


@router.post("/migrate")
def migrate(request: Request) -> dict:
    user = _me(request)
    if user is None:
        raise HTTPException(401, "Chưa đăng nhập")
    if accounts.via_api():
        raise HTTPException(409, "Dữ liệu của tài khoản đã nằm trên cloud DFlow.")
    try:
        from flowboard.worker.processor import get_worker
        if get_worker().active_count > 0:
            raise HTTPException(409, "Đang có việc chạy (tạo ảnh/video) — chờ xong rồi chuyển.")
    except ImportError:
        pass
    try:
        out = accounts.move_to_cloud(user["username"])
    except accounts.AuthError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Chuyển dữ liệu thất bại: {str(exc)[:300]}")
    if out.get("moved"):
        # Re-activate on the cloud engine right away.
        accounts.deactivate()
        accounts.activate(accounts.get_user(user["username"]))  # type: ignore[arg-type]
    return out
