"""Free machine translation without a key or an AI quota — what VieDub / pyvideotrans
dubs with (its default channel is Google Translate).

Order: Google (``translate.googleapis.com … client=gtx``: lines joined with newlines,
the answer keeps them) → Microsoft (the Edge browser's free endpoint: one item per
line, so the line count always holds). pyvideotrans' own Google call scrapes
``translate.google.com/m``, which Google answers with a "sorry" page once an IP has
sent a lot; gtx kept working from the same machine (30/10). A Google batch that comes
back with a different line count goes to Microsoft; when both are down the error
says so.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)

GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
MICROSOFT_URL = "https://edge.microsoft.com/translate/translatetext"
DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0.0.0 Safari/537.36")
#: lines per request, and the source characters per Google request (it is a GET: CJK triples in the URL)
BATCH_LINES = 25
GOOGLE_MAX_CHARS = 700
MICROSOFT_BATCH = 50
ATTEMPTS = 3
TIMEOUT_S = 20.0

#: Whisper's language codes → each service's
_GOOGLE_CODES = {"zh": "zh-CN", "": "auto", None: "auto"}
_MS_CODES = {"zh": "zh-Hans", "": "", None: ""}


class TranslateError(RuntimeError):
    pass


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def google_batch(lines: list[str], source: Optional[str], target: str = "vi", *,
                 client: Optional[httpx.Client] = None) -> list[str]:
    sl = _GOOGLE_CODES.get(source, source or "auto")
    params = {"client": "gtx", "sl": sl, "tl": _GOOGLE_CODES.get(target, target), "dt": "t", "q": "\n".join(lines)}
    c = client or httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": DESKTOP_UA})
    try:
        r = c.get(GOOGLE_URL, params=params)
        if r.status_code != 200:
            raise TranslateError(f"Google {r.status_code}")
        data = r.json()
        text = "".join(seg[0] for seg in (data[0] or []) if seg and seg[0])
    except (httpx.HTTPError, ValueError, TypeError, IndexError) as exc:
        raise TranslateError(f"Google: {exc}") from exc
    finally:
        if client is None:
            c.close()
    out = [_clean(x) for x in text.split("\n")]
    if len(out) != len(lines):
        raise TranslateError(f"Google trả {len(out)} dòng cho {len(lines)} dòng")
    return out


def microsoft_batch(lines: list[str], source: Optional[str], target: str = "vi", *,
                    client: Optional[httpx.Client] = None) -> list[str]:
    frm = _MS_CODES.get(source, source or "")
    c = client or httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": DESKTOP_UA})
    try:
        r = c.post(MICROSOFT_URL, params={"from": frm, "to": _MS_CODES.get(target, target), "isEnterpriseClient": "false"},
                   json=lines)
        if r.status_code != 200:
            raise TranslateError(f"Microsoft {r.status_code}")
        out = [_clean(item["translations"][0]["text"]) for item in r.json()]
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise TranslateError(f"Microsoft: {exc}") from exc
    finally:
        if client is None:
            c.close()
    if len(out) != len(lines):
        raise TranslateError(f"Microsoft trả {len(out)} dòng cho {len(lines)} dòng")
    return out


def _retry(fn: Callable[[], list[str]], sleep: Callable[[float], None]) -> list[str]:
    last: Optional[TranslateError] = None
    for attempt in range(ATTEMPTS):
        if attempt:
            sleep(1.5 * attempt)
        try:
            return fn()
        except TranslateError as exc:
            last = exc
            if "dòng cho" in str(exc):  # a line-count mismatch does not get better by asking again
                break
    raise last or TranslateError("không dịch được")


def batches(lines: list[str]) -> list[tuple[int, int]]:
    """``[(start, end)]``: ≤ :data:`BATCH_LINES` lines and ≤ :data:`GOOGLE_MAX_CHARS` characters each."""
    out: list[tuple[int, int]] = []
    start, chars = 0, 0
    for i, line in enumerate(lines):
        if i > start and (i - start >= BATCH_LINES or chars + len(line) > GOOGLE_MAX_CHARS):
            out.append((start, i))
            start, chars = i, 0
        chars += len(line) + 1
    if start < len(lines):
        out.append((start, len(lines)))
    return out


def translate_lines(lines: list[str], source: Optional[str] = None, target: str = "vi", *,
                    progress: Optional[Callable[[int, int], None]] = None,
                    sleep: Callable[[float], None] = time.sleep) -> tuple[list[str], str]:
    """One translation per line (empty stays empty) and which service did most of them
    ("google" / "microsoft"). Raises :class:`TranslateError` when both services fail."""
    out = [""] * len(lines)
    todo = [(i, _clean(t)) for i, t in enumerate(lines) if _clean(t)]
    texts = [t for _, t in todo]
    used: dict[str, int] = {}
    with httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": DESKTOP_UA}) as c:
        parts = batches(texts)
        for n, (a, b) in enumerate(parts):
            chunk = texts[a:b]
            errors: list[str] = []
            result: Optional[list[str]] = None
            for name, fn in (("google", google_batch), ("microsoft", microsoft_batch)):
                try:
                    result = _retry(lambda fn=fn: fn(chunk, source, target, client=c), sleep)
                    used[name] = used.get(name, 0) + len(chunk)
                    break
                except TranslateError as exc:
                    errors.append(str(exc))
            if result is None:
                raise TranslateError("Google và Microsoft đều không dịch được (" + " · ".join(errors) + ")")
            for (i, _), vi in zip(todo[a:b], result):
                out[i] = vi
            if progress:
                progress(n + 1, len(parts))
    by = max(used, key=used.get) if used else "google"
    logger.info("free_translate: %d lines (%s)", len(texts), ", ".join(f"{k} {v}" for k, v in used.items()) or "-")
    return out, by
