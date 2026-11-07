"""Account management — the admin account only (the seed account, ``akiragosho``).

  GET   /api/admin/accounts                      → every account (role, locked, note, data, last login)
  POST  /api/admin/accounts                      {username, password, note?, cloud?} → a new account
  PATCH /api/admin/accounts/{username}           {disabled?, note?}  (locking logs it out everywhere)
  POST  /api/admin/accounts/{username}/password  {new} → set a new password, logged out everywhere
  POST  /api/admin/accounts/{username}/logout    → logged out on every machine

Other accounts get 403 here; all they can do is change their own password
(``POST /api/account/password``). New accounts keep their data in their own
schema of the cloud database when this machine has one (``cloud``, default
on), so the friend logs in on any machine without a "move to cloud" step.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from flowboard import accounts

router = APIRouter(prefix="/api/admin/accounts", tags=["account-admin"])


class CreateBody(BaseModel):
    username: str
    password: str
    note: str = ""
    cloud: bool = True


class PatchBody(BaseModel):
    disabled: Optional[bool] = None
    note: Optional[str] = None


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
    return user


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
    return {"accounts": accounts.account_overview(), "me": me["username"], "cloud": accounts.central_url() is not None,
            "min_password": accounts.MIN_PASSWORD}


@router.post("", status_code=201)
def create_account(body: CreateBody, request: Request) -> dict:
    _admin(request)
    name = body.username.strip().lower()
    try:
        accounts.create_user(name, body.password, accounts.new_account_backend(name, body.cloud), note=body.note)
    except accounts.AuthError as exc:
        raise HTTPException(400, str(exc))
    return _row(name)


@router.patch("/{username}")
def update_account(username: str, body: PatchBody, request: Request) -> dict:
    _admin(request)
    target = _target(username)
    if body.disabled is not None:
        if body.disabled and accounts.is_admin(target):
            raise HTTPException(400, "Không khoá được tài khoản quản trị.")
        accounts.set_disabled(target["username"], body.disabled)
    if body.note is not None:
        accounts.set_note(target["username"], body.note)
    return _row(target["username"])


@router.post("/{username}/password")
def reset_password(username: str, body: PasswordBody, request: Request) -> dict:
    _admin(request)
    target = _target(username)
    if accounts.is_admin(target):
        raise HTTPException(400, "Mật khẩu của tài khoản quản trị đổi ở \"Đổi mật khẩu\" (cần mật khẩu hiện tại).")
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
