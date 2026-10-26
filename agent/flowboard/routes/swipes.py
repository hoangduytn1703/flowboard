"""The swipe file ("🔥 Mẫu đang hot").

  GET    /api/swipes                      saved swipes, newest first
  POST   /api/swipes/analyze {url?, text?}   read + analyse + keep one
  GET    /api/swipes/{id}
  DELETE /api/swipes/{id}
  POST   /api/swipes/{id}/adapt {as: post|clip, channel_id, product_id?, kind?, template_id?, wish?}
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from flowboard.routes.channels import get_channel
from flowboard.services import swipes
from flowboard.services.products import get_product

router = APIRouter(prefix="/api/swipes", tags=["swipes"])


class AnalyzeBody(BaseModel):
    url: Optional[str] = Field(default=None, max_length=2000)
    text: Optional[str] = Field(default=None, max_length=8000)


class AdaptBody(BaseModel):
    as_: str = Field(default="post", alias="as")
    channel_id: int
    product_id: Optional[int] = None
    kind: str = Field(default="story", max_length=32)
    template_id: Optional[str] = Field(default=None, max_length=64)
    wish: Optional[str] = Field(default=None, max_length=500)

    model_config = {"populate_by_name": True}


@router.get("")
def list_all() -> list[dict[str, Any]]:
    return swipes.list_swipes()


@router.post("/analyze")
async def analyze(body: AnalyzeBody) -> dict[str, Any]:
    if not (body.url or "").strip() and not (body.text or "").strip():
        raise HTTPException(400, "Dán link hoặc nội dung bài.")
    try:
        return await swipes.analyze(body.url, body.text)
    except swipes.SwipeError as exc:
        raise HTTPException(502 if str(exc).startswith("AI") else 400, str(exc))


@router.get("/{swipe_id}")
def get_one(swipe_id: int) -> dict[str, Any]:
    sw = swipes.get_swipe(swipe_id)
    if sw is None:
        raise HTTPException(404, "không có mẫu này")
    return sw


@router.delete("/{swipe_id}")
def delete_one(swipe_id: int) -> dict[str, Any]:
    if not swipes.delete_swipe(swipe_id):
        raise HTTPException(404, "không có mẫu này")
    return {"ok": True}


@router.post("/{swipe_id}/adapt")
async def adapt(swipe_id: int, body: AdaptBody) -> dict[str, Any]:
    channel = get_channel(body.channel_id)
    if channel is None:
        raise HTTPException(400, "Chọn kênh / page.")
    product = get_product(body.product_id) if body.product_id else None
    if body.product_id and product is None:
        raise HTTPException(400, "Không thấy sản phẩm này.")
    try:
        if body.as_ == "clip":
            if product is None:
                raise HTTPException(400, "Tạo clip theo mẫu cần chọn sản phẩm.")
            return {"as": "clip", **await swipes.adapt_clip(swipe_id, channel_id=body.channel_id, product=product,
                                                           template_id=body.template_id, wish=body.wish)}
        return {"as": "post", **await swipes.adapt_post(swipe_id, channel=channel, product=product, kind=body.kind, wish=body.wish)}
    except swipes.SwipeError as exc:
        raise HTTPException(400, str(exc))
