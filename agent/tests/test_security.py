"""Hardening: the installed app always logs in and seeds no known admin, the account store keeps only hashes of session
cookies, and pages of other websites cannot drive the local agent."""
import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from flowboard import accounts, config, licensing
from flowboard.db import session as db_session

ADMIN = {"username": "akiragosho", "password": "Password@123"}


@pytest.fixture
def auth_app(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWBOARD_AUTH", "on")
    monkeypatch.setattr(accounts, "_ROOT_STORAGE", tmp_path)
    monkeypatch.setattr(accounts, "_ROOT_DB", tmp_path / "flowboard.db")
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "flowboard.db")
    accounts.reset_central()
    accounts.deactivate()
    default_engine = db_session.current_engine()
    from flowboard.main import app
    accounts.startup()
    yield app
    accounts.deactivate()
    accounts.reset_central()
    db_session.set_engine(default_engine)


def test_the_store_keeps_only_a_hash_of_the_session_cookie(auth_app):
    c = TestClient(auth_app)
    assert c.post("/api/account/login", json=ADMIN).status_code == 200
    cookie = c.cookies.get(accounts.SESSION_COOKIE)
    with accounts.central_engine().connect() as conn:
        stored = [r.token for r in conn.execute(select(accounts.sessions)).all()]
    assert cookie not in stored and licensing.session_key(cookie) in stored and hashlib.sha256(cookie.encode()).hexdigest() not in stored
    # what someone reads from the table is no login
    thief = TestClient(auth_app)
    thief.cookies.set(accounts.SESSION_COOKIE, stored[0])
    assert thief.get("/api/account/me").status_code == 401
    assert c.get("/api/account/me").status_code == 200
    # logging out removes it
    c.post("/api/account/logout")
    with accounts.central_engine().connect() as conn:
        assert conn.execute(select(accounts.sessions)).all() == []


def test_pages_of_other_websites_cannot_drive_the_agent(auth_app):
    c = TestClient(auth_app)
    r = c.post("/api/account/login", json=ADMIN, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post("/api/app/connect", json={"central_db_url": "postgresql://x"}, headers={"Origin": "null"})
    assert r.status_code == 403
    for ok in ("http://localhost:5174", "http://127.0.0.1:8434", "chrome-extension://abcdefghijklmnopabcdefghijklmnop"):
        assert c.post("/api/account/login", json=ADMIN, headers={"Origin": ok}).status_code == 200
    # reading is not offered to foreign pages either (no CORS grant)
    r = c.get("/api/health", headers={"Origin": "https://evil.example"})
    assert r.headers.get("access-control-allow-origin") is None
    r = c.get("/api/health", headers={"Origin": "http://localhost:5174"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5174"


def test_the_installed_app_always_logs_in_and_seeds_no_known_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PACKAGED", True)
    monkeypatch.setenv("FLOWBOARD_AUTH", "off")
    assert accounts.auth_enabled() is True  # .env cannot switch the login off
    monkeypatch.setattr(accounts, "_ROOT_STORAGE", tmp_path)
    monkeypatch.setattr(accounts, "_ROOT_DB", tmp_path / "flowboard.db")
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    accounts.reset_central()
    try:
        assert accounts.seed_default() is False and accounts.list_users() == []
        with pytest.raises(accounts.AuthError):
            accounts.authenticate("akiragosho", "Password@123")
    finally:
        accounts.reset_central()
