"""Clip from a reference ad video: upload it, let Gemini analyse it against
a product, build the board.

Three calls so the user sees the analysis (and the mismatch verdict)
before any board exists:

1. ``POST /api/reference-video/upload``  multipart → ``{media_id}``
2. ``POST /api/reference-video/analyze`` ``{media_id, product_id?}`` → analysis
3. ``POST /api/reference-video/build``   ``{media_id, product_id?, analysis, name?, force?}``
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.services import media as media_service
from flowboard.services import product_link, reference_video
from flowboard.services.llm import gemini_api
from flowboard.services.products import get_product
from flowboard.services.templates import PersonRequiredError
from flowboard.services.product_gender import GenderMismatchError
from flowboard.services.video_export import probe_clip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reference-video", tags=["reference-video"])

_EXT_BY_MIME = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
}


@router.post("/upload")
async def upload_reference_video(file: UploadFile = File(...)) -> dict[str, Any]:
    """Store the ad video locally (it never goes to Flow) and register it
    as a video Asset so the media route can serve it back."""
    mime = (file.content_type or "").lower().split(";")[0].strip()
    ext = _EXT_BY_MIME.get(mime)
    if ext is None:
        # Browsers label .mov / .mkv inconsistently; trust the extension then.
        guess = Path(file.filename or "").suffix.lower()
        if guess in _EXT_BY_MIME.values():
            ext, mime = guess, next(m for m, e in _EXT_BY_MIME.items() if e == guess)
        else:
            raise HTTPException(415, f"unsupported video type {mime or guess!r}; use mp4 / mov / webm")
    import asyncio

    media_id = uuid.uuid4().hex
    media_service.MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = media_service.MEDIA_CACHE_DIR / f"{media_id}{ext}"
    # No size limit (a 60-minute video for "Cắt video" is easily 1–2 GB): copied to disk in chunks, never held in memory.
    try:
        size = await asyncio.to_thread(_save_upload, file.file, path)
    except OSError as exc:
        raise HTTPException(507, f"Không lưu được video (ổ đĩa đầy?): {exc}")
    if not size:
        raise HTTPException(400, "empty file")
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(path), mime=mime))
        s.commit()
    info = probe_clip(path)
    logger.info("reference-video: stored %s (%d bytes, %.1fs)", media_id, size, info.duration if info else -1)
    return {"media_id": media_id, "mime": mime, "size": size,
            "duration_s": round(info.duration, 1) if info else None,
            "width": info.width if info else None, "height": info.height if info else None}


def _save_upload(src: Any, dest: Path) -> int:
    """Copy an uploaded file to ``dest`` through a ``.part`` file; returns its size (0 = empty, nothing kept)."""
    import os
    import shutil

    part = dest.with_name(dest.name + ".part")
    try:
        with open(part, "wb") as fh:
            shutil.copyfileobj(src, fh, 1 << 20)
        size = part.stat().st_size
        if size:
            os.replace(part, dest)
        return size
    finally:
        part.unlink(missing_ok=True)


def _video_path(media_id: str) -> Path:
    media_id = media_service.normalize_media_id(media_id)
    if not media_service.is_valid_media_id(media_id):
        raise HTTPException(400, "invalid media_id")
    with get_session() as s:
        row = s.exec(select(Asset).where(Asset.uuid_media_id == media_id)).first()
    if row is None or row.kind != "video" or not row.local_path or not Path(row.local_path).is_file():
        raise HTTPException(404, "reference video not found — upload it first")
    return Path(row.local_path)


def _product_or_404(product_id: Optional[int]) -> Optional[dict]:
    if product_id is None:
        return None
    product = get_product(product_id)
    if product is None:
        raise HTTPException(404, f"unknown product {product_id}")
    return product


class AnalyzeBody(BaseModel):
    media_id: str
    product_id: Optional[int] = None
    scenes: Optional[int] = Field(default=None, ge=2, le=6)
    model: Optional[str] = None
    # "🔇 Không lời": scenes written for no voice-over (no narration_vi).
    voiceless: bool = False


@router.post("/analyze")
async def analyze_reference_video(body: AnalyzeBody) -> dict[str, Any]:
    """Gemini's breakdown of the video and the plan adapted to the product.
    ``blocked`` is true when the product does not fit the video; the build
    call then needs ``force``."""
    path = _video_path(body.media_id)
    product = _product_or_404(body.product_id)
    if not gemini_api.configured():
        raise HTTPException(400, "Chưa có Gemini API key — thêm trong Settings → Gemini API keys.")
    try:
        analysis = await reference_video.analyze(
            path, product, scenes=body.scenes, model=body.model or gemini_api.DEFAULT_MODEL,
            voiceless=body.voiceless,
        )
    except reference_video.ReferenceVideoError as exc:
        raise HTTPException(502, str(exc))
    return {"media_id": body.media_id, "product": product, "analysis": analysis,
            "blocked": analysis["blocked"], "block_reason": analysis.get("block_reason")}


class AnalyzeLinkBody(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    product_id: Optional[int] = None
    scenes: Optional[int] = Field(default=None, ge=2, le=6)
    model: Optional[str] = None
    voiceless: bool = False


@router.post("/analyze-link")
async def analyze_product_link(body: AnalyzeLinkBody) -> dict[str, Any]:
    """Same plan as ``/analyze`` but from a product page instead of a video;
    the result is built with ``/build`` (no ``media_id``)."""
    product = _product_or_404(body.product_id)
    if not gemini_api.configured():
        raise HTTPException(400, "Chưa có Gemini API key — thêm trong Settings → Gemini API keys.")
    try:
        analysis = await product_link.analyze(
            body.url, product, scenes=body.scenes, model=body.model, voiceless=body.voiceless,
        )
    except product_link.ProductLinkError as exc:
        raise HTTPException(502, str(exc))
    return {"product": product, "analysis": analysis,
            "blocked": analysis["blocked"], "block_reason": analysis.get("block_reason")}


class BuildBody(BaseModel):
    media_id: Optional[str] = None  # None: the plan came from a product link
    source_url: Optional[str] = Field(default=None, max_length=2000)
    product_id: Optional[int] = None
    analysis: dict
    name: Optional[str] = Field(default=None, max_length=80)
    force: bool = False
    # The model the user picked on the review screen; None keeps the AI's suggestion.
    character: Optional[dict] = None
    channel_id: Optional[int] = None
    # "🔇 Không lời" picked (or kept) on the review screen: no voice lines on the clip.
    voiceless: bool = False


@router.post("/build")
def build_from_reference(body: BuildBody) -> dict[str, Any]:
    """The board for a plan the user has reviewed. A mismatching product is
    refused (409) unless ``force`` says they know."""
    if body.media_id is not None:
        _video_path(body.media_id)
    product = _product_or_404(body.product_id)
    try:
        analysis = reference_video.normalize(body.analysis, product, voiceless=body.voiceless)
    except reference_video.ReferenceVideoError as exc:
        raise HTTPException(400, str(exc))
    if analysis["blocked"] and not body.force:
        raise HTTPException(409, analysis.get("block_reason") or "sản phẩm không khớp video mẫu")
    try:
        return reference_video.build_board(
            analysis, product, name=body.name,
            source_media_id=media_service.normalize_media_id(body.media_id) if body.media_id else None,
            source_url=body.source_url, character_pick=body.character, channel_id=body.channel_id,
            voiceless=body.voiceless,
        )
    except (PersonRequiredError, GenderMismatchError) as exc:
        raise HTTPException(400, str(exc))


# ── from a link (TikTok / YouTube / …) ────────────────────────────────────

_ALLOWED_HOSTS = (
    "tiktok.com", "youtube.com", "youtu.be", "instagram.com", "facebook.com", "fb.watch",
    "douyin.com", "iesdouyin.com", "x.com", "twitter.com",
)
#: a 60-minute video for "Cắt video" at 720p is several hundred MB
FETCH_TIMEOUT_S = 1800


class FetchBody(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


def _host_allowed(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _ALLOWED_HOSTS)


def _run_ytdlp(url: str, media_id: str, max_duration_s: Optional[float] = None) -> tuple[Optional[Path], str, str]:
    """Download ``url`` as ``<media_id>.mp4`` (≤ 720p, any size; longer than ``max_duration_s`` is refused before the
    download). Returns ``(path, title, error_tail)``. yt-dlp is this machine's or the agent's own copy (services/ytdlp)."""
    import subprocess

    from flowboard.services import ytdlp as ytdlp_tool

    try:
        ytdlp = ytdlp_tool.ensure()
    except ytdlp_tool.YtdlpError as exc:
        return None, "", f"chưa có công cụ tải video yt-dlp: {exc}"
    out_dir = media_service.MEDIA_CACHE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    limit = ["--match-filter", f"duration <=? {int(max_duration_s)}"] if max_duration_s else []
    cmd = [
        ytdlp,
        # The POT-provider plugin on this machine times out; nothing here
        # needs it for the formats below.
        "--no-plugin-dirs", "--no-playlist", "--no-progress", "--no-simulate",
        "--encoding", "utf-8", *ytdlp_tool.js_args(), *limit,
        "-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "--merge-output-format", "mp4",
        "--print", "after_move:title::%(title)s",
        "-o", str(out_dir / f"{media_id}.%(ext)s"),
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=FETCH_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return None, "", f"tải quá {FETCH_TIMEOUT_S}s"
    except OSError as exc:
        return None, "", f"không chạy được yt-dlp: {exc}"
    stdout = proc.stdout.decode("utf-8", "replace")
    stderr = proc.stderr.decode("utf-8", "replace").strip()
    title = next((line.split("title::", 1)[1].strip() for line in stdout.splitlines() if "title::" in line), "")
    path = next((p for p in out_dir.glob(f"{media_id}.*") if p.suffix.lower() in (".mp4", ".webm", ".mov", ".mkv")), None)
    # yt-dlp skips a video the filter refuses and still exits 0; with --print it does not always say why (seen on
    # Windows: nothing on stdout / stderr) — so "exit 0 and no file" is that refusal too
    if path is None and max_duration_s and ("does not pass filter" in stdout + stderr or proc.returncode == 0):
        return None, title, f"video dài hơn {max_duration_s / 60:.0f} phút — chọn video ngắn hơn"
    if proc.returncode != 0 or path is None:
        tail = [l for l in stderr.splitlines() if l.startswith("ERROR")] or stderr.splitlines()[-3:]
        return None, title, " ".join(tail)[-400:] or f"yt-dlp exited {proc.returncode}"
    return path, title, ""


@router.post("/fetch")
async def fetch_reference_video(body: FetchBody) -> dict[str, Any]:
    """Download a TikTok / YouTube / … link with yt-dlp and register it like
    an upload, so the link can be analysed without a manual download."""
    import asyncio

    from flowboard.services.video_fetch import FetchError, extract_url, fetch_video

    # A whole Douyin / TikTok "share" blurb may be pasted; the link is dug out of it.
    url = extract_url(body.url) or body.url.strip()
    if not _host_allowed(url):
        raise HTTPException(400, "Link phải là TikTok, YouTube, Instagram, Facebook, Douyin hoặc X")
    media_id = uuid.uuid4().hex
    try:
        path, title = await asyncio.to_thread(fetch_video, url, media_id, media_service.MEDIA_CACHE_DIR)
    except FetchError as exc:
        raise HTTPException(502, f"Không tải được video: {exc}")
    mime = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}[path.suffix.lower()]
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(path), mime=mime))
        s.commit()
    info = probe_clip(path)
    logger.info("reference-video: fetched %s → %s (%.1fs)", url[:80], media_id, info.duration if info else -1)
    return {"media_id": media_id, "mime": mime, "size": path.stat().st_size,
            "duration_s": round(info.duration, 1) if info else None,
            "width": info.width if info else None, "height": info.height if info else None,
            "title": title, "url": url}
