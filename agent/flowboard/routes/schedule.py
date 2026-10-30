"""The posting calendar ("Lịch đăng").

  GET    /api/schedule?from=&to=&channel_id=&status=   slots in a window (ISO times; default: this week → +4 weeks)
  GET    /api/schedule/due                              planned slots whose time has passed (Today page)
  GET    /api/schedule/suggest?channel_id=&limit=       next free golden-hour slots of a channel
  POST   /api/schedule        {kind, post_id|board_id, channel_id?, at, auto?, note?}
  PATCH  /api/schedule/{id}   {at?, channel_id?, auto?, note?, status?}   (status: planned|posted|skipped)
  DELETE /api/schedule/{id}
  POST   /api/schedule/{id}/publish                     publish now through the channel's Facebook Page
  GET    /api/schedule/hours                            the golden hours per platform (for the picker)
  GET    /api/schedule/facebook?from=&to=&channel_id=   posts that went up by hand on a connected Page (services/fb_sync)
  GET    /api/schedule/facebook/status                  when each connected Page was last read back
  POST   /api/schedule/facebook/sync {channel_id?, max_age?}   read the Pages' posts back now
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from flowboard.services import fb_sync, scheduler

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class SlotCreate(BaseModel):
    kind: str
    post_id: Optional[int] = None
    board_id: Optional[int] = None
    channel_id: Optional[int] = None
    at: str = Field(min_length=10, max_length=40)
    auto: bool = False
    note: Optional[str] = Field(default=None, max_length=300)
    fb_format: str = "post"
    fb_story: bool = False


class SlotPatch(BaseModel):
    at: Optional[str] = Field(default=None, min_length=10, max_length=40)
    channel_id: Optional[int] = None
    auto: Optional[bool] = None
    note: Optional[str] = Field(default=None, max_length=300)
    status: Optional[str] = None
    fb_format: Optional[str] = None
    fb_story: Optional[bool] = None


def _when(value: Optional[str]):
    if not value:
        return None
    try:
        return scheduler.parse_when(value)
    except scheduler.ScheduleError as exc:
        raise HTTPException(400, str(exc))


@router.get("")
def list_schedule(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = Query(None),
                  channel_id: Optional[int] = None, status: Optional[str] = None) -> dict[str, Any]:
    start = _when(from_)
    end = _when(to)
    if start is None and end is None:
        start = scheduler._now() - timedelta(days=7)
        end = scheduler._now() + timedelta(days=28)
    return {"items": scheduler.list_slots(start, end, channel_id=channel_id, status=status)}


@router.get("/reel-check")
def reel_check(kind: str, post_id: Optional[int] = None, board_id: Optional[int] = None) -> dict[str, Any]:
    """Can the item go out as a Facebook Reel (a video, 3–90 s, vertical-ish)? → {has_video, ok, reason}."""
    return scheduler.reel_check(kind, post_id, board_id)


@router.get("/due")
def due() -> dict[str, Any]:
    return {"items": scheduler.due_slots()}


@router.get("/hours")
def hours() -> dict[str, Any]:
    return {k: [t.strftime("%H:%M") for t in v] for k, v in scheduler.GOLDEN_HOURS.items()}


@router.get("/suggest")
def suggest(channel_id: int, limit: int = Query(6, ge=1, le=30), days: int = Query(7, ge=1, le=60)) -> dict[str, Any]:
    try:
        return {"items": scheduler.suggest_slots(channel_id, days=days, limit=limit)}
    except scheduler.ScheduleError as exc:
        raise HTTPException(400, str(exc))


class FbSyncBody(BaseModel):
    channel_id: Optional[int] = None
    # only Pages read longer ago than this (seconds) — what opening a page asks for
    max_age: Optional[float] = Field(default=None, ge=0)


@router.get("/facebook")
def facebook_posts(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = Query(None),
                   channel_id: Optional[int] = None) -> dict[str, Any]:
    start = _when(from_) or scheduler._now() - timedelta(days=7)
    end = _when(to) or scheduler._now() + timedelta(days=28)
    return {"items": fb_sync.list_manual(start, end, channel_id=channel_id), **fb_sync.status()}


@router.get("/facebook/status")
def facebook_status() -> dict[str, Any]:
    return fb_sync.status()


@router.post("/facebook/sync")
async def facebook_sync(body: FbSyncBody) -> dict[str, Any]:
    if body.channel_id is not None:
        try:
            return {"busy": False, "channels": [await fb_sync.sync_channel(body.channel_id)]}
        except fb_sync.SyncError as exc:
            raise HTTPException(400, str(exc))
    return await fb_sync.sync_all(max_age=body.max_age)


@router.post("", status_code=201)
def create_slot(body: SlotCreate) -> dict[str, Any]:
    when = _when(body.at)
    try:
        return scheduler.create(body.kind, when, post_id=body.post_id, board_id=body.board_id,
                                channel_id=body.channel_id, auto=body.auto, note=body.note or "", fb_format=body.fb_format,
                                fb_story=body.fb_story)
    except scheduler.ScheduleError as exc:
        raise HTTPException(400, str(exc))


@router.patch("/{slot_id}")
def patch_slot(slot_id: int, body: SlotPatch) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    if "at" in fields:
        fields["scheduled_at"] = _when(fields.pop("at"))
    try:
        return scheduler.update(slot_id, **fields)
    except scheduler.ScheduleError as exc:
        raise HTTPException(404 if "Không thấy lịch" in str(exc) else 400, str(exc))


@router.delete("/{slot_id}")
def delete_slot(slot_id: int) -> dict[str, Any]:
    if not scheduler.delete(slot_id):
        raise HTTPException(404, "không có lịch này")
    return {"ok": True}


@router.post("/{slot_id}/publish")
async def publish_slot(slot_id: int) -> dict[str, Any]:
    try:
        return await scheduler.publish(slot_id)
    except scheduler.ScheduleError as exc:
        raise HTTPException(404 if "Không thấy lịch" in str(exc) else 400, str(exc))
