"""Login / logout / who am I (the Flowboard account, not the Flow account).

  POST /api/account/login     {username, password} → sets the session cookie
  POST /api/account/logout
  GET  /api/account/me        → 401 when not logged in
  POST /api/account/password  {current, new}
  POST /api/account/register  {username, password}  (only with FLOWBOARD_ALLOW_REGISTER=1)
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from flowboard import accounts

router = APIRouter(prefix="/api/account", tags=["account"])


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
            "backend": (user.get("backend") or {}).get("type", "sqlite")}


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
    token = accounts.create_session(user, host=request.client.host if request.client else None)
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
        return {"auth": False, "username": "local", "backend": "sqlite"}
    user = accounts.user_from_request(request)
    if user is None:
        raise HTTPException(401, "Chưa đăng nhập")
    return _me_payload(user)


@router.post("/password")
def change_password(body: PasswordBody, request: Request) -> dict:
    user = accounts.user_from_request(request)
    if user is None:
        raise HTTPException(401, "Chưa đăng nhập")
    if not accounts.verify_password(body.current, user["password_hash"]):
        raise HTTPException(400, "Mật khẩu hiện tại không đúng.")
    try:
        accounts.set_password(user["username"], body.new)
    except accounts.AuthError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@router.post("/register", status_code=201)
def register(body: LoginBody) -> dict:
    if os.getenv("FLOWBOARD_ALLOW_REGISTER") != "1":
        raise HTTPException(403, "Chưa mở đăng ký. Đặt FLOWBOARD_ALLOW_REGISTER=1 trong .env để tạo tài khoản mới.")
    try:
        user = accounts.create_user(body.username, body.password)
    except accounts.AuthError as exc:
        raise HTTPException(400, str(exc))
    return {"username": user["username"]}
