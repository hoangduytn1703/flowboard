"""📡 Cào video kênh (services/channel_grab): the videos of YouTube / TikTok channels, listed to pick from.

  GET    /api/grab/status                    what can be listed, the scan sizes
  GET    /api/grab/channels                  the saved channels (counts, the scan in flight)
  POST   /api/grab/channels                  {url, tags?, limit?} — keep the channel of a link and scan it
  PATCH  /api/grab/channels/{id}             {tags?, note?, name?}
  DELETE /api/grab/channels/{id}             the channel and its list (downloaded videos stay)
  POST   /api/grab/channels/{id}/scan        {limit?} — read its newest videos again
  POST   /api/grab/channels/{id}/stop
  POST   /api/grab/scan-all                  {limit?}
  GET    /api/grab/channels/{id}/avatar
  GET    /api/grab/videos?channel_id=        the listed videos (all channels when left out)
  GET    /api/grab/videos/{id}/thumb
  GET    /api/grab/state                     scans + downloads in flight (cheap; the page polls it)
  POST   /api/grab/download                  {ids} — download the picked videos (two at a time)
  POST   /api/grab/download/stop             {ids?}
  POST   /api/grab/pick                      {ids, prompt} → {picks: [{id, why}], note} — the AI picks by title / numbers
  POST   /api/grab/media                     {ids} → [{id, media_id, name}] the downloaded ones (the cut / dubbing pages)
  POST   /api/grab/used                      {ids, tool: cut | dub} — remember they went on to that tool
  GET    /api/grab/marks                     the video labels in use (+ the ready-made ones) with counts
  POST   /api/grab/marks                     {ids, add?, remove?} — label videos ("Đã xử lý", "Đã đăng"…), kept by video
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from flowboard.db import get_session
from flowboard.db.models import GrabChannel, GrabVideo
from flowboard.services import channel_grab as grab

router = APIRouter(prefix="/api/grab", tags=["grab"])


class AddBody(BaseModel):
    url: str = Field(min_length=3, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    limit: Optional[int] = Field(default=None, ge=1, le=10000)


class EditBody(BaseModel):
    tags: Optional[list[str]] = Field(default=None, max_length=20)
    note: Optional[str] = Field(default=None, max_length=1000)
    name: Optional[str] = Field(default=None, max_length=200)


class ScanBody(BaseModel):
    limit: Optional[int] = Field(default=None, ge=1, le=10000)


class IdsBody(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=2000)


class PickBody(BaseModel):
    ids: list[int] = Field(max_length=2000)
    prompt: str = Field(max_length=4000)


class MarkBody(BaseModel):
    ids: list[int] = Field(max_length=20000)
    add: list[str] = Field(default_factory=list, max_length=20)
    remove: list[str] = Field(default_factory=list, max_length=20)


class UsedBody(BaseModel):
    ids: list[int] = Field(max_length=2000)
    tool: str = Field(pattern="^(cut|dub)$")


def _bad(exc: grab.GrabError, code: int = 400) -> HTTPException:
    return HTTPException(404 if str(exc).startswith("Không thấy") else code, str(exc))


@router.get("/status")
def status() -> dict[str, Any]:
    from flowboard.services import ytdlp

    return {"platforms": [{"key": k, **v} for k, v in grab.PLATFORMS.items()], "limits": grab.LIMITS,
            "max_limit": grab.MAX_LIMIT, "mark_presets": grab.MARK_PRESETS, "default_limit": grab.DEFAULT_LIMIT, "ytdlp": ytdlp.available(), "not_supported": grab.NOT_SUPPORTED,
            "max_minutes": grab.MAX_DURATION_S // 60, "pick_max": grab.PICK_MAX}


@router.get("/channels")
def list_channels() -> list[dict[str, Any]]:
    return grab.channels()


@router.post("/channels", status_code=201)
def add_channel(body: AddBody) -> dict[str, Any]:
    try:
        return grab.channel(grab.add_channel(body.url, body.tags, body.limit))
    except grab.GrabError as exc:
        raise _bad(exc)


@router.patch("/channels/{channel_id}")
def edit_channel(channel_id: int, body: EditBody) -> dict[str, Any]:
    try:
        return grab.update_channel(channel_id, tags=body.tags, note=body.note, name=body.name)
    except grab.GrabError as exc:
        raise _bad(exc)


@router.delete("/channels/{channel_id}")
def delete_channel(channel_id: int) -> dict[str, Any]:
    try:
        return {"deleted": True, "videos": grab.delete_channel(channel_id)}
    except grab.GrabError as exc:
        raise _bad(exc)


@router.post("/channels/{channel_id}/scan")
def scan(channel_id: int, body: ScanBody) -> dict[str, Any]:
    try:
        grab.start_scan(channel_id, body.limit)
        return grab.channel(channel_id)
    except grab.GrabError as exc:
        raise _bad(exc)


@router.post("/channels/{channel_id}/stop")
def stop_scan(channel_id: int) -> dict[str, Any]:
    grab.stop_scan(channel_id)
    return {"ok": True}


@router.post("/scan-all")
def scan_all(body: ScanBody) -> dict[str, Any]:
    return {"channels": grab.scan_all(body.limit)}


@router.get("/channels/{channel_id}/avatar")
def avatar(channel_id: int) -> FileResponse:
    path = grab.avatar_file(channel_id)
    if not path.is_file():
        with get_session() as db:
            ch = db.get(GrabChannel, channel_id)
        if ch is None or not ch.avatar or not grab.fetch_image(ch.avatar, path):
            raise HTTPException(404, "Kênh này chưa có ảnh")
    return FileResponse(path, media_type=grab.image_type(path), headers={"Cache-Control": "private, max-age=86400"})


@router.get("/videos")
def list_videos(channel_id: Optional[int] = Query(None)) -> list[dict[str, Any]]:
    return grab.videos(channel_id)


@router.get("/videos/{video_id}/thumb", response_model=None)
def thumb(video_id: int) -> FileResponse | RedirectResponse:
    path = grab.thumb_file(video_id)
    if not path.is_file():
        with get_session() as db:
            v = db.get(GrabVideo, video_id)
        if v is None:
            raise HTTPException(404, "Không thấy video")
        if not (v.thumb and grab.fetch_image(v.thumb, path)):
            if grab.local_media(v.media_id) is not None:  # the cover's link died: a frame of the downloaded file
                return RedirectResponse(f"/api/media/{v.media_id}/poster")
            raise HTTPException(404, "Video này chưa có ảnh bìa")
    return FileResponse(path, media_type=grab.image_type(path), headers={"Cache-Control": "private, max-age=86400"})


@router.get("/state")
def state() -> dict[str, Any]:
    return grab.state()


@router.post("/download")
def download(body: IdsBody) -> dict[str, Any]:
    if not body.ids:
        raise HTTPException(400, "Chọn ít nhất một video")
    return grab.download(body.ids)


@router.post("/download/stop")
def stop_download(body: IdsBody) -> dict[str, Any]:
    return {"stopping": grab.stop_downloads(body.ids or None)}


@router.post("/pick")
async def pick(body: PickBody) -> dict[str, Any]:
    try:
        return await grab.pick(body.ids, body.prompt)
    except grab.GrabError as exc:
        raise _bad(exc)


@router.post("/media")
def media(body: IdsBody) -> list[dict[str, Any]]:
    return grab.media_of(body.ids)


@router.get("/marks")
def marks() -> list[dict[str, Any]]:
    return grab.mark_tags()


@router.post("/marks")
def set_marks(body: MarkBody) -> dict[str, Any]:
    if not body.ids:
        raise HTTPException(400, "Chọn ít nhất một video")
    return {"marked": grab.set_marks(body.ids, body.add, body.remove)}


@router.post("/used")
def used(body: UsedBody) -> dict[str, Any]:
    try:
        return {"marked": grab.mark_used(body.ids, body.tool)}
    except grab.GrabError as exc:
        raise _bad(exc)
