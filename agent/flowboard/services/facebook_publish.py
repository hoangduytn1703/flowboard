"""Publishing to a Facebook Page through the Graph API ("tự đăng").

A channel is connected once with a Page access token (the seller pastes a
token from Graph API Explorer; a *user* token is accepted too, and the
page tokens behind it are listed to pick from). The token is kept in the
central settings store under ``fb_token:<owner>:<channel id>``, never in
the channel row that goes to the browser.

What gets published: a text post, optionally with up to 4 photos
(uploaded unpublished, then attached), or a video post (multipart upload
to graph-video); then the first comment under it (the affiliate link).
Personal profiles and groups cannot be posted to through the API — this
is for Pages only.
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Optional

import httpx

from flowboard import accounts

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v21.0"
GRAPH_VIDEO = "https://graph-video.facebook.com/v21.0"
TIMEOUT_S = 60.0
VIDEO_TIMEOUT_S = 600.0
MAX_PHOTOS = 4
MAX_VIDEO_BYTES = 1024 * 1024 * 1024  # the non-resumable upload limit


class FacebookError(RuntimeError):
    """The message is written for the person in front of the screen."""


def _owner() -> str:
    user = accounts.active_user()
    return str(user["username"]) if user else "local"


def token_key(channel_id: int) -> str:
    return f"fb_token:{_owner()}:{int(channel_id)}"


def get_token(channel_id: int) -> Optional[str]:
    tok = accounts.get_setting(token_key(channel_id))
    return str(tok) if tok else None


def set_token(channel_id: int, token: Optional[str]) -> None:
    accounts.set_setting(token_key(channel_id), token or "")


def _error_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        err = {}
    code, msg = err.get("code"), str(err.get("message") or resp.text[:200])
    if code == 190 or "access token" in msg.lower():
        return "Token Facebook hết hạn hoặc không hợp lệ — vào Kênh → Kết nối Facebook Page, dán token mới."
    if code in (200, 10) or "permission" in msg.lower():
        return ("Token thiếu quyền đăng bài (cần pages_manage_posts, pages_read_engagement). "
                "Tạo lại token với đủ quyền rồi dán lại.")
    return f"Facebook từ chối ({code or resp.status_code}): {msg}"


async def _get(client: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    resp = await client.get(f"{GRAPH}/{path}", params=params)
    if resp.status_code >= 400:
        raise FacebookError(_error_message(resp))
    return resp.json()


async def _post(client: httpx.AsyncClient, url: str, data: dict[str, Any], files: Optional[dict] = None) -> dict[str, Any]:
    resp = await client.post(url, data=data, files=files)
    if resp.status_code >= 400:
        raise FacebookError(_error_message(resp))
    body = resp.json()
    if not isinstance(body, dict):
        raise FacebookError("Facebook trả về dữ liệu lạ.")
    return body


async def inspect_token(token: str) -> dict[str, Any]:
    """What a pasted token is: ``{kind: "page"|"user", id, name, pages: [{id, name, access_token}]}``.
    A user token lists the pages it manages (each with its own page token);
    a page token names its page."""
    token = (token or "").strip()
    if len(token) < 20:
        raise FacebookError("Token quá ngắn — dán nguyên chuỗi access token từ Graph API Explorer.")
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        me = await _get(client, "me", fields="id,name", access_token=token)
        pages: list[dict[str, Any]] = []
        try:
            acc = await _get(client, "me/accounts", fields="id,name,access_token", access_token=token, limit=50)
            pages = [{"id": str(p["id"]), "name": str(p.get("name") or ""), "access_token": str(p.get("access_token") or "")}
                     for p in acc.get("data") or [] if p.get("id")]
        except FacebookError:
            pages = []  # a page token has no /me/accounts
        if pages:
            return {"kind": "user", "id": str(me["id"]), "name": str(me.get("name") or ""), "pages": pages}
        # No managed pages listed: either a page token (good) or a user with no pages.
        try:
            page = await _get(client, str(me["id"]), fields="id,name,category", access_token=token)
            if page.get("category"):
                return {"kind": "page", "id": str(page["id"]), "name": str(page.get("name") or ""),
                        "pages": [{"id": str(page["id"]), "name": str(page.get("name") or ""), "access_token": token}]}
        except FacebookError:
            pass
        raise FacebookError("Token này không quản lý Page nào. Tạo token bằng tài khoản là admin của Page, "
                            "chọn quyền pages_show_list + pages_manage_posts + pages_read_engagement.")


def _guess_mime(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


async def publish_post(channel_id: int, page_id: str, message: str, *, photos: Optional[list[Path]] = None,
                       video: Optional[Path] = None, first_comment: str = "") -> dict[str, Any]:
    """Publish and return ``{post_id, permalink, comment_id}``. Photos and
    video are files on this machine; at most :data:`MAX_PHOTOS` photos, and
    a video replaces the photos."""
    token = get_token(channel_id)
    if not token:
        raise FacebookError("Kênh này chưa kết nối Facebook Page — vào Kênh của tôi → Kết nối Facebook Page.")
    if not page_id:
        raise FacebookError("Kênh chưa có Page id — kết nối lại Facebook Page.")
    message = (message or "").strip()
    if not message and not video and not photos:
        raise FacebookError("Bài trống, không có gì để đăng.")
    async with httpx.AsyncClient(timeout=VIDEO_TIMEOUT_S if video else TIMEOUT_S) as client:
        if video is not None:
            if not video.is_file():
                raise FacebookError("Không thấy file video của clip trên máy này.")
            if video.stat().st_size > MAX_VIDEO_BYTES:
                raise FacebookError("Video lớn hơn 1 GB — Facebook không nhận qua cách tải này.")
            with video.open("rb") as fh:
                out = await _post(client, f"{GRAPH_VIDEO}/{page_id}/videos",
                                  {"description": message, "access_token": token},
                                  files={"source": (video.name, fh, _guess_mime(video))})
            post_id = str(out.get("id") or "")
        else:
            attached: list[str] = []
            for p in (photos or [])[:MAX_PHOTOS]:
                if not p.is_file():
                    continue
                with p.open("rb") as fh:
                    up = await _post(client, f"{GRAPH}/{page_id}/photos",
                                     {"published": "false", "access_token": token},
                                     files={"source": (p.name, fh, _guess_mime(p))})
                if up.get("id"):
                    attached.append(str(up["id"]))
            data: dict[str, Any] = {"message": message, "access_token": token}
            for i, fbid in enumerate(attached):
                data[f"attached_media[{i}]"] = '{"media_fbid":"%s"}' % fbid
            out = await _post(client, f"{GRAPH}/{page_id}/feed", data)
            post_id = str(out.get("id") or out.get("post_id") or "")
        if not post_id:
            raise FacebookError("Facebook không trả về id bài đăng.")
        comment_id = ""
        if first_comment.strip():
            try:
                c = await _post(client, f"{GRAPH}/{post_id}/comments", {"message": first_comment.strip(), "access_token": token})
                comment_id = str(c.get("id") or "")
            except FacebookError as exc:
                # A video post may not accept comments for a few seconds while it
                # processes; the post itself is up, so this is reported, not fatal.
                logger.warning("facebook: first comment failed on %s: %s", post_id, exc)
                comment_id = f"error: {exc}"
        permalink = ""
        try:
            info = await _get(client, post_id, fields="permalink_url", access_token=token)
            permalink = str(info.get("permalink_url") or "")
        except FacebookError:
            permalink = f"https://www.facebook.com/{post_id}"
    return {"post_id": post_id, "permalink": permalink, "comment_id": comment_id}
