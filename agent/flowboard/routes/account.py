"""Login / logout / who am I (the Flowboard account, not the Flow account).

  POST /api/account/login     {username, password} → sets the session cookie
  POST /api/account/logout
  GET  /api/account/me        → 401 when not logged in
  POST /api/account/password  {current, new}  (logs the account out on its other machines)
  GET  /api/account/prefs     → the UI preferences saved for this account (model picks …)
  PUT  /api/account/prefs     {…} → stored in the account's database (follows the login)
  GET  /api/account/upgrade              → plans with prices, current plan, a pending request (billing.py)
  POST /api/account/upgrade/quote        {plan_id, months} → VietQR + amount + transfer text + the new end date
  POST /api/account/upgrade/request      {plan_id, months} → "Tôi đã chuyển khoản": files a request for the admin
  POST /api/account/upgrade/cancel       → withdraws the pending request
  GET  /api/account/upgrades             → this account's upgrade requests (transaction history)
  PUT  /api/account/profile              {display_name, phone, email, contact} → "Tài khoản của tôi"
  POST /api/account/logout-others        → logged out on every other machine / browser

New accounts are made by the admin only (routes/account_admin.py) — there is
no open sign-up in the app (people sign up on the DFlow website).

Phase C (8/11): on a machine that logs in through the website (cloud_api.py) the password, profile and "log out other
machines" go to the website's app API; this machine's own login sessions are handled here as before.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from flowboard import accounts, billing, plans
from flowboard.db import get_session, has_engine
from flowboard.db.models import AppSetting

router = APIRouter(prefix="/api/account", tags=["account"])

#: AppSetting row (in the account's own database) holding the UI preferences.
PREFS_KEY = "ui_prefs"


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    current: str
    new: str


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(accounts.SESSION_COOKIE, token, max_age=accounts.SESSION_TTL_S, httponly=True,
                    samesite="lax", secure=False, path="/")


def _me_payload(user: dict) -> dict:
    return {"auth": True, "username": user["username"], "created_at": user["created_at"].isoformat() if user.get("created_at") else None,
            "backend": (user.get("backend") or {}).get("type", "sqlite"), "is_admin": accounts.is_admin(user),
            "profile": user.get("profile") or {k: "" for k in accounts.PROFILE_KEYS}, **_plan_payload(user), "site": _site()}


def _site() -> Optional[dict]:
    """Phase C: the DFlow website this machine logs in through (account admin, sign-up and renewals live there)."""
    from flowboard import cloud_api

    if not cloud_api.enabled():
        return None
    base = cloud_api.site()
    return {"url": base, "host": cloud_api.host(), "account": f"{base}/tai-khoan", "admin": f"{base}/quan-tri"}


def _api(username: str, method: str, path: str, body: Optional[dict] = None) -> dict:
    from flowboard import cloud_api

    try:
        return cloud_api.account_call(username, method, path, body=body)
    except cloud_api.ApiError as exc:
        raise HTTPException(401 if exc.status == 401 else 502 if exc.offline else 400, exc.detail)


def _plan_payload(user: dict) -> dict:
    """The account's plan and the features the UI may show (plans.py)."""
    plan = plans.plan_of(user)
    end = user.get("plan_expires") if not accounts.is_admin(user) else None
    return {"plan": {"id": plan["id"], "name": plan["name"], "trial": plan["id"] == plans.TRIAL_ID,
                     "expires_at": end.isoformat() if end else None},
            "features": list(plan["features"])}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    if not accounts.auth_enabled():
        return {"auth": False, "username": "local"}
    try:
        user = accounts.authenticate(body.username, body.password)
    except accounts.AuthError as exc:
        raise HTTPException(401, str(exc))
    try:
        accounts.activate(user)
    except accounts.AccountBusy as exc:
        raise HTTPException(409, str(exc))
    # The agent runs on the user's own machine, so a local caller is "this machine" (its name);
    # only a caller from elsewhere is recorded by address.
    client = request.client.host if request.client else None
    remote = client not in (None, "127.0.0.1", "::1", "localhost", "testclient")
    token = accounts.create_session(user, host=client if remote else None)
    _set_cookie(response, token)
    return _me_payload(user)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    accounts.delete_session(request.cookies.get(accounts.SESSION_COOKIE))
    response.delete_cookie(accounts.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    if not accounts.auth_enabled():
        return {"auth": False, "username": "local", "backend": "sqlite", "features": list(plans.FEATURE_KEYS)}
    user = accounts.user_from_request(request)
    if user is None:
        raise HTTPException(401, "Chưa đăng nhập")
    return _me_payload(user)


@router.post("/password")
def change_password(body: PasswordBody, request: Request) -> dict:
    user = accounts.user_from_request(request)
    if user is None:
        raise HTTPException(401, "Chưa đăng nhập")
    if not accounts.verify_password(body.current, user["password_hash"], user["username"]):
        raise HTTPException(400, "Mật khẩu hiện tại không đúng.")
    if body.new == body.current:
        raise HTTPException(400, "Mật khẩu mới phải khác mật khẩu hiện tại.")
    if accounts.via_api():
        from flowboard import cloud_api

        out = _api(user["username"], "POST", "/api/app/account/password", {"current": body.current, "new": body.new})
        cloud_api._save_token(user["username"], out.get("token"))
    try:
        accounts.set_password(user["username"], body.new)  # (via the website: this machine's copy, for logging in offline)
    except accounts.AuthError as exc:
        raise HTTPException(400, str(exc))
    # Whoever else knew the old password is logged out; this browser stays in.
    others = accounts.revoke_sessions(user["username"], keep=request.cookies.get(accounts.SESSION_COOKIE))
    return {"ok": True, "logged_out": others}


class UpgradeBody(BaseModel):
    plan_id: str
    months: int = 0  # plans.TERM_MONTHS; 0 = forever


def _me(request: Request) -> dict:
    user = accounts.user_from_request(request)
    if user is None:
        raise HTTPException(401, "Chưa đăng nhập")
    if accounts.is_admin(user):
        raise HTTPException(400, "Tài khoản quản trị đã có mọi tính năng.")
    return user


@router.get("/upgrade")
def upgrade_offer(request: Request) -> dict:
    return billing.offer(_me(request))


@router.post("/upgrade/quote")
def upgrade_quote(body: UpgradeBody, request: Request) -> dict:
    try:
        return billing.quote(_me(request), body.plan_id, body.months)
    except billing.BillingError as exc:
        raise HTTPException(400, str(exc))


@router.post("/upgrade/request")
def upgrade_request(body: UpgradeBody, request: Request) -> dict:
    try:
        return billing.file_request(_me(request), body.plan_id, body.months)
    except billing.BillingError as exc:
        raise HTTPException(400, str(exc))


@router.post("/upgrade/cancel")
def upgrade_cancel(request: Request) -> dict:
    billing.cancel_request(_me(request)["username"])
    return {"ok": True}


class ProfileBody(BaseModel):
    display_name: str = ""
    phone: str = ""
    email: str = ""
    contact: str = ""


@router.put("/profile")
def save_profile(body: ProfileBody, request: Request) -> dict:
    user = accounts.user_from_request(request)
    if user is None:
        raise HTTPException(401, "Chưa đăng nhập")
    email = body.email.strip()
    if email and ("@" not in email or " " in email or len(email) > 120):
        raise HTTPException(400, "Email chưa đúng dạng.")
    if accounts.via_api():
        from flowboard import cloud_api

        cloud_api.store(_api(user["username"], "PUT", "/api/app/account/profile", body.model_dump()))
    else:
        accounts.set_profile(user["username"], body.model_dump())
    return _me_payload(accounts.get_user(user["username"]) or user)


@router.get("/upgrades")
def my_upgrades(request: Request) -> dict:
    user = accounts.user_from_request(request)
    if user is None:
        raise HTTPException(401, "Chưa đăng nhập")
    return {"requests": billing.list_requests(50, username=user["username"])}


@router.post("/logout-others")
def logout_others(request: Request) -> dict:
    user = accounts.user_from_request(request)
    if user is None:
        raise HTTPException(401, "Chưa đăng nhập")
    if accounts.via_api():  # every other machine's token stops counting on the website; they notice within minutes
        from flowboard import cloud_api

        out = _api(user["username"], "POST", "/api/app/account/logout-others")
        cloud_api._save_token(user["username"], out.get("token"))
    n = accounts.revoke_sessions(user["username"], keep=request.cookies.get(accounts.SESSION_COOKIE))
    return {"ok": True, "logged_out": n}


@router.get("/prefs")
def get_prefs() -> dict:
    """The preferences the browser keeps in localStorage, but per account:
    image / video model, image source, UI mode … Empty when never saved."""
    import json

    if not has_engine():
        return {}
    with get_session() as s:
        row = s.get(AppSetting, PREFS_KEY)
    if row is None:
        return {}
    try:
        data = json.loads(row.value)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


@router.put("/prefs")
def put_prefs(body: dict) -> dict:
    import json

    if not has_engine():
        raise HTTPException(401, "Chưa đăng nhập")
    clean = {k: v for k, v in body.items() if isinstance(k, str) and isinstance(v, (str, int, float, bool))}
    with get_session() as s:
        row = s.get(AppSetting, PREFS_KEY)
        if row is None:
            s.add(AppSetting(key=PREFS_KEY, value=json.dumps(clean, ensure_ascii=False)))
        else:
            row.value = json.dumps(clean, ensure_ascii=False)
            s.add(row)
        s.commit()
    return clean

