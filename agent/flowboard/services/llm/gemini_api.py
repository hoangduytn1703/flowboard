"""Direct Gemini API client with a pool of keys that rotates on quota.

The CLI provider (``gemini.py`` → ``agy``) cannot read a video; this
client talks to ``generativelanguage.googleapis.com`` itself, with text,
images and videos (inline or through the Files API), and optional JSON
schema output.

Keys come from ``secrets.get_gemini_keys()``. A call tries them in order:
a key that answers 429 / RESOURCE_EXHAUSTED is parked **for that model**
(Google's free-tier quotas are per model: a key out of TTS requests still
answers text requests) and the next key is used; a key that answers
400/401/403 is parked as a whole for longer (it is invalid or unauthorised,
not merely busy). When every key is parked for a short while (a per-minute
limit) the call waits for the first one to come back instead of failing.
The pool state lives in this process; a restart gives every key another
chance.
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
from typing import Any, Awaitable, Callable, Generic, Optional, TypeVar

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
    """429 / RESOURCE_EXHAUSTED: the key is out of quota for now — for
    ``model`` when Google names one (the usual case: quotas are per model),
    ``limit`` = the quota value and ``per_day`` whether it is a daily cap."""

    def __init__(self, message: str, retry_after_s: Optional[float] = None, *, model: Optional[str] = None,
                 limit: Optional[str] = None, per_day: bool = False) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s
        self.model = model
        self.limit = limit
        self.per_day = per_day


class GeminiKeyError(GeminiAPIError):
    """400/401/403: the key itself is refused."""


class GeminiBusyError(GeminiAPIError):
    """503 / UNAVAILABLE: the model is overloaded right now (not the key)."""


class GeminiThinkingError(GeminiAPIError):
    """400 about ``thinkingConfig``: this model takes no such thinking level (the call is sent again without it)."""


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
    #: the key as a whole (refused / invalid)
    parked_until: float = 0.0
    #: model → until when that model's quota is out for this key
    model_parked: dict[str, float] = field(default_factory=dict)
    #: model → the quota value Google named ("10" a day…), for the message
    model_limit: dict[str, str] = field(default_factory=dict)
    last_error: Optional[str] = None
    calls: int = 0
    last_ok_at: Optional[float] = None

    def free_at(self, model: Optional[str], now: float) -> float:
        """When this key can be used for ``model`` (now or earlier = usable)."""
        return max(self.parked_until, self.model_parked.get(model, 0.0) if model else 0.0)


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

    def candidates(self, model: Optional[str] = None) -> list[KeyState]:
        """Keys usable right now, in configured order: not refused, and not
        out of quota for ``model`` (any model when None)."""
        now = time.time()
        return [s for s in self._sync() if s.free_at(model, now) <= now]

    def next_free_in(self, model: Optional[str] = None) -> Optional[float]:
        """Seconds until the first parked key comes back for ``model``; None when no key exists."""
        now = time.time()
        states = self._sync()
        if not states:
            return None
        return max(0.0, min(s.free_at(model, now) for s in states) - now)

    def park(self, key: str, seconds: float, reason: str, model: Optional[str] = None, limit: Optional[str] = None) -> None:
        """Rest ``key`` for ``seconds`` — only for ``model`` when given (quota),
        else as a whole (refused)."""
        st = self.states.get(key)
        if st is None:
            return
        until = time.time() + max(1.0, seconds)
        if model:
            st.model_parked[model] = until
            if limit:
                st.model_limit[model] = limit
        else:
            st.parked_until = until
        st.last_error = reason[:200]
        logger.warning("gemini_api: key …%s parked %ds%s: %s", key[-6:], int(seconds), f" for {model}" if model else "", reason[:120])

    def note_ok(self, key: str) -> None:
        st = self.states.get(key)
        if st is not None:
            st.calls += 1
            st.last_ok_at = time.time()
            st.last_error = None

    def snapshot(self) -> list[dict[str, Any]]:
        now = time.time()
        out = []
        for s in self._sync():
            models = {m: int(t - now) for m, t in s.model_parked.items() if t > now}
            out.append({
                "masked": mask(s.key),
                # "parked" = the key as a whole is refused (bad key); per-model quota rests are listed separately
                "parked": s.parked_until > now,
                "parked_for_s": max(0, int(s.parked_until - now)),
                "models_parked": models,
                "model_limits": {m: s.model_limit.get(m, "") for m in models},
                "last_error": s.last_error,
                "calls": s.calls,
            })
        return out


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


def _quota_violation(body: Any) -> dict[str, str]:
    """The ``QuotaFailure`` violation Google attaches to a 429: which model,
    which quota, its value — ``{model, id, value, desc}`` (missing when absent)."""
    out: dict[str, str] = {}
    try:
        for d in body["error"]["details"]:
            for v in d.get("violations") or []:
                dims = v.get("quotaDimensions") or {}
                if dims.get("model"):
                    out["model"] = str(dims["model"])
                if v.get("quotaId"):
                    out["id"] = str(v["quotaId"])
                if v.get("quotaValue"):
                    out["value"] = str(v["quotaValue"])
                if v.get("description"):
                    out["desc"] = str(v["description"])
                return out
    except (KeyError, TypeError, AttributeError):
        pass
    return out


def _human_wait(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600} giờ {(seconds % 3600) // 60} phút"
    if seconds >= 60:
        return f"{seconds // 60} phút"
    return f"{seconds} giây"


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
        quota = _quota_violation(body)
        per_day = bool(re.search(r"per day|daily|PerDay", message + quota.get("id", "") + quota.get("desc", "")))
        # A daily limit is worth a long park; a per-minute one a short one.
        if delay is None:
            delay = QUOTA_COOLDOWN_S if per_day else 90.0
        raise GeminiQuotaError(f"quota: {message}", retry_after_s=delay, model=quota.get("model"),
                               limit=quota.get("value"), per_day=per_day)
    if resp.status_code == 503 or status == "UNAVAILABLE":
        raise GeminiBusyError(f"HTTP {resp.status_code}: {message}")
    if resp.status_code == 400 and re.search(r"thinking", message, re.I):
        # before the key check below: "... is not valid for this model" must never park a good key for hours
        raise GeminiThinkingError(f"HTTP 400: {message}")
    if resp.status_code == 404 and re.search(r"models?/|no longer available|not found", message):
        # A retired or unknown model, not a bad key: the fallback chain
        # moves on to the next model.
        raise GeminiBusyError(f"HTTP 404: {message}")
    if resp.status_code in (400, 401, 403) and re.search(
        r"API key|api key|PERMISSION_DENIED|UNAUTHENTICATED|not valid|expired|disabled", message + status
    ):
        raise GeminiKeyError(f"HTTP {resp.status_code}: {message}")
    raise GeminiAPIError(f"HTTP {resp.status_code}: {message}")


#: How long a call may wait for a parked key to come back (per-minute limits) before giving up.
MAX_WAIT_S = 45.0


async def with_key(fn: Callable[[str], Awaitable[T]], *, model: Optional[str] = None,
                   max_wait_s: float = MAX_WAIT_S, offset: int = 0) -> T:
    """Run ``fn(key)`` with the first key usable for ``model``, moving to the
    next one when a key is out of quota (parked for the model the answer
    names, or ``model``) or refused (parked as a whole). When every key is
    parked but one comes back within ``max_wait_s``, wait for it. Other
    errors propagate. ``offset`` starts the round at a later key (calls sent
    side by side spread over the keys instead of all hitting the first)."""
    if not secrets.get_gemini_keys():
        raise NoKeyAvailable("Chưa có Gemini API key — thêm trong Settings → Gemini API keys.")
    tried: list[str] = []
    waited = 0.0
    quota: Optional[GeminiQuotaError] = None
    rounds = 0
    while True:
        rounds += 1
        if rounds > 50:
            break
        cands = pool.candidates(model)
        if cands and offset:
            cands = cands[offset % len(cands):] + cands[:offset % len(cands)]
        for st in cands:
            key = st.key
            tried.append(mask(key))
            try:
                result = await fn(key)
            except GeminiQuotaError as exc:
                quota = exc
                if model is None and exc.model:
                    model = exc.model  # the quota Google named is this call's model from here on
                pool.park(key, exc.retry_after_s or QUOTA_COOLDOWN_S, str(exc), model=exc.model or model, limit=exc.limit)
                continue
            except GeminiKeyError as exc:
                pool.park(key, INVALID_COOLDOWN_S, str(exc))
                continue
            pool.note_ok(key)
            return result
        wait = pool.next_free_in(model)
        if wait is not None and wait <= max_wait_s - waited and (wait > 0 or tried):
            logger.info("gemini_api: every key is resting; waiting %.0fs for the first one (%s)", wait, model or "any model")
            await asyncio.sleep(wait + 0.5)
            waited += wait + 0.5
            continue
        break
    raise NoKeyAvailable(_no_key_message(model, tried, quota, pool.next_free_in(model)))


def _no_key_message(model: Optional[str], tried: list[str], quota: Optional[GeminiQuotaError],
                    wait: Optional[float]) -> str:
    now = time.time()
    states = pool._sync()
    refused = [s for s in states if s.parked_until > now]
    rested = [s for s in states if model and s.model_parked.get(model, 0) > now and s.parked_until <= now]
    bits = [f"Mọi Gemini API key ({len(states)}) đều hết quota hoặc bị từ chối"]
    if model:
        bits[0] += f" cho {model}"
    detail = []
    if rested:
        limit = next((s.model_limit.get(model or "") for s in rested if s.model_limit.get(model or "")), None)
        per_day = quota.per_day if quota else False
        detail.append(f"{len(rested)} key hết quota" + (f" ngày — bản miễn phí chỉ {limit} lượt/ngày/key" if per_day and limit
                                                       else f" — giới hạn {limit} lượt" if limit else ""))
    if refused:
        detail.append(f"{len(refused)} key bị từ chối (key sai hoặc chưa bật API)")
    if tried:
        detail.append(f"{len(tried)} key vừa thử lần này")
    if detail:
        bits.append(" (" + "; ".join(detail) + ")")
    if wait:
        bits.append(f". Key sớm nhất dùng lại được sau {_human_wait(wait)}")
    bits.append(". Thêm key mới, chờ, hoặc đổi giọng Edge (không giới hạn).")
    return "".join(bits)


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
    thinking: Optional[str] = None,
) -> str:
    """One ``generateContent`` call; the model's text (JSON text when a
    schema was given). ``thinking`` = ``thinkingConfig.thinkingLevel``
    ("minimal" | "low" | ...; None = the model's default)."""
    payload: dict[str, Any] = {"contents": [{"role": "user", "parts": parts}]}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    config: dict[str, Any] = {}
    if response_schema is not None:
        config["responseMimeType"] = "application/json"
        config["responseSchema"] = response_schema
    if temperature is not None:
        config["temperature"] = temperature
    if thinking:
        config["thinkingConfig"] = {"thinkingLevel": thinking}
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


# -- one heavy request sent to several models at once ----------------------

#: A reference video's / product page's ad plan goes to these at the SAME time: (model, thinking level). Measured 18/11
#: with Google overloaded: 3.5 / 3.6 / 3.7 / 3.8-flash answered 503 (some only after 30-60 s), 3.1-flash-lite answered
#: the full plan in 15-20 s. One model at a time with 5 + 10 s waits between retries and 300 s per call kept the
#: seller waiting 5 minutes for an error; the race answers as soon as any model can.
RACE_MODELS: list[tuple[str, Optional[str]]] = [
    ("gemini-3.5-flash", "low"),
    ("gemini-3.8-flash", "low"),
    ("gemini-3.1-flash-lite", "minimal"),
]
#: answers from these are plainer: once only such a model has answered, a stronger one gets RACE_PREFER_S more to land
RACE_SAFETY_NETS = ("gemini-3.1-flash-lite",)
RACE_PREFER_S = 15.0
#: a 503 is retried after this many seconds (doubling up to RACE_RETRY_MAX_S) while the race lasts
RACE_RETRY_S = 2.0
RACE_RETRY_MAX_S = 8.0


class RaceLost(GeminiAPIError):
    """No model of the race gave a usable answer in time."""


@dataclass
class RaceResult(Generic[T]):
    value: T
    model: str


async def race(
    parts: list[dict],
    accept: Callable[[str], T],
    *,
    system: Optional[str] = None,
    response_schema: Optional[dict] = None,
    models: Optional[list[tuple[str, Optional[str]]]] = None,
    deadline_s: float = 150.0,
    call_timeout_s: float = 120.0,
    got_answer: Optional[asyncio.Event] = None,
) -> RaceResult[T]:
    """Send ``parts`` to every model of ``models`` at once and return the
    first answer ``accept`` takes (it parses / checks the text and raises
    ``ValueError`` on a bad one). A safety-net model's answer is held up to
    :data:`RACE_PREFER_S` for a stronger one. 503s are retried while the
    race lasts; each racer starts at a different key. ``got_answer`` is set
    as soon as any usable answer exists (even one that is still held)."""
    models = models or RACE_MODELS
    loop = asyncio.get_running_loop()
    end = loop.time() + deadline_s
    won: asyncio.Future = loop.create_future()
    held: list[RaceResult[T]] = []
    errors: dict[str, str] = {}
    strong_in_race = any(m not in RACE_SAFETY_NETS for m, _ in models)

    def offer(result: RaceResult[T]) -> None:
        if got_answer is not None:
            got_answer.set()
        if won.done():
            return
        if result.model in RACE_SAFETY_NETS and strong_in_race:
            held.append(result)
            loop.call_later(RACE_PREFER_S, lambda: won.done() or won.set_result(held[0]))
            return
        won.set_result(result)

    async def racer(i: int, model: str, thinking: Optional[str]) -> None:
        gap, tries, level = RACE_RETRY_S, 0, thinking
        while not won.done() and loop.time() < end:
            tries += 1
            left = end - loop.time()
            try:
                text = await with_key(
                    lambda key: generate(key, parts, model=model, system=system, response_schema=response_schema,
                                         timeout=min(call_timeout_s, max(5.0, left)), thinking=level),
                    model=model, max_wait_s=0.0, offset=i + tries,
                )
            except GeminiThinkingError as exc:
                errors[model] = str(exc)[:200]
                if level is None:
                    return
                level = None  # this model takes no such level: send it plain
                continue
            except GeminiBusyError as exc:
                errors[model] = "quá tải (503)"
                logger.info("gemini race: %s busy (try %d): %s", model, tries, str(exc)[:80])
                await asyncio.sleep(min(gap, max(0.0, end - loop.time())))
                gap = min(gap * 2, RACE_RETRY_MAX_S)
                continue
            except GeminiAPIError as exc:  # quota on every key, timeout, refused...
                errors[model] = str(exc)[:200]
                logger.warning("gemini race: %s gave up: %s", model, str(exc)[:160])
                return
            try:
                value = accept(text)
            except (ValueError, TypeError, KeyError) as exc:
                errors[model] = f"trả lời không dùng được: {exc}"[:200]
                logger.warning("gemini race: %s answer rejected (try %d): %s", model, tries, str(exc)[:160])
                if tries >= 2:
                    return
                continue
            logger.info("gemini race: %s answered after %d try(s)", model, tries)
            offer(RaceResult(value, model))
            return

    tasks = [asyncio.create_task(racer(i, m, lv)) for i, (m, lv) in enumerate(models)]
    everyone = asyncio.gather(*tasks, return_exceptions=True)
    try:
        await asyncio.wait({won, everyone}, timeout=max(1.0, end - loop.time() + 1.0),
                           return_when=asyncio.FIRST_COMPLETED)
        if not won.done() and held:
            won.set_result(held[0])  # every stronger racer has finished without an answer
        if won.done():
            return won.result()
        raise RaceLost("Gemini đang quá tải — " + "; ".join(f"{m}: {e}" for m, e in errors.items()) if errors
                       else "Gemini không trả lời kịp")
    finally:
        for task in tasks:
            task.cancel()
        everyone.cancel()
        # read the gather's outcome so a race cut short (another AI won) logs no "exception never retrieved"
        everyone.add_done_callback(lambda f: f.cancelled() or f.exception())


TTS_MODEL = "gemini-3.8-flash-tts"
MODEL_FALLBACKS[TTS_MODEL] = ["gemini-3.8-flash-lite-tts", "gemini-3.1-flash-tts-preview"]


async def _speak(key: str, prompt: str, voice: str, model: str, timeout: float) -> bytes:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{BASE_URL}/v1beta/models/{model}:generateContent",
                                     headers={"x-goog-api-key": key}, json=payload)
    except httpx.TimeoutException as exc:
        raise GeminiAPIError(f"gemini tts timed out after {timeout}s") from exc
    except httpx.HTTPError as exc:
        raise GeminiAPIError(f"gemini tts transport error: {exc}") from exc
    _raise_for(resp)
    try:
        part = resp.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
        data = base64.b64decode(part["data"])
        mime = str(part.get("mimeType") or "")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise GeminiAPIError("gemini tts answered without audio") from exc
    if not data:
        raise GeminiAPIError("gemini tts returned empty audio")
    if mime.startswith("audio/L16") or "pcm" in mime:
        # Raw 24 kHz 16-bit mono PCM: wrap it so ffmpeg can read it.
        import io
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(data)
        data = buf.getvalue()
    return data


#: A dubbing job has many lines: waiting a few minutes for a per-minute limit beats failing the job.
TTS_MAX_WAIT_S = 180.0


async def speak(prompt: str, voice: str, *, model: str = TTS_MODEL, timeout: float = 120.0) -> bytes:
    """Gemini TTS through the key pool: WAV bytes for ``prompt`` (which
    carries the style instruction before the text). Model first, keys
    second: every key is tried on ``model`` (each has its own daily quota
    there), then every key on the fallback TTS models — which have their
    own quotas, so a key out of ``model`` requests still speaks through them."""
    chain = [model] + [m for m in MODEL_FALLBACKS.get(model, []) if m != model]
    last: Optional[GeminiAPIError] = None
    for i, m in enumerate(chain):
        async def one(key: str, m: str = m) -> bytes:
            busy: Optional[GeminiBusyError] = None
            for attempt in range(BUSY_RETRIES + 1):
                try:
                    return await _speak(key, prompt, voice, m, timeout)
                except GeminiBusyError as exc:
                    busy = exc
                    if attempt < BUSY_RETRIES:
                        await asyncio.sleep(BUSY_BACKOFF_S * (attempt + 1))
            raise busy  # type: ignore[misc]

        try:
            return await with_key(one, model=m, max_wait_s=TTS_MAX_WAIT_S if i == len(chain) - 1 else 0.0)
        except (NoKeyAvailable, GeminiBusyError) as exc:
            last = exc
            if i + 1 < len(chain):
                logger.warning("gemini_api: tts %s out of keys / overloaded (%s); trying %s", m, str(exc)[:80], chain[i + 1])
    assert last is not None
    raise last


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
