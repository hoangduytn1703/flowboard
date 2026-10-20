"""Settings → "Nguồn tạo ảnh": which API renders images instead of Flow.

GET  /api/image-providers            → [{id, label, model, configured, notes_vi}]
PUT  /api/image-providers/{id}/key   {key} — empty string removes the key
POST /api/image-providers/{id}/test  {key?} → {ok, message} (free probe, no image)

The *selected* provider is a frontend preference (store/settings.ts) sent
per dispatch as ``params.image_provider``; the backend only keeps the keys.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from flowboard.services import image_providers
from flowboard.services.llm import secrets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/image-providers", tags=["image-providers"])


def _entry(pid: str) -> dict:
    meta = image_providers.PROVIDERS[pid]
    return {
        "id": pid,
        "label": meta["label"],
        "model": meta["model"],
        "configured": image_providers.configured(pid),
        "notes_vi": meta["notes_vi"],
    }


def _require(pid: str) -> None:
    if pid not in image_providers.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown image provider {pid!r}")


@router.get("")
def list_providers() -> list[dict]:
    return [_entry(pid) for pid in image_providers.PROVIDERS]


class KeyBody(BaseModel):
    key: str = ""


@router.put("/{pid}/key")
def put_key(pid: str, body: KeyBody) -> dict:
    _require(pid)
    if pid == "flow":
        raise HTTPException(status_code=400, detail="Flow dùng extension, không cần API key")
    key = body.key.strip()
    secrets.set_api_key(pid, key or None)
    logger.info("image-providers: key %s for %s", "set" if key else "cleared", pid)
    return _entry(pid)


class TestBody(BaseModel):
    key: Optional[str] = None


@router.post("/{pid}/test")
async def test_provider(pid: str, body: Optional[TestBody] = None) -> dict:
    _require(pid)
    key = (body.key or "").strip() if body is not None and body.key else None
    return await image_providers.test_key(pid, key)
