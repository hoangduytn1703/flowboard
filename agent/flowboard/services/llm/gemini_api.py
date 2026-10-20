"""Direct Gemini API client with a pool of keys that rotates on quota.

The CLI provider (``gemini.py`` → ``agy``) cannot read a video; this
client talks to ``generativelanguage.googleapis.com`` itself, with text,
images and videos (inline or through the Files API), and optional JSON
schema output.

Keys come from ``secrets.get_gemini_keys()``. A call tries them in order:
a key that answers 429 / RESOURCE_EXHAUSTED is parked for a cooldown and
the next one is used; a key that answers 400/401/403 is parked for longer
(it is invalid or unauthorised, not merely busy). The pool state lives in
this process; a restart gives every key another chance.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, TypeVar

import httpx

from . import secrets

logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_MODEL = "gemini-3.8-flash"
#: Requests above this go through the Files API instead of inline bytes.
INLINE_LIMIT_BYTES = 18 * 1024 * 1024
#: How long a key sits out after a quota answer that names no retry delay.
QUOTA_COOLDOWN_S = 15 * 60
#: A key that is rejected outright (bad key, API disabled) waits this long.
INVALID_COOLDOWN_S = 6 * 60 * 60

T = TypeVar("T")


class GeminiAPIError(RuntimeError):
    """A request that failed for a reason other than the key's quota."""


class GeminiQuotaError(GeminiAPIError):
    """429 / RESOURCE_EXHAUSTED: the key is out of quota for now."""

    def __init__(self, message: str, retry_after_s: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class GeminiKeyError(GeminiAPIError):
    """400/401/403: the key itself is refused."""


class GeminiBusyError(GeminiAPIError):
    """503 / UNAVAILABLE: the model is overloaded right now (not the key)."""


#: When a model answers 503, the call is retried, then moved down this list.
MODEL_FALLBACKS: dict[str, list[str]] = {
    # Newest first; the 2.x line is closed to new keys (404 "no longer
    # available"), so it is not in the chain.
    "gemini-3.8-flash": ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"],
    "gemini-3.5-flash": ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.1-flash-lite"],
    "gemini-3.1-pro-preview": ["gemini-3.8-flash", "gemini-3.7-flash"],
    "gemini-4-argon": ["gemini-3.8-flash", "gemini-3.7-flash"],
}
BUSY_RETRIES = 2
BUSY_BACKOFF_S = 5.0


async def with_model_fallback(fn: Callable[[str], Awaitable[T]], model: str) -> T:
    """``fn(model)``, retried on 503 and then tried on the fallback models."""
    chain = [model] + [m for m in MODEL_FALLBACKS.get(model, []) if m != model]
    last: Optional[Exception] = None
    for i, m in enumerate(chain):
        for attempt in range(BUSY_RETRIES + 1):
            try:
                return await fn(m)
            except GeminiBusyError as exc:
                last = exc
                if attempt < BUSY_RETRIES:
                    await asyncio.sleep(BUSY_BACKOFF_S * (attempt + 1))
        if i + 1 < len(chain):
            logger.warning("gemini_api: %s overloaded; falling back to %s", m, chain[i + 1])
    raise GeminiBusyError(f"Gemini đang quá tải ({', '.join(chain)}): {last}")


class NoKeyAvailable(GeminiAPIError):
    """Every configured key is parked, or none is configured."""


@dataclass
class KeyState:
    key: str
    parked_until: float = 0.0
    last_error: Optional[str] = None
    calls: int = 0
    last_ok_at: Optional[float] = None


@dataclass
class KeyPool:
    states: dict[str, KeyState] = field(default_factory=dict)

    def _sync(self) -> list[KeyState]:
        keys = secrets.get_gemini_keys()
        for k in keys:
            self.states.setdefault(k, KeyState(k))
        for k in list(self.states):
            if k not in keys:
                del self.states[k]
        return [self.states[k] for k in keys]

    def candidates(self) -> list[KeyState]:
        """Usable keys in configured order, parked ones last (they are
        tried only when nothing else is left and their cooldown passed)."""
        now = time.time()
        states = self._sync()
        return [s for s in states if s.parked_until <= now]

    def park(self, key: str, seconds: float, reason: str) -> None:
        st = self.states.get(key)
        if st is None:
            return
        st.parked_until = time.time() + max(1.0, seconds)
        st.last_error = reason[:200]
        logger.warning("gemini_api: key …%s parked %ds: %s", key[-6:], int(seconds), reason[:120])

    def note_ok(self, key: str) -> None:
        st = self.states.get(key)
        if st is not None:
            st.calls += 1
            st.last_ok_at = time.time()
            st.last_error = None

    def snapshot(self) -> list[dict[str, Any]]:
        now = time.time()
        return [
            {
                "masked": mask(s.key),
                "parked": s.parked_until > now,
                "parked_for_s": max(0, int(s.parked_until - now)),
                "last_error": s.last_error,
                "calls": s.calls,
            }
            for s in self._sync()
        ]


pool = KeyPool()


def mask(key: str) -> str:
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "…"


def configured() -> bool:
    return bool(secrets.get_gemini_keys())


# ── error classification ───────────────────────────────────────────────

def _retry_delay(body: Any) -> Optional[float]:
    """``details[].retryDelay`` ("31s") when Google names one."""
    try:
        for d in body["error"]["details"]:
            delay = d.get("retryDelay")
            if isinstance(delay, str) and delay.endswith("s"):
                return float(delay[:-1])
    except (KeyError, TypeError, ValueError):
        pass
    return None


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        body = resp.json()
        message = str(body.get("error", {}).get("message") or body)[:300]
        status = str(body.get("error", {}).get("status") or "")
    except ValueError:
        body, message, status = None, resp.text[:300], ""
    if resp.status_code == 429 or status == "RESOURCE_EXHAUSTED":
        delay = _retry_delay(body)
        # A daily limit is worth a long park; a per-minute one a short one.
        if delay is None:
            delay = QUOTA_COOLDOWN_S if re.search(r"per day|daily|PerDay", message) else 90.0
        raise GeminiQuotaError(f"quota: {message}", retry_after_s=delay)
    if resp.status_code == 503 or status == "UNAVAILABLE":
        raise GeminiBusyError(f"HTTP {resp.status_code}: {message}")
    if resp.status_code == 404 and re.search(r"models?/|no longer available|not found", message):
        # A retired or unknown model, not a bad key: the fallback chain
        # moves on to the next model.
        raise GeminiBusyError(f"HTTP 404: {message}")
    if resp.status_code in (400, 401, 403) and re.search(
        r"API key|api key|PERMISSION_DENIED|UNAUTHENTICATED|not valid|expired|disabled", message + status
    ):
        raise GeminiKeyError(f"HTTP {resp.status_code}: {message}")
    raise GeminiAPIError(f"HTTP {resp.status_code}: {message}")


async def with_key(fn: Callable[[str], Awaitable[T]]) -> T:
    """Run ``fn(key)`` with the first usable key, moving to the next one
    when a key is out of quota or refused. Other errors propagate."""
    tried: list[str] = []
    for st in pool.candidates():
        key = st.key
        tried.append(mask(key))
        try:
            result = await fn(key)
        except GeminiQuotaError as exc:
            pool.park(key, exc.retry_after_s or QUOTA_COOLDOWN_S, str(exc))
            continue
        except GeminiKeyError as exc:
            pool.park(key, INVALID_COOLDOWN_S, str(exc))
            continue
        pool.note_ok(key)
        return result
    if not secrets.get_gemini_keys():
        raise NoKeyAvailable("Chưa có Gemini API key — thêm trong Settings → Gemini API keys.")
    raise NoKeyAvailable(
        f"Mọi Gemini API key đều hết quota hoặc bị từ chối ({len(tried)} key đã thử). Thêm key mới hoặc chờ."
    )


# ── requests ───────────────────────────────────────────────────────────

def text_part(text: str) -> dict:
    return {"text": text}


def inline_part(path: Path, mime: Optional[str] = None) -> dict:
    mime = mime or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return {"inlineData": {"mimeType": mime, "data": base64.b64encode(path.read_bytes()).decode("ascii")}}


def file_part(uri: str, mime: str) -> dict:
    return {"fileData": {"mimeType": mime, "fileUri": uri}}


async def generate(
    key: str,
    parts: list[dict],
    *,
    model: str = DEFAULT_MODEL,
    system: Optional[str] = None,
    response_schema: Optional[dict] = None,
    temperature: Optional[float] = None,
    timeout: float = 180.0,
) -> str:
    """One ``generateContent`` call; the model's text (JSON text when a
    schema was given)."""
    payload: dict[str, Any] = {"contents": [{"role": "user", "parts": parts}]}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    config: dict[str, Any] = {}
    if response_schema is not None:
        config["responseMimeType"] = "application/json"
        config["responseSchema"] = response_schema
    if temperature is not None:
        config["temperature"] = temperature
    if config:
        payload["generationConfig"] = config
    url = f"{BASE_URL}/v1beta/models/{model}:generateContent"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers={"x-goog-api-key": key}, json=payload)
    except httpx.TimeoutException as exc:
        raise GeminiAPIError(f"gemini request timed out after {timeout}s") from exc
    except httpx.HTTPError as exc:
        raise GeminiAPIError(f"gemini transport error: {exc}") from exc
    _raise_for(resp)
    try:
        data = resp.json()
        cand = data["candidates"][0]
        texts = [p.get("text", "") for p in cand["content"]["parts"] if isinstance(p, dict)]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        reason = ""
        try:
            reason = resp.json().get("promptFeedback", {}).get("blockReason", "")
        except ValueError:
            pass
        raise GeminiAPIError(f"gemini response carried no text{f' (blocked: {reason})' if reason else ''}") from exc
    text = "".join(texts).strip()
    if not text:
        raise GeminiAPIError("gemini returned an empty answer")
    return text


async def upload_file(key: str, path: Path, mime: Optional[str] = None, *, timeout: float = 300.0) -> tuple[str, str]:
    """Resumable upload through the Files API; waits until the file is
    ACTIVE. Returns ``(file_uri, mime)``. Files belong to the key that
    uploaded them, so the generate call must use the same key."""
    mime = mime or mimetypes.guess_type(str(path))[0] or "video/mp4"
    size = path.stat().st_size
    async with httpx.AsyncClient(timeout=timeout) as client:
        start = await client.post(
            f"{BASE_URL}/upload/v1beta/files",
            headers={
                "x-goog-api-key": key,
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(size),
                "X-Goog-Upload-Header-Content-Type": mime,
                "Content-Type": "application/json",
            },
            json={"file": {"display_name": path.name}},
        )
        _raise_for(start)
        upload_url = start.headers.get("x-goog-upload-url")
        if not upload_url:
            raise GeminiAPIError("files API did not return an upload url")
        done = await client.post(
            upload_url,
            headers={
                "Content-Length": str(size),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            },
            content=path.read_bytes(),
        )
        _raise_for(done)
        info = done.json().get("file", {})
        name, uri = info.get("name"), info.get("uri")
        if not name or not uri:
            raise GeminiAPIError("files API upload answered without a file name")
        # Video needs a few seconds of server-side processing before it
        # can be referenced.
        for _ in range(60):
            status = await client.get(f"{BASE_URL}/v1beta/{name}", headers={"x-goog-api-key": key})
            _raise_for(status)
            state = status.json().get("state")
            if state == "ACTIVE":
                return uri, mime
            if state == "FAILED":
                raise GeminiAPIError("files API could not process the video")
            await asyncio.sleep(3)
    raise GeminiAPIError("files API processing timed out")


async def generate_with_media(
    parts_before: list[dict],
    media_path: Optional[Path],
    parts_after: list[dict],
    *,
    model: str = DEFAULT_MODEL,
    system: Optional[str] = None,
    response_schema: Optional[dict] = None,
    timeout: float = 240.0,
) -> str:
    """``generate`` with one media file in the middle, inline when small,
    through the Files API otherwise — rotating keys as a unit so a file
    uploaded under one key is never referenced with another."""

    async def run(key: str) -> str:
        parts = list(parts_before)
        if media_path is not None:
            if media_path.stat().st_size <= INLINE_LIMIT_BYTES:
                parts.append(inline_part(media_path))
            else:
                uri, mime = await upload_file(key, media_path)
                parts.append(file_part(uri, mime))
        parts.extend(parts_after)
        return await with_model_fallback(
            lambda m: generate(key, parts, model=m, system=system,
                               response_schema=response_schema, timeout=timeout),
            model,
        )

    return await with_key(run)


async def generate_text(
    prompt: str,
    *,
    system: Optional[str] = None,
    attachments: Optional[list[str]] = None,
    model: str = DEFAULT_MODEL,
    response_schema: Optional[dict] = None,
    timeout: float = 120.0,
) -> str:
    """Text (+ optional image attachments) through the key pool."""
    parts: list[dict] = [inline_part(Path(p)) for p in attachments or []]
    parts.append(text_part(prompt))
    return await with_key(lambda key: with_model_fallback(
        lambda m: generate(key, parts, model=m, system=system, response_schema=response_schema, timeout=timeout),
        model,
    ))


async def list_models(key: str, timeout: float = 20.0) -> list[str]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{BASE_URL}/v1beta/models?pageSize=200", headers={"x-goog-api-key": key})
    _raise_for(resp)
    out = []
    for m in resp.json().get("models", []):
        name = str(m.get("name", "")).removeprefix("models/")
        if "generateContent" in (m.get("supportedGenerationMethods") or []) and name.startswith("gemini"):
            out.append(name)
    return out


async def check_key(key: str) -> dict[str, Any]:
    """One cheap request per key for the Settings panel's "Test" button."""
    started = time.monotonic()
    try:
        models = await list_models(key)
        pool._sync()
        pool.note_ok(key)
        return {"masked": mask(key), "ok": True, "models": len(models),
                "latency_ms": int((time.monotonic() - started) * 1000)}
    except GeminiQuotaError as exc:
        pool._sync()
        pool.park(key, exc.retry_after_s or QUOTA_COOLDOWN_S, str(exc))
        return {"masked": mask(key), "ok": False, "error": "hết quota", "detail": str(exc)[:200]}
    except GeminiAPIError as exc:
        pool._sync()
        if isinstance(exc, GeminiKeyError):
            pool.park(key, INVALID_COOLDOWN_S, str(exc))
        return {"masked": mask(key), "ok": False, "error": "bị từ chối", "detail": str(exc)[:200]}


def parse_json(text: str) -> Any:
    """The model's JSON, tolerant of code fences around it."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S).strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise
