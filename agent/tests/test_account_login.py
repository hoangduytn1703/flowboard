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
    h = accounts.hash_password("Password@123")
    assert h.startswith("pbkdf2_sha256$") and accounts.verify_password("Password@123", h)
    assert not accounts.verify_password("password@123", h)
    assert not accounts.verify_password("x", "garbage")


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


def test_register_is_closed_unless_enabled(auth_app, monkeypatch):
    assert auth_app.post("/api/account/register", json={"username": "new", "password": "secret123"}).status_code == 403
    monkeypatch.setenv("FLOWBOARD_ALLOW_REGISTER", "1")
    assert auth_app.post("/api/account/register", json={"username": "new", "password": "secret123"}).status_code == 201
    assert auth_app.post("/api/account/register", json={"username": "new", "password": "secret123"}).status_code == 400
    assert auth_app.post("/api/account/register", json={"username": "bad name!", "password": "secret123"}).status_code == 400


def test_change_password(auth_app):
    auth_app.post("/api/account/login", json={"username": "akiragosho", "password": "Password@123"})
    assert auth_app.post("/api/account/password", json={"current": "nope", "new": "NewPass123"}).status_code == 400
    assert auth_app.post("/api/account/password", json={"current": "Password@123", "new": "NewPass123"}).status_code == 200
    auth_app.post("/api/account/logout")
    auth_app.cookies.clear()
    assert auth_app.post("/api/account/login", json={"username": "akiragosho", "password": "NewPass123"}).status_code == 200
