"""User identity and plan, surfaced from the extension.

The extension used to fetch Google's ``/oauth2/v2/userinfo`` as soon as it
captured a Bearer token and push the profile here over WebSocket.

Since Flow moved to flow.google.com there is no Bearer to capture, so that
never fires: **identity is not obtainable on the current transport**. The
paygate tier isn't either — it came from ``/v1/credits``, same token — so it
is now declared in config instead. This route reports the effective tier and
says which of the two it came from, rather than reporting ``null`` and letting
the AccountPanel imply the user should go open a Flow tab to fix it.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from flowboard.services.flow_client import flow_client
from flowboard.services.flow_sdk import resolve_paygate_tier
from flowboard.db import get_session
from flowboard.db.models import AppSetting
from flowboard.services.flow_project import effective_project_id, set_override
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/auth", tags=["auth"])


# Test hook kept for backward compatibility with existing test imports.
# The DB-tier-fallback cache it used to reset is gone — see the
# `_last_observed_paygate_tier_from_db` removal below.
def _reset_db_tier_cache_for_tests() -> None:
    """No-op — preserved so existing tests' `from .auth import
    _reset_db_tier_cache_for_tests` doesn't break. Will be removed in
    v1.2 along with the test imports."""
    return


@router.get("/me")
def get_me() -> dict:
    """Return the cached Google profile + paygate tier from the live
    extension signal only.

    The previous version had a "fall back to last observed tier in DB"
    branch that read `request.params.paygate_tier` from the most recent
    gen request. That branch was a footgun: the worker used to default
    to `PAYGATE_TIER_ONE` when no live tier was present, and that wrong
    value got stamped into request.params, polluting the DB. The next
    /api/auth/me call would then read the polluted row and report Pro
    forever — even for Ultra users — until a fresh known-good gen
    happened to overwrite the fallback row.

    Now: no bogus tier can get into the DB, because the tier is resolved from
    config rather than guessed per request (see
    `flow_sdk.resolve_paygate_tier`), and an unrecognised value fails loud at
    dispatch.

    `paygate_tier` is the tier generation will actually use, so the panel shows
    the real checkpoint. `paygate_tier_source` says where it came from:
    `"extension"` if a live signal was somehow available, `"configured"`
    otherwise — which is the normal case now.

    `identity_available` is False when the transport cannot yield a profile at
    all. Without it the AccountPanel would poll /me every five seconds forever
    waiting for an email that is never coming.
    """
    info = flow_client.user_info or {}
    live_tier = flow_client.paygate_tier
    try:
        effective_tier = resolve_paygate_tier(live_tier)
        tier_error = None
    except ValueError as exc:
        # A misconfigured FLOWBOARD_PAYGATE_TIER. Report it here rather than
        # only at dispatch, so the panel can say why generation will refuse.
        effective_tier, tier_error = None, str(exc)
    return {
        "email": info.get("email"),
        "name": info.get("name"),
        "picture": info.get("picture"),
        "verified_email": info.get("verified_email"),
        "paygate_tier": effective_tier,
        "paygate_tier_source": "extension" if live_tier else "configured",
        "paygate_tier_error": tier_error,
        # Identity and credits both rode on the Bearer token that
        # flow.google.com no longer mints. Genuinely unknown, not pending.
        "identity_available": flow_client.user_info is not None,
        "sku": flow_client.sku,
        "credits": flow_client.credits,
        "accounts": len(flow_client.accounts()),
    }


# ── several Google accounts: one Chrome profile + extension each ─────────────

def _project_key(email: str) -> str:
    return f"flow_project_for:{email.lower()}"


def _remembered_project(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    with get_session() as s:
        row = s.get(AppSetting, _project_key(email))
    return row.value if row and row.value else None


def remember_project_for_active(project_id: Optional[str]) -> None:
    """Called when the pinned project changes: tie it to the active account
    so switching back later re-pins it."""
    conn = flow_client.active_conn
    if conn is None or not conn.email or not project_id:
        return
    with get_session() as s:
        row = s.get(AppSetting, _project_key(conn.email))
        if row is None:
            s.add(AppSetting(key=_project_key(conn.email), value=project_id))
        else:
            row.value = project_id
        s.commit()


def _accounts_payload() -> dict:
    pinned = effective_project_id()
    rows = []
    for a in flow_client.accounts():
        remembered = _remembered_project(a["email"])
        rows.append({**a, "project_id": remembered, "project_is_pinned": remembered == pinned if remembered else None})
    return {"accounts": rows, "active_id": flow_client._active, "pinned_project_id": pinned}


# ── the account pool: several Google accounts in one Chrome ──────────────────

class PoolAccountBody(BaseModel):
    email: str
    project_id: Optional[str] = None
    label: Optional[str] = None
    enabled: Optional[bool] = None


class PoolAutoBody(BaseModel):
    auto: bool


class PoolSwitchBody(BaseModel):
    email: str


@router.get("/pool")
def pool_status() -> dict:
    from flowboard.services.account_pool import account_pool
    return account_pool.status()


@router.put("/pool/accounts")
def pool_upsert(body: PoolAccountBody) -> dict:
    from flowboard.services.account_pool import account_pool
    try:
        account_pool.upsert(body.email, project_id=body.project_id, label=body.label, enabled=body.enabled)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return account_pool.status()


@router.delete("/pool/accounts/{email}")
def pool_remove(email: str) -> dict:
    from flowboard.services.account_pool import account_pool
    if not account_pool.remove(email):
        raise HTTPException(404, "không có tài khoản này trong danh sách")
    return account_pool.status()


@router.put("/pool/auto")
def pool_auto(body: PoolAutoBody) -> dict:
    from flowboard.services.account_pool import account_pool
    account_pool.set_auto(body.auto)
    return account_pool.status()


@router.post("/pool/switch")
async def pool_switch(body: PoolSwitchBody) -> dict:
    """Switch by hand: pin that account's project and ask for its Flow tab."""
    from flowboard.services.account_pool import account_pool
    acc = account_pool.get(body.email)
    if acc is None:
        raise HTTPException(404, "không có tài khoản này trong danh sách")
    if not acc.get("project_id"):
        raise HTTPException(400, "tài khoản này chưa có project id — điền trước")
    await account_pool.begin_switch(acc, cost=0, reason="chuyển tay", from_email=account_pool.current_email())
    return account_pool.status()


@router.post("/pool/check")
async def pool_check() -> dict:
    """Read the Flow tab now (after the user switched accounts there)."""
    from flowboard.services.account_pool import account_pool
    res = await account_pool.check()
    return {**res, "status": account_pool.status()}


@router.post("/pool/open-tab")
async def pool_open_tab(body: Optional[PoolSwitchBody] = None) -> dict:
    from flowboard.services.account_pool import account_pool
    email = body.email if body else (account_pool.pending or {}).get("to_email")
    if not email:
        raise HTTPException(400, "không biết mở tab cho tài khoản nào")
    return {"ok": await account_pool.open_flow_tab(email), "email": email}


@router.post("/pool/dismiss")
def pool_dismiss() -> dict:
    """Drop a pending switch without waiting (the job keeps waiting on its own clock)."""
    from flowboard.services.account_pool import account_pool
    account_pool.pending = None
    return account_pool.status()


@router.get("/accounts")
def list_accounts() -> dict:
    """Every connected extension with what we know about its account."""
    return _accounts_payload()


@router.post("/accounts/refresh")
async def refresh_accounts() -> dict:
    """Re-read email / credits / plan from each extension's Flow tab."""
    results = {}
    for a in flow_client.accounts():
        results[a["id"]] = await flow_client.read_account(a["id"])
    return {**_accounts_payload(), "results": results}


class ActivateBody(BaseModel):
    pin_remembered_project: bool = True


@router.post("/accounts/{conn_id}/activate")
async def activate_account(conn_id: int, body: Optional[ActivateBody] = None) -> dict:
    """Make this connection the one generation uses. Its remembered Flow
    project (the one pinned while it was active before) is pinned again,
    because projects and media ids belong to a Google account."""
    if not flow_client.activate(conn_id):
        raise HTTPException(404, "không có kết nối extension này")
    conn = flow_client.active_conn
    repinned = None
    if (body is None or body.pin_remembered_project) and conn is not None:
        remembered = _remembered_project(conn.email)
        if remembered and remembered != effective_project_id():
            try:
                set_override(remembered)
                repinned = remembered
            except ValueError:
                repinned = None
    return {**_accounts_payload(), "repinned_project_id": repinned}


@router.post("/logout")
async def logout() -> dict:
    """Disconnect the extension's identity from the agent.

    Clears the agent-side cached profile + tier so /api/auth/me
    returns null fields immediately. Sends a `logout` message to the
    extension over WS so it drops its own in-memory cachedUserInfo +
    flowKey — the next time the user wants to reconnect they pick up
    fresh credentials, not stale ones.

    The extension's WS connection itself stays open. We don't tear it
    down because the user might log back in with a different account
    and we want to be ready to push the new identity.
    """
    extension_notified = await flow_client.notify({"type": "logout"})
    flow_client.clear_extension()
    return {
        "ok": True,
        "extension_notified": extension_notified,
    }


@router.post("/scan")
async def scan_extension() -> dict:
    """Diagnostic + nudge for the extension connection.

    Returns a snapshot of the connection state so the frontend can
    decide what to surface to the user, and (when the WS is open but
    the userinfo cache is empty) asks the extension to re-fetch its
    Google profile.

    Cases the frontend cares about:
      - extension_connected=False: Chrome extension isn't running /
        installed / enabled. The frontend shows install instructions.
      - extension_connected=True + has_user_info=False: WS is open but
        Google /oauth2/v2/userinfo hasn't completed yet (or token
        rotated and the cache cleared). We send a `please_resend_userinfo`
        nudge — the extension's handler will re-call its
        fetchAndPushUserInfo flow.
      - extension_connected=True + has_user_info=True + has_tier=False:
        Token captured but the authoritative /v1/credits fetch hasn't
        landed yet (or it failed transiently). The scan handler retries
        the fetch synchronously below so the response reflects the
        post-fetch state.
      - All three present: nothing to do; frontend re-polls /me to
        refresh the AccountPanel.
    """
    nudged = False
    if flow_client.connected and flow_client.user_info is None:
        nudged = await flow_client.notify({"type": "please_resend_userinfo"})
    # Credits + email live on the Flow page's account panel now; read them
    # from the active extension so the badge and /me are current.
    account = await flow_client.read_account() if flow_client.connected else {"error": "extension_disconnected"}
    # If tier is still null but we have a token, do an authoritative
    # /v1/credits fetch right now. Synchronous (not fire-and-forget)
    # so the response reflects the post-fetch state — UI gets a single
    # round-trip instead of having to re-poll /me.
    tier_fetched = False
    if flow_client.paygate_tier is None:
        tier_fetched = await flow_client.fetch_paygate_tier()
    return {
        "extension_connected": flow_client.connected,
        "has_user_info": flow_client.user_info is not None,
        "has_paygate_tier": flow_client.paygate_tier is not None,
        "userinfo_nudged": nudged,
        "tier_fetched": tier_fetched,
        "account": account,
    }
