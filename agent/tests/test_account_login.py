"""Login, sessions, and data isolation between accounts (auth switched ON
for this module only; the rest of the suite runs with FLOWBOARD_AUTH=off)."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowboard import accounts, config
from flowboard.db import session as db_session


@pytest.fixture
def auth_app(tmp_path, monkeypatch):
    """A fresh central store + per-account data under tmp_path, auth on."""
    monkeypatch.setenv("FLOWBOARD_AUTH", "on")
    monkeypatch.delenv("FLOWBOARD_ALLOW_REGISTER", raising=False)
    monkeypatch.setattr(accounts, "_ROOT_STORAGE", tmp_path)
    monkeypatch.setattr(accounts, "_ROOT_DB", tmp_path / "flowboard.db")
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "flowboard.db")
    accounts.reset_central()
    accounts.deactivate()
    default_engine = db_session.current_engine()
    from flowboard.main import app
    accounts.startup()
    yield TestClient(app)
    accounts.deactivate()
    accounts.reset_central()
    db_session.set_engine(default_engine)


def test_password_hashing_round_trip():
    h = accounts.hash_password("Password@123", "akiragosho")
    assert h.startswith("dflow2$") and accounts.verify_password("Password@123", h, "akiragosho")
    assert not accounts.verify_password("password@123", h, "akiragosho")
    assert not accounts.verify_password("Password@123", h, "ban")  # bound to the account: no copying it onto another row
    assert not accounts.verify_password("x", "garbage", "akiragosho")


def test_seed_account_exists_and_api_needs_login(auth_app):
    users = accounts.list_users()
    assert [u["username"] for u in users] == ["akiragosho"]
    assert auth_app.get("/api/boards").status_code == 401
    assert auth_app.get("/api/account/me").status_code == 401
    assert auth_app.get("/api/health").status_code == 200  # open
    assert auth_app.post("/api/account/login", json={"username": "akiragosho", "password": "wrong"}).status_code == 401


def test_login_sets_cookie_and_opens_the_account_data(auth_app, tmp_path):
    r = auth_app.post("/api/account/login", json={"username": "akiragosho", "password": "Password@123"})
    assert r.status_code == 200 and r.json()["username"] == "akiragosho"
    assert accounts.SESSION_COOKIE in auth_app.cookies
    me = auth_app.get("/api/account/me")
    assert me.status_code == 200 and me.json()["auth"] is True
    # The account's own data folder and database.
    assert (tmp_path / "accounts" / "akiragosho" / "flowboard.db").is_file()
    assert Path(config.STORAGE_DIR) == tmp_path / "accounts" / "akiragosho"
    r = auth_app.post("/api/boards", json={"name": "Clip của akira"})
    assert r.status_code in (200, 201), r.text
    assert [b["name"] for b in auth_app.get("/api/boards").json()] == ["Clip của akira"]
    # Logout: cookie gone, API closed again.
    assert auth_app.post("/api/account/logout").status_code == 200
    auth_app.cookies.clear()
    assert auth_app.get("/api/boards").status_code == 401


def test_remember_me_keeps_the_login_and_the_other_kind_ends_with_the_browser(auth_app, monkeypatch):
    from datetime import timedelta

    # ticked (and what older pages send): a cookie with an age, renewed by /me; 90 days idle before it ends
    r = auth_app.post("/api/account/login", json={"username": "akiragosho", "password": "Password@123", "remember": True})
    assert r.status_code == 200
    head = r.headers["set-cookie"]
    assert f"Max-Age={accounts.SESSION_TTL_S}" in head and accounts.SESSION_TTL_S == 90 * 24 * 3600
    me = auth_app.get("/api/account/me")
    assert me.json()["remembered"] is True and f"Max-Age={accounts.SESSION_TTL_S}" in me.headers["set-cookie"]
    long_token = auth_app.cookies.get(accounts.SESSION_COOKIE)
    assert accounts.session_remembered(long_token)
    auth_app.cookies.clear()

    # not ticked: no Max-Age (the browser / app drops it on close), /me does not renew it, a day idle ends it
    r = auth_app.post("/api/account/login", json={"username": "akiragosho", "password": "Password@123", "remember": False})
    assert r.status_code == 200 and "Max-Age" not in r.headers["set-cookie"]
    short = auth_app.cookies.get(accounts.SESSION_COOKIE)
    assert not accounts.session_remembered(short) and short.split(".")[1] == "s"
    me = auth_app.get("/api/account/me")
    assert me.status_code == 200 and me.json()["remembered"] is False and "set-cookie" not in me.headers
    # the mark cannot be taken off the cookie: the store keeps a hash of the whole token
    uid, _, rand = short.split(".", 2)
    assert accounts.resolve_session(f"{uid}.{rand}") is None
    # two days without use: the short one has ended, the remembered one still works
    later = accounts._now() + timedelta(days=2)
    monkeypatch.setattr(accounts, "_now", lambda: later)
    accounts._session_cache.clear()
    assert accounts.resolve_session(short) is None
    assert accounts.resolve_session(long_token) is not None


def test_two_accounts_do_not_see_each_other(auth_app, tmp_path):
    accounts.create_user("ban", "secret123")
    auth_app.post("/api/account/login", json={"username": "akiragosho", "password": "Password@123"})
    auth_app.post("/api/boards", json={"name": "của akira"})
    auth_app.post("/api/account/logout")
    auth_app.cookies.clear()

    r = auth_app.post("/api/account/login", json={"username": "ban", "password": "secret123"})
    assert r.status_code == 200
    assert auth_app.get("/api/boards").json() == []
    auth_app.post("/api/boards", json={"name": "của bạn"})
    assert (tmp_path / "accounts" / "ban" / "flowboard.db").is_file()
    auth_app.post("/api/account/logout")
    auth_app.cookies.clear()

    auth_app.post("/api/account/login", json={"username": "akiragosho", "password": "Password@123"})
    assert [b["name"] for b in auth_app.get("/api/boards").json()] == ["của akira"]


def test_first_login_adopts_the_old_single_user_data(auth_app, tmp_path):
    # Old layout: storage/flowboard.db + storage/media — made before login existed.
    old_engine = db_session.make_engine(tmp_path / "flowboard.db")
    from flowboard.db import init_db
    init_db(old_engine)
    with old_engine.begin() as c:
        c.exec_driver_sql("INSERT INTO board (name, data, created_at) VALUES ('clip cũ', '{}', '2026-10-01 00:00:00')")
    old_engine.dispose()
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "x.png").write_bytes(b"png")

    auth_app.post("/api/account/login", json={"username": "akiragosho", "password": "Password@123"})
    assert [b["name"] for b in auth_app.get("/api/boards").json()] == ["clip cũ"]
    assert (tmp_path / "accounts" / "akiragosho" / "media" / "x.png").is_file()
    assert not (tmp_path / "flowboard.db").exists()


def test_there_is_no_open_sign_up(auth_app, monkeypatch):
    """Accounts are made by the admin only (test_account_admin.py)."""
    monkeypatch.setenv("FLOWBOARD_ALLOW_REGISTER", "1")
    r = auth_app.post("/api/account/register", json={"username": "new", "password": "secret123"})
    assert r.status_code in (401, 404, 405)
    assert accounts.get_user("new") is None


def test_change_password(auth_app):
    auth_app.post("/api/account/login", json={"username": "akiragosho", "password": "Password@123"})
    assert auth_app.post("/api/account/password", json={"current": "nope", "new": "NewPass123"}).status_code == 400
    assert auth_app.post("/api/account/password", json={"current": "Password@123", "new": "NewPass123"}).status_code == 200
    auth_app.post("/api/account/logout")
    auth_app.cookies.clear()
    assert auth_app.post("/api/account/login", json={"username": "akiragosho", "password": "NewPass123"}).status_code == 200


def test_secrets_and_prefs_follow_the_account(auth_app, tmp_path, monkeypatch):
    """API keys live in the central store per account (adopted once from
    this machine's secrets.json); UI preferences live in the account's DB."""
    from flowboard.services.llm import secrets

    local = tmp_path / "secrets.json"
    local.write_text('{"geminiApiKeys": ["AIza-from-file"]}')
    monkeypatch.delenv("FLOWBOARD_SECRETS_PATH", raising=False)
    monkeypatch.setattr(secrets, "_DEFAULT_PATH", local)
    secrets.forget_cache()
    c = auth_app
    assert c.post("/api/account/login", json={"username": "akiragosho", "password": "Password@123"}).status_code == 200
    # First read adopts the file into the account's central row.
    assert secrets.get_gemini_keys() == ["AIza-from-file"]
    assert accounts.get_setting("secrets:akiragosho") == {"geminiApiKeys": ["AIza-from-file"]}
    secrets.set_gemini_keys(["AIza-new"])
    assert accounts.get_setting("secrets:akiragosho")["geminiApiKeys"] == ["AIza-new"]
    assert '"AIza-new"' not in local.read_text()  # the file is not written any more
    # Preferences round-trip through the account's own database.
    assert c.get("/api/account/prefs").json() == {}
    r = c.put("/api/account/prefs", json={"imageModel": "NANO_BANANA_PRO", "uiMode": "canvas", "nested": {"x": 1}})
    assert r.status_code == 200 and r.json() == {"imageModel": "NANO_BANANA_PRO", "uiMode": "canvas"}
    assert c.get("/api/account/prefs").json()["uiMode"] == "canvas"
    secrets.forget_cache()
