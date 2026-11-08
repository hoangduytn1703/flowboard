"""Account management — the admin account only (the seed account, ``akiragosho``).

  GET   /api/admin/accounts                      → every account (role, locked, note, data, last login)
  POST  /api/admin/accounts                      {username, password, note?, cloud?, plan?, months?, days?} → a new account
  PATCH /api/admin/accounts/{username}           {disabled?, note?, plan?, months?, days?, stack?, expires_on?}  (locking
                                                 logs it out everywhere; plan + months = a paid term, 0 = forever; days =
                                                 trial length; stack = add onto the time left on the same plan;
                                                 expires_on = "YYYY-MM-DD", any end date the admin picks)
  POST  /api/admin/accounts/{username}/password  {new} → set a new password, logged out everywhere
  POST  /api/admin/accounts/{username}/logout    → logged out on every machine
  POST  /api/admin/accounts/{username}/extend    {months?, days?} → trial: starts over from today; paid plan: + months
  GET   /api/admin/plans                         → the plans, the feature list, accounts per plan
  PUT   /api/admin/plans                         {plans: [{id?, name, features, terms?, days?}]} → replace them all (in order)
  GET   /api/admin/billing                       → bank account, prices, transfer text template, upgrade requests
  PUT   /api/admin/billing                       {bank_bin, account_no, account_name, template, note}
  POST  /api/admin/billing/requests/{id}/approve | /reject → the account moves to the plan it paid for (or not)

Other accounts get 403 here; all they can do is change their own password
(``POST /api/account/password``). New accounts keep their data in their own
schema of the cloud database when this machine has one (``cloud``, default
on), so the friend logs in on any machine without a "move to cloud" step.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from flowboard import accounts, billing, licensing, plans

router = APIRouter(prefix="/api/admin/accounts", tags=["account-admin"])


class CreateBody(BaseModel):
    username: str
    password: str
    note: str = ""
    cloud: bool = True
    plan: Optional[str] = None
    months: Optional[int] = None
    days: Optional[int] = None


class PatchBody(BaseModel):
    disabled: Optional[bool] = None
    note: Optional[str] = None
    plan: Optional[str] = None
    months: Optional[int] = None
    days: Optional[int] = None
    stack: bool = False
    expires_on: Optional[str] = None  # "YYYY-MM-DD": the plan ends at the end of that day (Vietnam time)


class ExtendBody(BaseModel):
    months: Optional[int] = None
    days: Optional[int] = None


class PlansBody(BaseModel):
    plans: list[dict]
    default: Optional[str] = None


class PasswordBody(BaseModel):
    new: str


def _admin(request: Request) -> dict:
    if not accounts.auth_enabled():
        raise HTTPException(400, "Agent đang chạy không đăng nhập (FLOWBOARD_AUTH=off) — không có tài khoản để quản lý.")
    user = accounts.user_from_request(request)
    if user is None:
        raise HTTPException(401, "Chưa đăng nhập")
    if not accounts.is_admin(user):
        raise HTTPException(403, "Chỉ tài khoản quản trị mới quản lý được tài khoản. Bạn chỉ đổi được mật khẩu của mình.")
    if accounts.via_api():
        from flowboard import cloud_api

        raise HTTPException(409, f"Máy này đăng nhập qua {cloud_api.host()}: quản lý tài khoản, gói và thanh toán ở trang quản trị "
                                 f"{cloud_api.site()}/quan-tri.")
    return user


def _guard() -> None:
    """A signed store: what changes an account's rights is signed — only on the admin's machine (licensing.py)."""
    try:
        licensing.guard()
    except licensing.LicenseError as exc:
        raise HTTPException(403, str(exc))


def _target(username: str) -> dict:
    user = accounts.get_user(username)
    if user is None:
        raise HTTPException(404, "Không có tài khoản này.")
    return user


def _row(username: str) -> dict:
    return next(a for a in accounts.account_overview() if a["username"] == username)


@router.get("")
def list_accounts(request: Request) -> dict:
    me = _admin(request)
    if licensing.can_sign():
        try:
            licensing.ensure_epoch()
        except Exception:  # noqa: BLE001 — the list still shows
            pass
    return {"accounts": accounts.account_overview(), "me": me["username"], "cloud": accounts.central_url() is not None,
            "licensing": licensing.status(),
            "min_password": accounts.MIN_PASSWORD}


@router.post("", status_code=201)
def create_account(body: CreateBody, request: Request) -> dict:
    _admin(request)
    _guard()
    name = body.username.strip().lower()
    plan = _plan_id(body.plan) if body.plan else plans.load()["default"]
    try:
        accounts.create_user(name, body.password, accounts.new_account_backend(name, body.cloud), note=body.note, plan=plan,
                             plan_expires=_end(plan, body.months, body.days))
    except accounts.AuthError as exc:
        raise HTTPException(400, str(exc))
    return _row(name)


@router.patch("/{username}")
def update_account(username: str, body: PatchBody, request: Request) -> dict:
    _admin(request)
    target = _target(username)
    if body.disabled is not None or body.plan is not None or body.expires_on:
        _guard()
    if body.disabled is not None:
        if body.disabled and accounts.is_admin(target):
            raise HTTPException(400, "Không khoá được tài khoản quản trị.")
        accounts.set_disabled(target["username"], body.disabled)
    if body.note is not None:
        accounts.set_note(target["username"], body.note)
    if body.plan is not None or body.expires_on:
        if accounts.is_admin(target):
            raise HTTPException(400, "Tài khoản quản trị luôn có mọi tính năng, không cần gói.")
        pid = _plan_id(body.plan or target.get("plan") or plans.load()["default"])
        if body.expires_on:
            accounts.set_plan(target["username"], pid, _end_of_day(body.expires_on))
        else:
            base = target.get("plan_expires") if body.stack and (target.get("plan") or "") == pid else None
            accounts.set_plan(target["username"], pid, _end(pid, body.months, body.days, base))
    return _row(target["username"])


@router.post("/{username}/extend")
def extend_plan(username: str, request: Request, body: Optional[ExtendBody] = None) -> dict:
    """Trial: starts over from today (its length, or `days`). Paid plan: `months` more, on top of the time left."""
    _admin(request)
    _guard()
    target = _target(username)
    if accounts.is_admin(target):
        raise HTTPException(400, "Tài khoản quản trị không có hạn.")
    body = body or ExtendBody()
    pid = target.get("plan") or plans.load()["default"]
    if pid == plans.TRIAL_ID:
        accounts.set_plan(target["username"], pid, _end(pid, None, body.days))
    elif body.months is None:
        raise HTTPException(400, "Chọn thời hạn gia hạn (số tháng, 0 = vĩnh viễn).")
    else:
        accounts.set_plan(target["username"], pid, _end(pid, body.months, None, target.get("plan_expires")))
    return _row(target["username"])


def _end(plan_id: str, months: Optional[int], days: Optional[int], base=None):
    """The end date for a plan + term picked by the admin (no term picked: trial length / paid forever)."""
    if plan_id == plans.TRIAL_ID:
        if days is not None and not 1 <= days <= 365:
            raise HTTPException(400, "Số ngày dùng thử phải từ 1 đến 365.")
        return plans.plan_end(plan_id, days=days, base=base)
    if months is not None and months not in plans.TERM_MONTHS:
        raise HTTPException(400, "Thời hạn không hợp lệ.")
    return plans.plan_end(plan_id, months or 0, base=base)


def _end_of_day(day: str):
    """ "2026-12-31" → 23:59:59 that day in Vietnam (UTC+7), as naive UTC like the central store."""
    try:
        d = datetime.strptime(day.strip()[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Ngày hết hạn chưa đúng dạng (năm-tháng-ngày).")
    if d.year < 2000 or d.year > 2200:
        raise HTTPException(400, "Ngày hết hạn không hợp lệ.")
    return d.replace(hour=23, minute=59, second=59) - timedelta(hours=7)


def _plan_id(pid: str) -> str:
    if pid not in {p["id"] for p in plans.load()["plans"]}:
        raise HTTPException(400, "Không có gói này (có thể vừa bị xoá) — tải lại trang.")
    return pid


def _plans_payload() -> dict:
    data = plans.load(fresh=True)
    counts: dict[str, int] = {}
    for a in accounts.account_overview():
        if a["role"] != accounts.ROLE_ADMIN:
            pid = a["plan"] if a["plan"] in {p["id"] for p in data["plans"]} else data["default"]
            counts[pid] = counts.get(pid, 0) + 1
    return {**data, "features": plans.FEATURES, "counts": counts, "max_plans": plans.MAX_PLANS,
            "trial_id": plans.TRIAL_ID, "trial_days": plans.TRIAL_DAYS, "term_months": plans.TERM_MONTHS,
            "signed": licensing.doc_state(plans.SETTING_KEY), "can_sign": licensing.can_sign()}


plans_router = APIRouter(prefix="/api/admin/plans", tags=["account-admin"])


@plans_router.get("")
def get_plans(request: Request) -> dict:
    _admin(request)
    return _plans_payload()


@plans_router.put("")
def put_plans(body: PlansBody, request: Request) -> dict:
    _admin(request)
    _guard()
    names = [" ".join(str(p.get("name") or "").split()).lower() for p in body.plans]
    if not body.plans or any(not n for n in names):
        raise HTTPException(400, "Mỗi gói cần có tên, và phải còn ít nhất một gói.")
    if len(set(names)) != len(names):
        raise HTTPException(400, "Hai gói trùng tên — đặt tên khác nhau.")
    if len(body.plans) > plans.MAX_PLANS:
        raise HTTPException(400, f"Tối đa {plans.MAX_PLANS} gói.")
    plans.save({"plans": body.plans, "default": body.default})
    return _plans_payload()


billing_router = APIRouter(prefix="/api/admin/billing", tags=["account-admin"])


def _billing_payload() -> dict:
    settings = billing.load()
    all_plans = [p for p in plans.load()["plans"] if p["id"] != plans.TRIAL_ID]
    sample_plan = next((p for p in all_plans if p.get("terms")), all_plans[0] if all_plans else {"id": "", "name": "Premium"})
    term = (sample_plan.get("terms") or [{"months": 1, "price": 0}])[0]
    amount = term["price"]
    text = billing.transfer_text(settings["template"], "tenkhach", sample_plan["name"], plans.term_label(term["months"]))
    return {
        "settings": settings, "banks": billing.BANKS, "ready": billing.ready(settings),
        "default_template": billing.DEFAULT_TEMPLATE, "text_max": billing.TEXT_MAX, "term_months": plans.TERM_MONTHS,
        "signed": licensing.doc_state(billing.SETTING_KEY), "can_sign": licensing.can_sign(),
        "bank_name": billing.bank_name(settings["bank_bin"]),
        # a sample QR the admin scans with their own bank app before sending accounts to it
        "sample": {"plan_name": sample_plan["name"], "term": plans.term_label(term["months"]), "amount": amount, "content": text,
                   "qr": billing.vietqr_payload(settings["bank_bin"], settings["account_no"], amount, text)
                   if billing.ready(settings) else ""},
        "requests": billing.list_requests(),
    }


@billing_router.get("")
def get_billing(request: Request) -> dict:
    _admin(request)
    return _billing_payload()


@billing_router.put("")
def put_billing(body: dict, request: Request) -> dict:
    _admin(request)
    _guard()
    billing.save(body)
    return _billing_payload()


@billing_router.post("/requests/{request_id}/{verdict}")
def decide_request(request_id: int, verdict: str, request: Request) -> dict:
    _admin(request)
    if verdict not in ("approve", "reject"):
        raise HTTPException(404, "Không có thao tác này.")
    if verdict == "approve":
        _guard()
    try:
        billing.decide(request_id, verdict == "approve")
    except billing.BillingError as exc:
        raise HTTPException(400, str(exc))
    return _billing_payload()


@router.post("/{username}/password")
def reset_password(username: str, body: PasswordBody, request: Request) -> dict:
    _admin(request)
    target = _target(username)
    if accounts.is_admin(target):
        raise HTTPException(400, "Mật khẩu của tài khoản quản trị đổi ở trang \"Tài khoản của tôi\" (cần mật khẩu hiện tại).")
    try:
        accounts.set_password(target["username"], body.new)
    except accounts.AuthError as exc:
        raise HTTPException(400, str(exc))
    n = accounts.revoke_sessions(target["username"])
    return {**_row(target["username"]), "logged_out": n}


@router.post("/{username}/logout")
def logout_everywhere(username: str, request: Request) -> dict:
    me = _admin(request)
    target = _target(username)
    keep = request.cookies.get(accounts.SESSION_COOKIE) if target["id"] == me["id"] else None
    n = accounts.revoke_sessions(target["username"], keep=keep)
    return {**_row(target["username"]), "logged_out": n}
