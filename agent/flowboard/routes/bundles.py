"""One product → clip + Facebook post + TikTok caption ("🎁 Gói nội dung").

  POST /api/bundles   {product_id, channel_id, template_id?, post_kind?, with_clip?, with_post?, with_tiktok?, clip_name?}
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from flowboard.services import bundle

router = APIRouter(prefix="/api/bundles", tags=["bundles"])


class BundleBody(BaseModel):
    product_id: int
    channel_id: int
    template_id: Optional[str] = Field(default=None, max_length=64)
    post_kind: str = "review"
    with_clip: bool = True
    with_post: bool = True
    with_tiktok: bool = True
    clip_name: Optional[str] = Field(default=None, max_length=80)


@router.get("/options")
def options() -> dict[str, Any]:
    from flowboard.services.post_writer import POST_TYPES

    return {"post_kinds": [{"key": k, "label": POST_TYPES[k][0]} for k in bundle.POST_KINDS]}


@router.post("")
async def make_bundle(body: BundleBody) -> dict[str, Any]:
    if not (body.with_clip or body.with_post or body.with_tiktok):
        raise HTTPException(400, "Chọn ít nhất một phần: clip, bài Facebook hoặc caption TikTok.")
    try:
        return await bundle.make(body.product_id, body.channel_id, template_id=body.template_id, post_kind=body.post_kind,
                                 with_clip=body.with_clip, with_post=body.with_post, with_tiktok=body.with_tiktok,
                                 clip_name=body.clip_name)
    except bundle.BundleError as exc:
        raise HTTPException(400, str(exc))
