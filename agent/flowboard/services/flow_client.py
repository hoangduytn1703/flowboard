"""Bridge to the Chrome MV3 extension over WebSocket.

Ported + trimmed from flowkit.

Control flow:
1. Extension opens WS to the agent (``EXTENSION_WS_PORT``, default 8355).
2. Agent sends ``{type:"callback_secret", secret}`` immediately.
3. When the agent wants to run a Flow RPC it calls
   ``flow_client.batch_rpc(rpcid, freq, ...)``, which sends
   ``{id, method:"batch_rpc", params}`` over WS and awaits a future.
4. The extension runs that envelope inside a signed-in ``flow.google.com`` tab
   — the page holds the cookie, the per-page ``at`` token and the reCAPTCHA
   mint, none of which can be replayed from outside it — then POSTs the
   response to ``/api/ext/callback`` with ``X-Callback-Secret``.
5. That HTTP handler resolves the pending future by id.
6. WS-side inbound messages from the extension (``token_captured``,
   ``extension_ready``, ``pong``, ``status``) update our stats.

Since Flow moved to ``flow.google.com`` (September 2026) there is no
``Authorization: Bearer ya29.…`` on any request, so ``flow_key_present: false``
is the normal, healthy state and ``token_captured`` no longer arrives. The
Bearer-dependent helpers below are kept for an older extension that still
emits one, and because ``/api/requests`` still accepts a raw ``proxy`` type.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
import logging
import secrets
import time
import uuid
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


# Google Flow's public API key — appears verbatim in every aisandbox-pa
# request URL Flow web emits. Not a secret; documented here so we don't
# need to plumb it through from the extension on every call.
_FLOW_API_KEY = "AIzaSyBtrm0o5ab1c-Ec8ZuLcGt3oJAA5VWt3pY"
_FLOW_CREDITS_URL = "https://aisandbox-pa.googleapis.com/v1/credits"
# Minimum gap between paygate-tier refreshes when the same Bearer token
# is re-delivered. Tier rarely changes; 60 s is fine for AccountPanel
# freshness and tames the credits-fetch storm an old extension can
# induce by re-emitting `token_captured` on every outbound request.
_TIER_REFRESH_MIN_INTERVAL_S = 60.0


@dataclass
class ExtConn:
    """One connected extension = one Chrome profile = one Google account."""
    id: int
    ws: Any
    connected_at: float
    remote: str = ""
    version: Optional[str] = None
    flow_key_present: bool = False
    email: Optional[str] = None
    credits: Optional[int] = None
    tier: Optional[str] = None
    account_checked_at: Optional[float] = None
    account_error: Optional[str] = None
    #: The Flow tab the account was read from, and the project that tab has open (setup guide: "use this one").
    tab_url: Optional[str] = None
    tab_project: Optional[str] = None


def _tab_project(url: Optional[str]) -> Optional[str]:
    """The project a Flow tab has open (``…/project/<uuid>``), or None on the home page / a non-project URL."""
    if not url or "/project/" not in url:
        return None
    from flowboard.services.flow_project import normalize_project_id

    return normalize_project_id(url)


def _version_tuple(v: Optional[str]) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in (v or "0").split("."))
    except ValueError:
        return (0,)


def _parse_credits(value: Any) -> Optional[int]:
    """'62 tín dụng Google Flow' / '1.250 credits' / 1250 → 1250."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return None
    m = re.search(r"\d[\d.,\s]*", value)
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group(0))
    return int(digits) if digits else None


def _clean_email(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if "@" in value and len(value) < 200 else None


class FlowClient:
    """Singleton bridge client."""

    DEFAULT_TIMEOUT = 180.0  # seconds
    #: First extension build that answers ``read_account``.
    ACCOUNT_MIN_VERSION = (0, 3, 0)

    def __init__(self) -> None:
        # Every connected extension (one per Chrome profile = one Google
        # account) is an ExtConn; ``_active`` is the one generation uses.
        self._conns: dict[int, ExtConn] = {}
        self._active: Optional[int] = None
        self._next_conn_id = 1
        # Called with {"email", "credits", "tier"} after each account read
        # (services.account_pool registers itself here).
        self.account_listeners: list = []
        self._pending: dict[str, asyncio.Future] = {}
        self._callback_secret: str = secrets.token_urlsafe(32)

        self._token_captured_at: Optional[float] = None
        self._flow_key_present: bool = False
        # Cached Bearer token for server-side fetches against
        # aisandbox-pa (e.g. /v1/credits for paygate tier resolution).
        # In-memory only; cleared on extension disconnect. NOT logged
        # anywhere — see fetch_paygate_tier() for the only consumer.
        self._flow_key: Optional[str] = None
        # Last time we hit /v1/credits — guards against the extension
        # emitting `token_captured` on every outbound aisandbox-pa
        # request (polls fire dozens per minute during video gen). The
        # extension was patched to only emit on rotation, but we keep
        # this dedupe so older installs don't spam the credits endpoint.
        self._last_tier_fetch_at: Optional[float] = None
        self._last_logged_key: Optional[str] = None
        # Profile pushed by the extension after it resolves the Bearer
        # token via Google's userinfo endpoint. Stays in-memory only —
        # if the agent restarts the extension will replay it on the
        # next WS reconnect.
        self._user_info: Optional[dict] = None
        # Paygate tier authoritative from /v1/credits + sku for display.
        self._paygate_tier: Optional[str] = None
        self._sku: Optional[str] = None  # e.g. "WS_ULTRA" / "WS_PRO"
        self._credits: Optional[int] = None
        self._request_count = 0
        self._success_count = 0
        self._failed_count = 0
        self._last_error: Optional[str] = None

    # ── connection ─────────────────────────────────────────────────────────
    @property
    def active_conn(self) -> Optional["ExtConn"]:
        if self._active is None:
            return None
        return self._conns.get(self._active)

    @property
    def _ws(self) -> Optional[Any]:
        conn = self.active_conn
        return conn.ws if conn else None

    @property
    def connected(self) -> bool:
        return self._ws is not None

    @property
    def extension_version(self) -> Optional[str]:
        """Manifest version the active extension reported on connect; None
        for a build older than 0.2.0, which does not send one."""
        conn = self.active_conn
        return conn.version if conn else None

    @property
    def callback_secret(self) -> str:
        return self._callback_secret

    def conn_for(self, ws: Any) -> Optional["ExtConn"]:
        for c in self._conns.values():
            if c.ws is ws:
                return c
        return None

    def set_extension(self, ws: Any) -> int:
        """Register a connected extension; the first one becomes active.
        Returns its connection id."""
        existing = self.conn_for(ws)
        if existing:
            return existing.id
        conn = ExtConn(id=self._next_conn_id, ws=ws, connected_at=time.time(),
                       remote=str(getattr(ws, "remote_address", "") or ""))
        self._next_conn_id += 1
        self._conns[conn.id] = conn
        if self._active is None or self._active not in self._conns:
            self._active = conn.id
        return conn.id

    def clear_extension(self, ws: Any = None) -> None:
        """Forget one connection (``ws``) or, with no argument, all of them
        (logout). Losing the active one promotes another connected
        extension so generation keeps going."""
        if ws is None:
            self._conns.clear()
            self._active = None
        else:
            conn = self.conn_for(ws)
            if conn is None:
                return
            self._conns.pop(conn.id, None)
            if self._active == conn.id:
                self._active = next(iter(self._conns), None)
            if self._active is not None:
                # Another account carries on; its own identity applies.
                self._reset_identity()
                return
        self._reset_identity()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("extension_disconnected"))
        self._pending.clear()

    def _reset_identity(self) -> None:
        self._flow_key_present = False
        self._flow_key = None
        # Drop the cached identity + tier — next reconnect will replay.
        self._user_info = None
        self._paygate_tier = None
        self._sku = None
        self._credits = None

    # ── accounts (one per connected Chrome profile) ────────────────────────
    def accounts(self) -> list[dict]:
        out = []
        for c in self._conns.values():
            out.append({
                "id": c.id, "active": c.id == self._active, "email": c.email,
                "credits": c.credits, "tier": c.tier, "version": c.version,
                "connected_at": c.connected_at, "account_checked_at": c.account_checked_at,
                "account_error": c.account_error,
            })
        return out

    def activate(self, conn_id: int) -> bool:
        if conn_id not in self._conns or conn_id == self._active:
            return conn_id in self._conns
        self._active = conn_id
        self._reset_identity()
        return True

    async def read_account(self, conn_id: Optional[int] = None) -> dict:
        """Ask one extension to read email / credits / plan off the account
        panel of its Flow tab (there is no API for it on this transport)."""
        conn = self._conns.get(conn_id) if conn_id is not None else self.active_conn
        if conn is None:
            return {"error": "extension_disconnected"}
        if _version_tuple(conn.version) < self.ACCOUNT_MIN_VERSION:
            conn.account_error = "extension_outdated"
            return {"error": "extension_outdated", "version": conn.version}
        resp = await self._send("read_account", {}, timeout=25.0, conn=conn)
        err = resp.get("error")
        if err:
            conn.account_error = str(err)
            return {"error": str(err)}
        try:
            data = resp.get("data")
            info = json.loads(data) if isinstance(data, str) else dict(data or {})
        except (TypeError, ValueError):
            conn.account_error = "bad_payload"
            return {"error": "bad_payload"}
        conn.email = _clean_email(info.get("email"))
        conn.credits = _parse_credits(info.get("credits"))
        tier = info.get("tier")
        conn.tier = tier.strip().upper() if isinstance(tier, str) and tier.strip() else None
        conn.tab_url = info.get("tabUrl") if isinstance(info.get("tabUrl"), str) else None
        conn.tab_project = _tab_project(conn.tab_url)
        conn.account_checked_at = time.time()
        conn.account_error = None
        if conn.id == self._active:
            self._credits = conn.credits
            if conn.email and not self._user_info:
                self._user_info = {"email": conn.email}
        logger.info("read_account conn=%s email=%s credits=%s tier=%s", conn.id, conn.email, conn.credits, conn.tier)
        out = {"email": conn.email, "credits": conn.credits, "tier": conn.tier, "project_id": conn.tab_project}
        if conn.id == self._active:
            for fn in list(self.account_listeners):
                try:
                    fn(out)
                except Exception:  # noqa: BLE001
                    logger.exception("account listener failed")
        return out

    @property
    def user_info(self) -> Optional[dict]:
        return self._user_info

    @property
    def paygate_tier(self) -> Optional[str]:
        return self._paygate_tier

    @property
    def sku(self) -> Optional[str]:
        return self._sku

    @property
    def credits(self) -> Optional[int]:
        return self._credits

    async def fetch_paygate_tier(self) -> bool:
        """Paygate tier resolution via the Flow /v1/credits endpoint.

        DEAD ON THE CURRENT TRANSPORT. This needs the Bearer token the old
        aisandbox-pa host required, and flow.google.com does not mint one, so
        ``self._flow_key`` stays empty and this returns False on the first
        line. The tier now comes from ``config.DEFAULT_PAYGATE_TIER``; see
        ``flow_sdk.resolve_paygate_tier``. Kept so an older extension that
        still captures a token keeps populating the AccountPanel, and so the
        day Flow exposes credits again there is one place to re-point.

        Triggered automatically when `handle_message` receives a
        `token_captured` message (extension just captured a fresh
        Bearer token), and on demand via /api/auth/scan when the
        cache is cold but the WS is open.

        Returns True on success (tier cached), False otherwise. Failure
        modes:
          - No Bearer token cached (extension hasn't pushed one yet)
          - HTTP 4xx (token expired / revoked)
          - HTTP 5xx / network (transient — caller can retry)
          - Response missing `userPaygateTier` (Flow API contract change)

        IMPORTANT: never log the Bearer token. The error path captures
        only the HTTP status / response shape, never headers.
        """
        if not self._flow_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    _FLOW_CREDITS_URL,
                    params={"key": _FLOW_API_KEY},
                    headers={
                        "authorization": f"Bearer {self._flow_key}",
                        "origin": "https://labs.google",
                        "referer": "https://labs.google/",
                    },
                )
        except httpx.HTTPError as exc:
            logger.warning("fetch_paygate_tier transport error: %s", exc)
            return False
        if resp.status_code != 200:
            logger.warning(
                "fetch_paygate_tier returned HTTP %s (token may be expired)",
                resp.status_code,
            )
            return False
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            logger.warning("fetch_paygate_tier: response was not JSON")
            return False
        tier = data.get("userPaygateTier")
        if tier not in ("PAYGATE_TIER_ONE", "PAYGATE_TIER_TWO"):
            logger.warning(
                "fetch_paygate_tier: response missing userPaygateTier (got %r)",
                tier,
            )
            return False
        self._paygate_tier = tier
        sku = data.get("sku")
        if isinstance(sku, str):
            self._sku = sku
        credits_val = data.get("credits")
        if isinstance(credits_val, int):
            self._credits = credits_val
        logger.info(
            "fetch_paygate_tier resolved tier=%s sku=%s credits=%s",
            tier, self._sku, self._credits,
        )
        return True

    # ── inbound handling ───────────────────────────────────────────────────
    async def handle_message(self, data: dict, ws: Any = None) -> None:
        t = data.get("type")
        if t == "extension_ready":
            v = data.get("version")
            conn = self.conn_for(ws) if ws is not None else self.active_conn
            if conn is not None:
                conn.version = v if isinstance(v, str) and v else None
                conn.flow_key_present = bool(data.get("flowKeyPresent"))
                if _version_tuple(conn.version) >= self.ACCOUNT_MIN_VERSION:
                    # Learn which Google account this profile is, in the background.
                    asyncio.create_task(self.read_account(conn.id))
            if conn is None or conn.id == self._active:
                self._flow_key_present = bool(data.get("flowKeyPresent"))
            logger.info("extension_ready conn=%s flowKeyPresent=%s version=%s",
                        conn.id if conn else None, bool(data.get("flowKeyPresent")), conn.version if conn else None)
            return
        if t == "token_captured":
            self._flow_key_present = True
            self._token_captured_at = time.time()
            flow_key = data.get("flowKey")
            if isinstance(flow_key, str) and flow_key:
                key_changed = flow_key != self._flow_key
                self._flow_key = flow_key
                # Defensive dedupe — see _last_tier_fetch_at field comment.
                # Skip the log + credits refetch when the token hasn't
                # rotated and we already fetched within the rate-limit
                # window. Without this, an older extension re-sending the
                # same token on every poll trips one /v1/credits per poll.
                now = time.time()
                last = self._last_tier_fetch_at or 0.0
                if key_changed or (now - last) > _TIER_REFRESH_MIN_INTERVAL_S:
                    if flow_key != self._last_logged_key:
                        logger.info("token_captured (len=%d)", len(flow_key))
                        self._last_logged_key = flow_key
                    self._last_tier_fetch_at = now
                    # Authoritative tier resolution — fetch /v1/credits in
                    # the background so the AccountPanel sees a real tier
                    # within an HTTP RTT instead of waiting for the user's
                    # Flow tab to emit a request the passive sniffer can
                    # see. Don't await: WS handler must stay responsive.
                    asyncio.create_task(self.fetch_paygate_tier())
            return
        if t == "user_info":
            info = data.get("userInfo")
            if isinstance(info, dict):
                # Whitelist on intake — Google's userinfo response can
                # carry id / locale / hd / given_name / family_name etc.
                # The /api/auth/me route filters on output, but caching
                # the full dict here means any future surface that
                # returns flow_client.user_info directly leaks PII.
                # Clamp at the door instead.
                allowed = ("email", "name", "picture", "verified_email")
                self._user_info = {k: info[k] for k in allowed if k in info}
                logger.info(
                    "user_info captured for %s",
                    self._user_info.get("email") or "<no email>",
                )
            return
        if t == "pong":
            return
        # Inbound response (legacy path; production flow uses HTTP callback)
        req_id = data.get("id")
        if req_id and req_id in self._pending:
            self._resolve(req_id, data)

    def resolve_callback(self, data: dict) -> bool:
        """Called by the HTTP callback endpoint after validating the secret.

        Returns True if a pending future matched.
        """
        req_id = data.get("id")
        if not req_id or req_id not in self._pending:
            return False
        self._resolve(req_id, data)
        return True

    def _resolve(self, req_id: str, data: dict) -> None:
        fut = self._pending.pop(req_id, None)
        if not fut or fut.done():
            return
        # Count as failure if (a) an explicit `error` field is set OR
        # (b) the HTTP status is a 4xx/5xx. Otherwise success.
        status = data.get("status")
        http_error = isinstance(status, int) and status >= 400
        explicit_error = bool(data.get("error"))
        if http_error or explicit_error:
            self._failed_count += 1
            msg = data.get("error") or f"API_{status}"
            self._last_error = str(msg)[:200]
            fut.set_result(data)
        else:
            self._success_count += 1
            fut.set_result(data)

    # ── outbound ──────────────────────────────────────────────────────────
    async def notify(self, message: dict) -> bool:
        """Fire-and-forget WS push to the extension. Returns False when the
        extension isn't connected so callers can surface a meaningful
        diagnostic instead of silently losing the message.

        Used by the logout flow (tell extension to clear its in-memory
        token + cached userinfo) and the scan flow (ask extension to
        re-fetch userinfo when the agent has a connection but the cache
        is empty).
        """
        if not self.connected or self._ws is None:
            return False
        try:
            await self._ws.send(json.dumps(message))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("notify failed: %s", exc)
            return False

    async def _send(self, method: str, params: dict, timeout: Optional[float] = None,
                    conn: Optional["ExtConn"] = None) -> dict:
        ws = conn.ws if conn is not None else self._ws
        if ws is None:
            return {"error": "extension_disconnected"}

        req_id = str(uuid.uuid4())
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        self._request_count += 1

        payload = {"id": req_id, "method": method, "params": params}
        try:
            await ws.send(json.dumps(payload))
            return await asyncio.wait_for(fut, timeout=timeout or self.DEFAULT_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            self._failed_count += 1
            self._last_error = "timeout"
            return {"error": "timeout"}
        except ConnectionError as exc:
            self._pending.pop(req_id, None)
            self._failed_count += 1
            self._last_error = str(exc)
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            self._pending.pop(req_id, None)
            self._failed_count += 1
            self._last_error = str(exc)
            return {"error": str(exc)}

    # ── batchexecute transport (the live path) ─────────────────────────────
    #
    # Flow's rewritten frontend signs every call with the session cookie plus a
    # per-page `at` token, and a generate also carries a single-use reCAPTCHA
    # token. None of that can be replayed from here, so the agent only builds
    # the envelope and the extension issues it inside a signed-in Flow tab.
    #
    # `api_request` / `trpc_request` below are the pre-migration REST and tRPC
    # proxies. They are kept because `/api/requests` still accepts a raw
    # `proxy` type and an extension may be newer than its agent, but nothing
    # in the generation path reaches for them any more.

    async def batch_rpc(
        self,
        rpcid: str,
        freq: str,
        captcha_action: Optional[str] = None,
        match: Optional[str] = None,
        timeout: Optional[float] = 300.0,
    ) -> dict:
        """Run one batchexecute RPC inside the Flow page. Returns the raw body.

        ``match`` asks the extension to cut the response down to an 800-byte
        window around that string before handing it back. The project listing
        is past 17 MB for the single entry we want out of it, and the cheapest
        place to throw the rest away is inside the tab — shipping it whole gets
        it truncated and loses roughly half of all lookups.
        """
        params: dict[str, Any] = {"rpcid": rpcid, "freq": freq}
        if captcha_action:
            params["captchaAction"] = captcha_action
        if match:
            params["match"] = match
        return await self._send("batch_rpc", params, timeout=timeout)

    async def api_request(
        self,
        url: str,
        method: str = "POST",
        headers: Optional[dict] = None,
        body: Any = None,
        captcha_action: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        """Proxy an HTTP call against aisandbox-pa.googleapis.com through the
        extension's browser session. If ``captcha_action`` is set, the
        extension solves reCAPTCHA on an active Flow tab before firing the
        fetch and injects the token into the body's recaptchaContext fields.
        """
        params: dict[str, Any] = {
            "url": url,
            "method": method,
            "headers": headers or {},
            "body": body,
        }
        if captcha_action:
            params["captchaAction"] = captcha_action
        return await self._send("api_request", params, timeout=timeout)

    async def trpc_request(
        self,
        url: str,
        method: str = "POST",
        headers: Optional[dict] = None,
        body: Any = None,
        timeout: Optional[float] = 30.0,
    ) -> dict:
        """Proxy a TRPC call against labs.google through the extension.

        No captcha; just Bearer auth passthrough on a `credentials: include`
        fetch. Used for metadata calls like ``project.createProject``.
        """
        return await self._send(
            "trpc_request",
            {"url": url, "method": method, "headers": headers or {}, "body": body},
            timeout=timeout,
        )

    # ── observability ─────────────────────────────────────────────────────
    @property
    def ws_stats(self) -> dict:
        token_age = (
            int(time.time() - self._token_captured_at)
            if self._token_captured_at is not None
            else None
        )
        return {
            "connected": self.connected,
            "flow_key_present": self._flow_key_present,
            "token_age_s": token_age,
            "pending": len(self._pending),
            "request_count": self._request_count,
            "success_count": self._success_count,
            "failed_count": self._failed_count,
            "last_error": self._last_error,
        }


flow_client = FlowClient()


def get_flow_client() -> FlowClient:
    return flow_client
