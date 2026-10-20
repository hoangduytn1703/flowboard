"""Image generation through a paid API instead of Google Flow.

Flow is the default renderer (worker ``_handle_gen_image``) and the only one
that can turn an image into a video. This module adds two alternatives for
the *image* step — OpenAI GPT Image and xAI Grok Imagine — for users whose
Flow credits ran out or who already pay for one of those APIs.

The output is pushed back INTO the pinned Flow project through the same
upload path the user-upload route uses (``routes/upload.py::
_ingest_image_bytes``), so the result is an ordinary Flow media id: the node
renders it via ``/media/<id>`` and the video step can use it as an
ingredient exactly like a Flow-made image.

Request shapes verified against the providers' docs (October 2026):

* OpenAI ``POST /v1/images/generations`` — ``model``, ``prompt``, ``size``
  (``1024x1024`` / ``1536x1024`` / ``1024x1536``), ``quality``. GPT image
  models always return ``data[].b64_json``; ``response_format`` is rejected
  for them, so it is not sent. With reference images the call becomes
  ``POST /v1/images/edits`` (multipart, ``image[]`` files, same fields).
* xAI ``POST /v1/images/generations`` — ``model``, ``prompt``,
  ``aspect_ratio``, ``response_format: b64_json``. No reference-image input
  on this endpoint, so product photos cannot condition the render; the
  settings UI says so.

Keys live in ``~/.flowboard/secrets.json`` under ``apiKeys.openai`` /
``apiKeys.xai`` (``services/llm/secrets.py``). ``openai`` is deliberately
shared with the LLM provider layer: one key, one place to paste it.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Optional

import httpx

from flowboard.services import media as media_service
from flowboard.services.llm import secrets

logger = logging.getLogger(__name__)

OPENAI_BASE = "https://api.openai.com/v1"
XAI_BASE = "https://api.x.ai/v1"
OPENAI_MODEL = "gpt-image-1"
# `grok-2-image` was the first-generation model; the current docs only list
# `grok-imagine-image-2.0` for /v1/images/generations and it accepts
# `aspect_ratio`, which the old model did not.
XAI_MODEL = "grok-imagine-image-2.0"
GENERATE_TIMEOUT_S = 180.0
TEST_TIMEOUT_S = 20.0
MAX_VARIANTS = 4
# Fetched bytes bigger than this are not sent as a reference (OpenAI caps
# edit inputs at 50 MB, but the Flow upload cache never holds that much).
MAX_REFERENCE_BYTES = 20 * 1024 * 1024

PROVIDERS: dict[str, dict[str, Any]] = {
    "flow": {
        "label": "Google Flow",
        "model": None,
        "notes_vi": "Mặc định. Dùng credit của gói Flow Pro/Ultra qua extension Chrome; "
                    "nhận ảnh sản phẩm làm tham chiếu.",
    },
    "openai": {
        "label": "OpenAI GPT Image",
        "model": OPENAI_MODEL,
        "notes_vi": "Tính tiền theo ảnh (chất lượng medium). Nhận ảnh sản phẩm làm tham chiếu "
                    "(qua /images/edits). Ảnh tạo xong vẫn được đưa vào Flow để làm nguyên liệu video.",
    },
    "xai": {
        "label": "xAI Grok Image",
        "model": XAI_MODEL,
        "notes_vi": "Tính tiền theo ảnh. KHÔNG nhận ảnh tham chiếu nên sản phẩm trong ảnh có thể lệch "
                    "so với ảnh thật. Ảnh tạo xong vẫn được đưa vào Flow để làm nguyên liệu video.",
    },
}
API_PROVIDERS: tuple[str, ...] = ("openai", "xai")


class ImageProviderError(Exception):
    """A provider call failed; ``str(exc)`` is the Vietnamese message shown to the user."""


# ── helpers ────────────────────────────────────────────────────────────


def is_api_provider(provider: object) -> bool:
    return isinstance(provider, str) and provider in API_PROVIDERS


def configured(provider: str) -> bool:
    if provider == "flow":
        return True
    return bool(secrets.get_api_key(provider))


def _key_for(provider: str, api_key: Optional[str] = None) -> str:
    key = api_key or secrets.get_api_key(provider)
    if not key:
        raise ImageProviderError(
            f"Chưa có API key cho {PROVIDERS.get(provider, {}).get('label', provider)} "
            "(Cài đặt → Nguồn tạo ảnh)."
        )
    return key


def _orientation(aspect_ratio: object) -> str:
    """Flow enum → "portrait" | "landscape" | "square"."""
    upper = aspect_ratio.upper() if isinstance(aspect_ratio, str) else ""
    if "PORTRAIT" in upper:
        return "portrait"
    if "SQUARE" in upper:
        return "square"
    return "landscape"


def openai_size(aspect_ratio: object) -> str:
    return {"portrait": "1024x1536", "square": "1024x1024"}.get(_orientation(aspect_ratio), "1536x1024")


def xai_aspect(aspect_ratio: object) -> str:
    return {"portrait": "9:16", "square": "1:1"}.get(_orientation(aspect_ratio), "16:9")


def _body_snippet(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"][:200]
        if isinstance(err, str):
            return err[:200]
    except ValueError:
        pass
    return (resp.text or "")[:200].strip()


def error_for_response(provider: str, resp: httpx.Response) -> ImageProviderError:
    """HTTP failure → one Vietnamese sentence the settings panel / node can show."""
    label = PROVIDERS.get(provider, {}).get("label", provider)
    status = resp.status_code
    if status in (401, 403):
        return ImageProviderError(f"{label}: API key sai hoặc hết hạn (HTTP {status}).")
    if status == 429:
        return ImageProviderError(f"{label}: hết quota / bị giới hạn tốc độ (HTTP 429). {_body_snippet(resp)}".strip())
    return ImageProviderError(f"{label}: HTTP {status} — {_body_snippet(resp) or 'không có chi tiết'}")


def _client(timeout: float = GENERATE_TIMEOUT_S) -> httpx.AsyncClient:
    """One place to build the HTTP client (tests swap in a MockTransport here)."""
    return httpx.AsyncClient(timeout=timeout)


def _sniff_mime(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"


_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}


def _first_b64(provider: str, data: Any) -> bytes:
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ImageProviderError(f"{PROVIDERS[provider]['label']}: phản hồi không có ảnh.")
    first = items[0] if isinstance(items[0], dict) else {}
    b64 = first.get("b64_json")
    if not isinstance(b64, str) or not b64:
        raise ImageProviderError(f"{PROVIDERS[provider]['label']}: phản hồi không có dữ liệu base64.")
    try:
        raw = base64.b64decode(b64, validate=False)
    except (ValueError, TypeError) as exc:
        raise ImageProviderError(f"{PROVIDERS[provider]['label']}: base64 hỏng ({exc}).") from exc
    if not raw:
        raise ImageProviderError(f"{PROVIDERS[provider]['label']}: ảnh rỗng.")
    return raw


async def _send(provider: str, request_fn) -> httpx.Response:
    try:
        resp = await request_fn()
    except httpx.TimeoutException as exc:
        raise ImageProviderError(f"{PROVIDERS[provider]['label']}: quá thời gian chờ ({exc.__class__.__name__}).") from exc
    except httpx.HTTPError as exc:
        raise ImageProviderError(f"{PROVIDERS[provider]['label']}: lỗi mạng — {str(exc)[:160]}") from exc
    if resp.status_code >= 400:
        raise error_for_response(provider, resp)
    return resp


# ── generation ─────────────────────────────────────────────────────────


async def generate(
    provider: str,
    prompt: str,
    *,
    aspect_ratio: object = "IMAGE_ASPECT_RATIO_LANDSCAPE",
    reference_images: Optional[list[bytes]] = None,
    api_key: Optional[str] = None,
) -> bytes:
    """One image from ``provider``; returns the raw image bytes (PNG for OpenAI)."""
    if provider not in API_PROVIDERS:
        raise ImageProviderError(f"Nguồn tạo ảnh không hợp lệ: {provider!r}")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ImageProviderError("Thiếu prompt.")
    key = _key_for(provider, api_key)
    headers = {"Authorization": f"Bearer {key}"}
    refs = [r for r in (reference_images or []) if isinstance(r, bytes) and r and len(r) <= MAX_REFERENCE_BYTES]

    async with _client() as client:
        if provider == "openai":
            if refs:
                # Edits endpoint: the references are the input images and the
                # prompt describes the scene to build around them.
                files = []
                for i, raw in enumerate(refs[:16]):
                    mime = _sniff_mime(raw)
                    files.append(("image[]", (f"ref{i}.{_EXT.get(mime, 'bin')}", raw, mime)))
                data = {
                    "model": OPENAI_MODEL,
                    "prompt": prompt.strip(),
                    "size": openai_size(aspect_ratio),
                    "quality": "medium",
                    "n": "1",
                }
                resp = await _send(provider, lambda: client.post(
                    f"{OPENAI_BASE}/images/edits", headers=headers, data=data, files=files,
                ))
            else:
                body = {
                    "model": OPENAI_MODEL,
                    "prompt": prompt.strip(),
                    "size": openai_size(aspect_ratio),
                    "quality": "medium",
                    "n": 1,
                }
                resp = await _send(provider, lambda: client.post(
                    f"{OPENAI_BASE}/images/generations", headers=headers, json=body,
                ))
        else:  # xai
            if refs:
                logger.info("image_providers: xai ignores %d reference image(s)", len(refs))
            body = {
                "model": XAI_MODEL,
                "prompt": prompt.strip(),
                "aspect_ratio": xai_aspect(aspect_ratio),
                "response_format": "b64_json",
                "n": 1,
            }
            resp = await _send(provider, lambda: client.post(
                f"{XAI_BASE}/images/generations", headers=headers, json=body,
            ))
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ImageProviderError(f"{PROVIDERS[provider]['label']}: phản hồi không phải JSON.") from exc
    return _first_b64(provider, payload)


async def test_key(provider: str, api_key: Optional[str] = None) -> dict[str, Any]:
    """Cheap, free probe for the "Kiểm tra" button: ``{ok, message}``."""
    if provider == "flow":
        return {"ok": True, "message": "Flow không cần API key."}
    if provider not in API_PROVIDERS:
        return {"ok": False, "message": f"Nguồn tạo ảnh không hợp lệ: {provider!r}"}
    try:
        key = _key_for(provider, api_key)
    except ImageProviderError as exc:
        return {"ok": False, "message": str(exc)}
    headers = {"Authorization": f"Bearer {key}"}
    url = f"{OPENAI_BASE}/models/{OPENAI_MODEL}" if provider == "openai" else f"{XAI_BASE}/models"
    try:
        async with _client(TEST_TIMEOUT_S) as client:
            resp = await _send(provider, lambda: client.get(url, headers=headers))
    except ImageProviderError as exc:
        return {"ok": False, "message": str(exc)}
    model = PROVIDERS[provider]["model"]
    if provider == "xai":
        try:
            ids = [m.get("id") for m in (resp.json().get("data") or []) if isinstance(m, dict)]
        except (ValueError, AttributeError):
            ids = []
        if ids and model not in ids:
            return {"ok": True, "message": f"Key dùng được, nhưng danh sách model không có {model} "
                                            f"(có: {', '.join(str(i) for i in ids[:6])})."}
    return {"ok": True, "message": f"Key dùng được ({model})."}


# ── worker hook ────────────────────────────────────────────────────────


async def _ingest(raw: bytes, mime: str, project_id: str, file_name: str, node_id: Optional[int]) -> dict:
    """Push bytes into the Flow project; same path as a user upload.

    Imported lazily so this module stays importable in contexts without the
    FastAPI app (and so tests can monkeypatch this one name).
    """
    from flowboard.routes.upload import _ingest_image_bytes

    return await _ingest_image_bytes(raw, mime, project_id, file_name, node_id)


async def _reference_bytes(media_ids: list[str]) -> list[bytes]:
    out: list[bytes] = []
    for mid in media_ids:
        if not isinstance(mid, str) or not media_service.is_valid_media_id(mid):
            continue
        path = media_service.cached_path(mid)
        if path is None:
            fetched = await media_service.fetch_and_cache(mid)
            path = fetched[2] if fetched else None
        if path is None:
            logger.warning("image_providers: reference %s has no local bytes; skipped", mid)
            continue
        try:
            out.append(path.read_bytes())
        except OSError as exc:
            logger.warning("image_providers: cannot read reference %s: %s", mid, exc)
    return out


async def generate_and_ingest(
    provider: str,
    prompt: str,
    aspect_ratio: object,
    reference_media_ids: Optional[list[str]],
    project_id: str,
    *,
    prompts: Optional[list[str]] = None,
    variant_count: int = 1,
    node_id: Optional[int] = None,
) -> dict:
    """Render via the API, then upload into Flow. Result mirrors ``_handle_gen_image``.

    One API call per variant (``prompts`` gives each its own text, like the
    Flow path's per-variant prompts). A variant that fails leaves a ``None``
    in ``media_ids`` and its message in ``slot_errors``; if every variant
    fails the first message is raised as ``ImageProviderError``.
    """
    from fastapi import HTTPException

    if not isinstance(project_id, str) or not project_id.strip():
        raise ImageProviderError("missing_project_id")
    project_id = project_id.strip()
    texts = [p for p in (prompts or []) if isinstance(p, str) and p.strip()]
    count = max(1, min(int(variant_count or 1), MAX_VARIANTS))
    if len(texts) < count:
        texts = texts + [prompt] * (count - len(texts))
    texts = texts[:count]
    refs = await _reference_bytes(reference_media_ids or [])

    async def one(text: str) -> tuple[Optional[dict], Optional[str]]:
        try:
            raw = await generate(provider, text, aspect_ratio=aspect_ratio, reference_images=refs)
            mime = _sniff_mime(raw)
            if mime == "application/octet-stream":
                mime = "image/png"
            up = await _ingest(raw, mime, project_id, f"{provider}-image.{_EXT.get(mime, 'png')}", node_id)
        except ImageProviderError as exc:
            return None, str(exc)
        except HTTPException as exc:
            detail = exc.detail
            msg = detail.get("message") if isinstance(detail, dict) else detail
            return None, f"Đưa ảnh vào Flow thất bại: {str(msg)[:160]}"
        except Exception as exc:  # noqa: BLE001 — one bad variant must not sink the batch
            logger.exception("image_providers: variant failed")
            return None, f"{PROVIDERS[provider]['label']}: {str(exc)[:160]}"
        return up, None

    outcomes = await asyncio.gather(*(one(t) for t in texts))
    media_ids: list[Optional[str]] = []
    entries: list[dict] = []
    slot_errors: list[Optional[str]] = []
    for up, err in outcomes:
        if up is not None:
            mid = up["media_id"]
            media_ids.append(mid)
            entries.append({"media_id": mid, "kind": "image", "mime": up.get("mime"),
                            "width": up.get("width"), "height": up.get("height")})
            slot_errors.append(None)
        else:
            media_ids.append(None)
            slot_errors.append(err)
    if not any(media_ids):
        raise ImageProviderError(next((e for e in slot_errors if e), "không tạo được ảnh"))
    failed = [e for e in slot_errors if e]
    primary = next(m for m in media_ids if m)
    return {
        "media_ids": media_ids,
        "media_entries": entries,
        "media_id": primary,
        "slot_errors": slot_errors,
        "partial_error": f"{len(failed)}/{len(media_ids)} variants failed: {failed[0]}" if failed else None,
        "aspect_ratio": aspect_ratio,
        "provider": provider,
        "model": PROVIDERS[provider]["model"],
        "raw": None,
    }


async def maybe_generate_via_api(params: dict) -> Optional[tuple[dict, Optional[str]]]:
    """Worker hook for ``_handle_gen_image``.

    ``None`` means "not ours, carry on with Flow". Otherwise the request is
    settled here: ``(result, None)`` on success, ``({}, error)`` on failure —
    the same contract as every worker handler.
    """
    provider = params.get("image_provider")
    if provider in (None, "", "flow"):
        return None
    if not is_api_provider(provider):
        return {}, f"unknown_image_provider:{provider}"
    prompt = params.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return {}, "missing_prompt"
    project_id = params.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        return {}, "missing_project_id"
    raw_refs = params.get("ref_media_ids")
    if not isinstance(raw_refs, list):
        raw_refs = params.get("character_media_ids")
    refs = [m for m in raw_refs if isinstance(m, str) and m] if isinstance(raw_refs, list) else []
    raw_count = params.get("variant_count")
    raw_prompts = params.get("prompts")
    node_id = params.get("__node_id")
    try:
        result = await generate_and_ingest(
            provider,
            prompt.strip(),
            params.get("aspect_ratio") or "IMAGE_ASPECT_RATIO_LANDSCAPE",
            refs,
            project_id,
            prompts=raw_prompts if isinstance(raw_prompts, list) else None,
            variant_count=raw_count if isinstance(raw_count, int) and raw_count > 0 else 1,
            node_id=node_id if isinstance(node_id, int) else None,
        )
    except ImageProviderError as exc:
        return {"provider": provider}, str(exc)[:200]
    return result, None
