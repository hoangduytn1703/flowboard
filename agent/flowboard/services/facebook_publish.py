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
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from flowboard import accounts

logger = logging.getLogger(__name__)

_TOKEN_IN_URL = re.compile(r"(access_token=)[^&\s\"']+")


class _RedactToken(logging.Filter):
    """httpx logs every request URL at INFO — Graph API GETs carry the Page
    token in the query string, which would land in the agent log as is."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(
                _TOKEN_IN_URL.sub(r"\1***", str(a)) if "access_token=" in str(a) else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
        if isinstance(record.msg, str) and "access_token=" in record.msg:
            record.msg = _TOKEN_IN_URL.sub(r"\1***", record.msg)
        return True


logging.getLogger("httpx").addFilter(_RedactToken())

GRAPH = "https://graph.facebook.com/v21.0"
GRAPH_VIDEO = "https://graph-video.facebook.com/v21.0"
TIMEOUT_S = 60.0
VIDEO_TIMEOUT_S = 600.0
MAX_PHOTOS = 4
#: Bigger videos go up in pieces (``upload_phase`` start → transfer → finish): one 152 MB request got
#: "413 Request Entity Too Large" from graph-video (28/10, a 3:35 dubbed clip).
CHUNKED_ABOVE = 20 * 1024 * 1024
MAX_VIDEO_BYTES = int(1.75 * 1024 * 1024 * 1024)  # the chunked upload's limit (and 45 minutes)
CHUNK_TRIES = 3
#: Reels through the API (developers.facebook.com/docs/video-api/guides/reels-publishing) say 3–90 s, between 9:16
#: and 16:9, ≥ 540 px on the short side; a Page publishes ≤ 30 posts a day through the API. The Facebook app takes
#: far longer Reels (the user posted a 3:00 one by hand, 28/10), so only < 3 s blocks — the rest is a warning and
#: Facebook decides.
REEL_MIN_S = 3.0
REEL_MAX_S = 90.0
REEL_MIN_SIDE = 540
REEL_READY_WAIT_S = 120.0


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


#: "is this channel connected?" remembered for a short while: the token lives in the central store (a cloud round trip,
#: ~0.15 s) and every channel list asks it for every channel. Publishing always reads the token itself.
HAS_TOKEN_TTL_S = 120.0
_has_token: dict[str, tuple[float, bool]] = {}


def has_token(channel_id: int) -> bool:
    key = token_key(channel_id)
    hit = _has_token.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < HAS_TOKEN_TTL_S:
        return hit[1]
    value = bool(get_token(channel_id))
    _has_token[key] = (now, value)
    return value


def set_token(channel_id: int, token: Optional[str]) -> None:
    accounts.set_setting(token_key(channel_id), token or "")
    _has_token.pop(token_key(channel_id), None)


def _error_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        err = {}
    code, msg = err.get("code"), str(err.get("message") or resp.text[:200])
    if resp.status_code == 413:
        return "Facebook từ chối: file gửi lên quá lớn cho một lần tải."
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


async def _upload_video_chunked(client: httpx.AsyncClient, page_id: str, token: str, video: Path, message: str) -> str:
    """A big video in pieces: ``start`` (size) → ``transfer`` the byte range Facebook asks for, again and
    again → ``finish`` (with the post text). Returns the video id (its post, as with a one-shot upload)."""
    url = f"{GRAPH_VIDEO}/{page_id}/videos"
    size = video.stat().st_size
    start = await _post(client, url, {"upload_phase": "start", "file_size": str(size), "access_token": token})
    session = str(start.get("upload_session_id") or "")
    video_id = str(start.get("video_id") or "")
    if not session:
        raise FacebookError("Facebook không mở được phiên tải video lên.")
    a, b = int(start.get("start_offset") or 0), int(start.get("end_offset") or 0)
    rounds = 0
    with video.open("rb") as fh:
        while a < b:
            rounds += 1
            if rounds > 5000:
                raise FacebookError("Tải video lên Facebook không xong (quá nhiều lượt).")
            fh.seek(a)
            chunk = fh.read(b - a)
            for attempt in range(CHUNK_TRIES):
                try:
                    out = await _post(client, url, {"upload_phase": "transfer", "upload_session_id": session,
                                                    "start_offset": str(a), "access_token": token},
                                      files={"video_file_chunk": (video.name, chunk, "application/octet-stream")})
                    break
                except httpx.TransportError as exc:  # a dropped connection: send the same piece again
                    if attempt == CHUNK_TRIES - 1:
                        raise FacebookError(f"Mất kết nối khi tải video lên Facebook: {exc}") from exc
            a, b = int(out.get("start_offset") or b), int(out.get("end_offset") or b)
    done = await _post(client, url, {"upload_phase": "finish", "upload_session_id": session, "description": message,
                                     "access_token": token})
    if done.get("success") is False:
        raise FacebookError("Facebook không hoàn tất video vừa tải lên.")
    return video_id or str(done.get("video_id") or done.get("id") or "")


def reel_problem(video: Path) -> Optional[str]:
    """Why this file cannot be a Reel at all (in Vietnamese), or None."""
    from flowboard.services.video_export import probe_clip

    info = probe_clip(video)
    if info is None or info.duration <= 0:
        return "Không đọc được video để kiểm tra làm Reel."
    if info.duration < REEL_MIN_S:
        return f"Reel phải dài ít nhất {REEL_MIN_S:g} giây — video này {info.duration:.1f} s."
    return None


def reel_warning(video: Path) -> Optional[str]:
    """What may make Facebook turn the Reel down (outside what its API documents) — said, not blocked."""
    from flowboard.services.video_export import probe_clip

    info = probe_clip(video)
    if info is None:
        return None
    # Length is not checked: the API docs say 90 s, but a 10:51 Reel was accepted on 29/10 — Facebook decides.
    notes = []
    if info.width / max(1, info.height) > 16 / 9 + 0.01:
        notes.append("video ngang hơn 16:9")
    if min(info.width, info.height) < REEL_MIN_SIDE:
        notes.append(f"video {info.width}×{info.height} nhỏ hơn chuẩn Reel (cạnh ngắn {REEL_MIN_SIDE} px)")
    if not notes:
        return None
    return "Lưu ý: " + "; ".join(notes) + ". Tool vẫn thử đăng Reel — Facebook từ chối thì đăng lại dạng bài viết."


async def _wait_reel(client: httpx.AsyncClient, video_id: str, token: str) -> None:
    """Facebook processes a Reel after "finish"; wait (bounded) so the first comment lands on a live post."""
    import asyncio

    loop = asyncio.get_running_loop()
    end = loop.time() + REEL_READY_WAIT_S
    while loop.time() < end:
        try:
            st = (await _get(client, video_id, fields="status", access_token=token)).get("status") or {}
        except FacebookError:
            return
        live = st.get("video_status") in ("ready", "published")
        if live or (st.get("publishing_phase") or {}).get("status") == "complete":
            return
        if st.get("video_status") in ("error", "upload_failed", "expired"):
            raise FacebookError("Facebook xử lý Reel bị lỗi — thử đăng lại hoặc đăng dạng bài viết.")
        await asyncio.sleep(REEL_POLL_S)


REEL_POLL_S = 5.0


async def publish_reel(channel_id: int, page_id: str, message: str, *, video: Path,
                       first_comment: str = "") -> dict[str, Any]:
    """A Reel on the Page: ``video_reels`` start → the file to ``rupload.facebook.com`` → finish
    (``video_state=PUBLISHED``, the caption as ``description``) → the first comment once it is live."""
    token = get_token(channel_id)
    if not token:
        raise FacebookError("Kênh này chưa kết nối Facebook Page — vào Kênh của tôi → Kết nối Facebook Page.")
    if not page_id:
        raise FacebookError("Kênh chưa có Page id — kết nối lại Facebook Page.")
    if not video.is_file():
        raise FacebookError("Không thấy file video trên máy này.")
    why = reel_problem(video)
    if why is not None:
        raise FacebookError(why)
    size = video.stat().st_size
    async with httpx.AsyncClient(timeout=VIDEO_TIMEOUT_S) as client:
        start = await _post(client, f"{GRAPH}/{page_id}/video_reels", {"upload_phase": "start", "access_token": token})
        video_id = str(start.get("video_id") or "")
        if not video_id:
            raise FacebookError("Facebook không mở được phiên tải Reel lên.")
        upload_url = str(start.get("upload_url") or f"https://rupload.facebook.com/video-upload/v21.0/{video_id}")
        data = video.read_bytes()
        offset = 0
        for attempt in range(CHUNK_TRIES):
            try:
                resp = await client.post(upload_url, content=data[offset:], headers={
                    "Authorization": f"OAuth {token}", "offset": str(offset), "file_size": str(size),
                    "Content-Type": "application/octet-stream"})
                if resp.status_code >= 400:
                    raise FacebookError(_error_message(resp))
                break
            except httpx.TransportError as exc:  # resume where Facebook says it got to
                if attempt == CHUNK_TRIES - 1:
                    raise FacebookError(f"Mất kết nối khi tải Reel lên Facebook: {exc}") from exc
                try:
                    st = (await _get(client, video_id, fields="status", access_token=token)).get("status") or {}
                    offset = int((st.get("uploading_phase") or {}).get("bytes_transfered") or 0)
                except (FacebookError, ValueError):
                    offset = 0
        done = await _post(client, f"{GRAPH}/{page_id}/video_reels", {
            "upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED",
            "description": (message or "").strip(), "access_token": token})
        if done.get("success") is False:
            raise FacebookError("Facebook không đăng được Reel.")
        await _wait_reel(client, video_id, token)
        comment_id = ""
        if first_comment.strip():
            try:
                c = await _post(client, f"{GRAPH}/{video_id}/comments", {"message": first_comment.strip(), "access_token": token})
                comment_id = str(c.get("id") or "")
            except FacebookError as exc:
                logger.warning("facebook: first comment failed on reel %s: %s", video_id, exc)
                comment_id = f"error: {exc}"
        try:
            info = await _get(client, video_id, fields="permalink_url", access_token=token)
            permalink = str(info.get("permalink_url") or "")
            if permalink.startswith("/"):
                permalink = "https://www.facebook.com" + permalink
        except FacebookError:
            permalink = ""
    return {"post_id": video_id, "permalink": permalink or f"https://www.facebook.com/reel/{video_id}",
            "comment_id": comment_id, "format": "reel"}


#: Page Stories: a video story is at most 60 s (Meta, Page Stories API); a longer clip goes up as its first part.
STORY_MAX_VIDEO_S = 60.0
STORY_CUT_S = 59.5
STORY_MAX_PHOTO_BYTES = 10 * 1024 * 1024


def story_video(video: Path) -> tuple[Path, str]:
    """The file a video story uses, and a note: a clip over 60 s is cut to its first 59.5 s (stream copy, next to it)."""
    from flowboard.services.video_export import probe_clip

    info = probe_clip(video)
    if info is None or info.duration <= STORY_MAX_VIDEO_S:
        return video, ""
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise FacebookError("Video dài hơn 60 giây mà máy không có ffmpeg để cắt — tin trên Page tối đa 60 giây.")
    out = Path(tempfile.gettempdir()) / f"story-{video.stem}.mp4"
    try:
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(video), "-t", str(STORY_CUT_S), "-c", "copy",
                        "-movflags", "+faststart", str(out)], capture_output=True, timeout=180, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise FacebookError(f"Không cắt được video cho tin: {exc}") from exc
    return out, f"video dài {round(info.duration)} giây nên tin lấy 60 giây đầu"


async def publish_story(channel_id: int, page_id: str, *, photo: Optional[Path] = None,
                        video: Optional[Path] = None) -> dict[str, Any]:
    """"📲 Thêm vào tin": a Page Story with ``video`` (``video_stories`` start → file to rupload → finish) or else
    ``photo`` (uploaded again unpublished — a photo of a published post cannot be reused — then ``photo_stories``).
    Returns ``{post_id, kind, note}``."""
    token = get_token(channel_id)
    if not token:
        raise FacebookError("Kênh này chưa kết nối Facebook Page.")
    if not page_id:
        raise FacebookError("Kênh chưa có Page id — kết nối lại Facebook Page.")
    if video is None and photo is None:
        raise FacebookError("Tin cần ảnh hoặc video — bài này không có chữ, ảnh hay video nào.")
    async with httpx.AsyncClient(timeout=VIDEO_TIMEOUT_S if video else TIMEOUT_S) as client:
        if video is not None:
            if not video.is_file():
                raise FacebookError("Không thấy file video cho tin trên máy này.")
            path, note = story_video(video)
            start = await _post(client, f"{GRAPH}/{page_id}/video_stories", {"upload_phase": "start", "access_token": token})
            video_id = str(start.get("video_id") or "")
            if not video_id:
                raise FacebookError("Facebook không mở được phiên tải tin lên.")
            upload_url = str(start.get("upload_url") or f"https://rupload.facebook.com/video-upload/v21.0/{video_id}")
            data = path.read_bytes()
            resp = await client.post(upload_url, content=data, headers={
                "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data)),
                "Content-Type": "application/octet-stream"})
            if resp.status_code >= 400:
                raise FacebookError(_error_message(resp))
            done = await _post(client, f"{GRAPH}/{page_id}/video_stories",
                               {"upload_phase": "finish", "video_id": video_id, "access_token": token})
            if done.get("success") is False:
                raise FacebookError("Facebook không đăng được tin video.")
            return {"post_id": str(done.get("post_id") or video_id), "kind": "video", "note": note}
        assert photo is not None
        if not photo.is_file():
            raise FacebookError("Không thấy file ảnh cho tin trên máy này.")
        if photo.stat().st_size > STORY_MAX_PHOTO_BYTES:
            raise FacebookError("Ảnh lớn hơn 10 MB — tin trên Page không nhận.")
        with photo.open("rb") as fh:
            up = await _post(client, f"{GRAPH}/{page_id}/photos", {"published": "false", "access_token": token},
                             files={"source": (photo.name, fh, _guess_mime(photo))})
        photo_id = str(up.get("id") or "")
        if not photo_id:
            raise FacebookError("Facebook không nhận ảnh cho tin.")
        done = await _post(client, f"{GRAPH}/{page_id}/photo_stories", {"photo_id": photo_id, "access_token": token})
        if done.get("success") is False:
            raise FacebookError("Facebook không đăng được tin ảnh.")
        return {"post_id": str(done.get("post_id") or photo_id), "kind": "photo", "note": ""}


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
                raise FacebookError("Video lớn hơn 1,75 GB — Facebook không nhận.")
            if video.stat().st_size > CHUNKED_ABOVE:
                post_id = await _upload_video_chunked(client, page_id, token, video, message)
            else:
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
