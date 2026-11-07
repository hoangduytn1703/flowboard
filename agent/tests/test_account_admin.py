"""Account management: only the admin (seed account) makes / locks / resets
accounts; everyone else can only change their own password (auth ON here)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text

from flowboard import accounts, config
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


def _client(app, creds) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/account/login", json=creds)
    assert r.status_code == 200, r.text
    return c


def test_the_seed_account_is_the_admin_and_can_make_accounts(auth_app):
    admin = _client(auth_app, ADMIN)
    assert admin.get("/api/account/me").json()["is_admin"] is True
    r = admin.post("/api/admin/accounts", json={"username": "Ban.A", "password": "secret123", "note": "bạn A"})
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["username"] == "ban.a" and row["role"] == "user" and row["note"] == "bạn A"
    assert row["backend"] == "sqlite"  # no cloud database in tests
    # Bad / duplicate input is refused with the reason.
    assert admin.post("/api/admin/accounts", json={"username": "ban.a", "password": "secret123"}).status_code == 400
    assert admin.post("/api/admin/accounts", json={"username": "x y", "password": "secret123"}).status_code == 400
    assert admin.post("/api/admin/accounts", json={"username": "short", "password": "123"}).status_code == 400
    names = [a["username"] for a in admin.get("/api/admin/accounts").json()["accounts"]]
    assert names == ["akiragosho", "ban.a"]
    # The new account logs in and is not an admin.
    friend = _client(auth_app, {"username": "ban.a", "password": "secret123"})
    assert friend.get("/api/account/me").json()["is_admin"] is False


def test_other_accounts_cannot_manage_accounts(auth_app):
    accounts.create_user("ban", "secret123")
    friend = _client(auth_app, {"username": "ban", "password": "secret123"})
    assert friend.get("/api/admin/accounts").status_code == 403
    assert friend.post("/api/admin/accounts", json={"username": "x", "password": "secret123"}).status_code == 403
    assert friend.post("/api/admin/accounts/akiragosho/password", json={"new": "hacked123"}).status_code == 403
    assert friend.patch("/api/admin/accounts/akiragosho", json={"disabled": True}).status_code == 403
    assert accounts.get_user("x") is None
    # …but changes its own password.
    assert friend.post("/api/account/password", json={"current": "secret123", "new": "secret456"}).status_code == 200


def test_locking_logs_the_account_out_and_keeps_it_out(auth_app):
    accounts.create_user("ban", "secret123")
    friend = _client(auth_app, {"username": "ban", "password": "secret123"})
    admin = _client(auth_app, ADMIN)
    row = admin.patch("/api/admin/accounts/ban", json={"disabled": True, "note": "hết hạn"}).json()
    assert row["disabled"] is True and row["note"] == "hết hạn" and row["sessions"] == 0
    assert friend.get("/api/account/me").status_code == 401
    r = TestClient(auth_app).post("/api/account/login", json={"username": "ban", "password": "secret123"})
    assert r.status_code == 401 and "khoá" in r.json()["detail"]
    # The admin cannot be locked; unlocking lets the friend back in.
    assert admin.patch("/api/admin/accounts/akiragosho", json={"disabled": True}).status_code == 400
    assert admin.patch("/api/admin/accounts/ban", json={"disabled": False}).json()["disabled"] is False
    _client(auth_app, {"username": "ban", "password": "secret123"})


def test_reset_password_and_log_out_everywhere(auth_app):
    accounts.create_user("ban", "secret123")
    friend = _client(auth_app, {"username": "ban", "password": "secret123"})
    admin = _client(auth_app, ADMIN)
    r = admin.post("/api/admin/accounts/ban/password", json={"new": "fresh123"})
    assert r.status_code == 200 and r.json()["logged_out"] == 1
    assert friend.get("/api/account/me").status_code == 401
    _client(auth_app, {"username": "ban", "password": "fresh123"})
    # The admin's own password only changes with the current one.
    assert admin.post("/api/admin/accounts/akiragosho/password", json={"new": "fresh123"}).status_code == 400
    friend2 = _client(auth_app, {"username": "ban", "password": "fresh123"})
    assert admin.post("/api/admin/accounts/ban/logout").json()["logged_out"] >= 1
    assert friend2.get("/api/account/me").status_code == 401
    # Logging yourself out everywhere keeps this browser in.
    assert admin.post("/api/admin/accounts/akiragosho/logout").status_code == 200
    assert admin.get("/api/account/me").status_code == 200


def test_changing_your_password_logs_out_your_other_machines(auth_app):
    accounts.create_user("ban", "secret123")
    here = _client(auth_app, {"username": "ban", "password": "secret123"})
    there = _client(auth_app, {"username": "ban", "password": "secret123"})
    assert here.post("/api/account/password", json={"current": "secret123", "new": "secret123"}).status_code == 400
    r = here.post("/api/account/password", json={"current": "secret123", "new": "newpass123"})
    assert r.status_code == 200 and r.json()["logged_out"] == 1
    assert here.get("/api/account/me").status_code == 200
    assert there.get("/api/account/me").status_code == 401


def test_new_accounts_go_to_the_cloud_when_there_is_one(monkeypatch):
    monkeypatch.setenv("FLOWBOARD_CENTRAL_DB_URL", "postgresql://u:p@host-pooler.example/db")
    assert accounts.new_account_backend("Ban.A") == {"type": "postgres", "schema": "acct_ban_a"}
    assert accounts.new_account_backend("ban", cloud=False) == {"type": "sqlite"}
    monkeypatch.setenv("FLOWBOARD_CENTRAL_DB_URL", "")
    assert accounts.new_account_backend("ban") == {"type": "sqlite"}


def test_an_older_central_store_gets_the_new_columns_and_the_seed_becomes_admin(tmp_path, monkeypatch):
    """Neon's account_user predates role / disabled / note: they are added, nothing else changes."""
    from datetime import datetime

    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    eng = db_session.make_engine(tmp_path / "accounts.db")
    md = MetaData()
    old = Table("account_user", md, Column("id", Integer, primary_key=True), Column("username", String(64)),
                Column("password_hash", String(256)), Column("created_at", DateTime), Column("backend", Text))
    md.create_all(eng)
    with eng.begin() as c:
        for i, name in enumerate(["akiragosho", "ban"], 1):
            c.execute(old.insert().values(id=i, username=name, password_hash=accounts.hash_password("secret123"),
                                          created_at=datetime(2026, 10, 22), backend='{"type": "sqlite"}'))
    eng.dispose()
    accounts.reset_central()
    try:
        users = {u["username"]: u for u in accounts.list_users()}
        assert users["akiragosho"]["role"] == "admin" and users["ban"]["role"] == "user"
        assert users["ban"]["disabled"] is False and users["ban"]["note"] == ""
        accounts.authenticate("ban", "secret123")
    finally:
        accounts.reset_central()
