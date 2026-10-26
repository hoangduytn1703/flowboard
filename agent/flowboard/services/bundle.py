"""One product → the whole content pack ("🎁 Gói nội dung"): a clip board
with its script written for the product, a Facebook post that goes with
the clip (first comment with the affiliate link), and a short TikTok
caption — all on one channel, in its voice.

The clip is only *prepared* (board + tailored prompts and voice lines):
rendering images and videos costs Flow credits, so that stays a click in
the wizard. Each part is made independently: one failure is reported in
its slot, the others still come back.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from flowboard.db import get_session
from flowboard.db.models import Post
from flowboard.services import post_writer
from flowboard.services.products import get_product

logger = logging.getLogger(__name__)

#: Post types that make sense next to a clip.
POST_KINDS = ("review", "story", "tips", "discussion", "sale")


class BundleError(RuntimeError):
    pass


async def _clip(product: dict, channel_id: int, template_id: Optional[str], name: Optional[str]) -> dict[str, Any]:
    # Imported here: the route module pulls in the FastAPI layer.
    from fastapi import HTTPException

    from flowboard.routes.templates import FromTemplateBody, create_board_from_template

    tid = template_id or product.get("template_id") or "affiliate_reel"
    try:
        board = await create_board_from_template(FromTemplateBody(
            template_id=tid, name=name, inputs={}, product_id=int(product["id"]), channel_id=channel_id, tailor=True,
        ))
    except HTTPException as exc:
        raise BundleError(str(exc.detail))
    return {"id": board["id"], "name": board["name"], "template_id": tid,
            "tailored": bool(((board.get("data") or {}).get("quicktool") or {}).get("tailored"))}


def _save_post(post: dict[str, Any], *, kind: str, title: str, product_id: int, channel_id: int,
               board_id: Optional[int], brief: dict[str, Any]) -> dict[str, Any]:
    with get_session() as s:
        row = Post(kind=kind, title=title[:120], body=post["body"], hashtags=" ".join(post.get("hashtags") or []),
                   first_comment=post.get("first_comment") or "", product_id=product_id, board_id=board_id,
                   channel_id=channel_id, images=[], image_prompts=list(post.get("image_prompts") or []), brief=brief)
        s.add(row)
        s.commit()
        s.refresh(row)
        return {"id": row.id, "title": row.title, "body": row.body, "hashtags": row.hashtags,
                "first_comment": row.first_comment, "kind": row.kind}


async def _fb_post(product: dict, channel: Optional[dict], clip: Optional[dict], board_id: Optional[int],
                   channel_id: int, kind: str) -> dict[str, Any]:
    brief = {"kind": kind, "cta": "link", "length": "medium", "images": 0, "boosts": ["question_end"]}
    post = await post_writer.write_post(brief, product=product, clip=clip, channel=channel)
    return _save_post(post, kind=kind, title=post.get("title") or f"{product['name']} — bài Facebook",
                      product_id=int(product["id"]), channel_id=channel_id, board_id=board_id, brief=brief)


async def _tiktok_caption(product: dict, channel: Optional[dict], clip: Optional[dict], board_id: Optional[int],
                          channel_id: int) -> dict[str, Any]:
    brief = {"kind": "sale", "platform": "tiktok", "cta": "link", "length": "short", "images": 0,
             "topic": "Caption ngắn cho video TikTok Shop của sản phẩm này: 1-2 câu móc + lợi ích chính, hashtag; link ở bình luận đầu."}
    post = await post_writer.write_post(brief, product=product, clip=clip, channel=channel)
    return _save_post(post, kind="tiktok_caption", title=f"Caption TikTok — {product['name']}",
                      product_id=int(product["id"]), channel_id=channel_id, board_id=board_id, brief=brief)


async def make(product_id: int, channel_id: int, *, template_id: Optional[str] = None, post_kind: str = "review",
               with_clip: bool = True, with_post: bool = True, with_tiktok: bool = True,
               clip_name: Optional[str] = None) -> dict[str, Any]:
    """Build the pack. Returns ``{product, channel_id, clip, post, tiktok, errors}``
    where a missing part has its reason in ``errors[part]``."""
    from flowboard.routes.channels import get_channel
    from flowboard.routes.posts import _clip_context

    product = get_product(product_id)
    if product is None:
        raise BundleError("Không thấy sản phẩm này.")
    channel = get_channel(channel_id)
    if channel is None:
        raise BundleError("Chọn kênh / page cho gói nội dung.")
    if post_kind not in POST_KINDS:
        post_kind = "review"
    out: dict[str, Any] = {"product": {"id": product["id"], "name": product["name"]}, "channel_id": channel_id,
                           "clip": None, "post": None, "tiktok": None, "errors": {}}
    clip_ctx: Optional[dict] = None
    board_id: Optional[int] = None
    if with_clip:
        try:
            out["clip"] = await _clip(product, channel_id, template_id, clip_name)
            board_id = int(out["clip"]["id"])
            clip_ctx, _p, _c = _clip_context(board_id)
        except BundleError as exc:
            out["errors"]["clip"] = str(exc)
        except Exception as exc:  # noqa: BLE001 — the posts can still be written
            logger.exception("bundle: clip failed")
            out["errors"]["clip"] = f"Không tạo được clip: {exc}"
    jobs: dict[str, Any] = {}
    if with_post:
        jobs["post"] = _fb_post(product, channel, clip_ctx, board_id, channel_id, post_kind)
    if with_tiktok:
        jobs["tiktok"] = _tiktok_caption(product, channel, clip_ctx, board_id, channel_id)
    if jobs:
        results = await asyncio.gather(*jobs.values(), return_exceptions=True)
        for key, res in zip(jobs.keys(), results):
            if isinstance(res, Exception):
                logger.warning("bundle: %s failed: %s", key, res)
                out["errors"][key] = str(res) if isinstance(res, post_writer.PostWriterError) else f"Lỗi: {res}"
            else:
                out[key] = res
    if out["clip"] is None and out["post"] is None and out["tiktok"] is None:
        raise BundleError("Không tạo được phần nào: " + "; ".join(out["errors"].values()))
    return out
