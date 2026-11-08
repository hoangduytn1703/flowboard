"""Service plans: the admin edits plans (features per plan, order, the built-in trial's length) and gives each account
one; the account's features gate both the UI (/api/account/me) and the API routes; an ended trial cannot log in."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from flowboard import accounts, config, plans
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


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_routes_map_to_features():
    assert plans.feature_for("GET", "/api/dub/jobs") == ("dub",)
    assert plans.feature_for("GET", "/api/dub/status") is None  # Bước 4 asks it on every clip
    assert plans.feature_for("POST", "/api/clean/abc/detect") == ("clean", "dub", "cut")
    assert plans.feature_for("POST", "/api/clean/jobs") == ("clean",)
    assert plans.feature_for("GET", "/api/posts") == ("posts", "facebook")
    assert plans.feature_for("POST", "/api/posts/write") == ("posts",)
    assert plans.feature_for("POST", "/api/posts/clip-hooks") is None
    assert plans.feature_for("POST", "/api/schedule/12/publish") == ("facebook",)
    assert plans.feature_for("POST", "/api/channels/3/facebook") == ("facebook",)
    assert plans.feature_for("GET", "/api/channels") is None  # the clip dialogs list channels
    assert plans.feature_for("GET", "/api/boards") is None
    assert plans.feature_for("POST", "/api/assistant/chat") == ("assistant",)


def test_plans_normalize_keeps_them_sane():
    data = plans.normalize({"plans": [
        {"id": "vip", "name": "  VIP  ", "features": ["dub", "nope", "posts"]},
        {"name": "vip", "features": []},            # same name → dropped
        {"id": "admin", "name": "Gói A", "features": []},  # reserved id → new slug
        {"name": "", "features": ["dub"]},          # no name → dropped
        {"id": "trial", "name": "Thử 3 ngày", "features": ["posts"], "days": 3},  # the trial moves first
    ], "default": "vip"})
    assert [p["name"] for p in data["plans"]] == ["Thử 3 ngày", "VIP", "Gói A"]
    assert data["plans"][0] == {"id": "trial", "name": "Thử 3 ngày", "features": ["posts"], "days": 3}
    assert data["plans"][1]["features"] == ["dub", "posts"]
    assert data["plans"][2]["id"] not in ("admin", "trial")
    assert data["default"] == "trial"  # the trial is always the default
    assert plans.normalize({"plans": [{"name": "Chỉ một gói"}]})["plans"][0]["id"] == "trial"  # added when missing
    assert plans.normalize({"plans": [{"id": "trial", "name": "T", "days": 5}]})["plans"][0]["days"] == plans.DEFAULT_TRIAL_DAYS
    assert [p["id"] for p in plans.normalize({})["plans"]] == ["trial", "vip", "pro", "premium"]


def test_a_plan_without_dub_hides_and_refuses_dubbing(auth_app):
    admin = _client(auth_app, ADMIN)
    assert set(admin.get("/api/account/me").json()["features"]) == set(plans.FEATURE_KEYS)
    r = admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "vip"})
    assert r.status_code == 201 and r.json()["plan"] == "vip" and r.json()["plan_expires"] is None
    friend = _client(auth_app, {"username": "ban", "password": "secret123"})
    me = friend.get("/api/account/me").json()
    assert me["plan"] == {"id": "vip", "name": "VIP", "trial": False, "expires_at": None} and "dub" not in me["features"]
    r = friend.get("/api/dub/jobs")
    assert r.status_code == 403 and "VIP" in r.json()["detail"] and r.json()["feature"] == "dub"
    assert friend.get("/api/dub/status").status_code == 200  # shared helper stays open
    assert friend.get("/api/boards").status_code == 200       # core clip making is never gated
    # The admin moves the friend to Premium: dubbing opens at once.
    assert admin.patch("/api/admin/accounts/ban", json={"plan": "premium"}).json()["plan"] == "premium"
    assert "dub" in friend.get("/api/account/me").json()["features"]
    assert friend.get("/api/dub/jobs").status_code == 200


def test_the_admin_edits_and_reorders_plans_and_the_trial_stays_first(auth_app):
    admin = _client(auth_app, ADMIN)
    data = admin.get("/api/admin/plans").json()
    assert [p["id"] for p in data["plans"]] == ["trial", "vip", "pro", "premium"] and data["default"] == "trial"
    assert data["trial_days"] == [3, 7, 14, 30] and data["plans"][0]["days"] == 7
    admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "pro"})
    # Premium before VIP, Pro dropped, a new plan, the trial left out of the list and set to 14 days.
    r = admin.put("/api/admin/plans", json={"plans": [
        {"id": "premium", "name": "Premium", "features": plans.FEATURE_KEYS},
        {"id": "vip", "name": "VIP Vàng", "features": ["dub"]},
        {"id": "goi-moi", "name": "Gói mới", "features": ["auto_clip"]},
        {"id": "trial", "name": "Dùng thử", "features": ["posts"], "days": 14},
    ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["id"] for p in body["plans"]] == ["trial", "premium", "vip", "goi-moi"]
    assert body["plans"][0]["days"] == 14
    ban = accounts.get_user("ban")
    assert ban["plan"] == "trial"  # Pro was deleted → the trial, starting now
    assert timedelta(days=13) < ban["plan_expires"] - _now() <= timedelta(days=14)
    # New accounts start on the trial with its length.
    row = admin.post("/api/admin/accounts", json={"username": "moi", "password": "secret123"}).json()
    assert row["plan"] == "trial" and row["plan_expires"]
    # Leaving the trial out of an edit never deletes it.
    kept = admin.put("/api/admin/plans", json={"plans": [{"id": "premium", "name": "Premium", "features": []}]}).json()
    assert [p["id"] for p in kept["plans"]] == ["trial", "premium"]
    assert admin.put("/api/admin/plans", json={"plans": [{"name": "A"}, {"name": "a"}]}).status_code == 400
    assert admin.patch("/api/admin/accounts/akiragosho", json={"plan": "trial"}).status_code == 400


def test_an_ended_trial_cannot_log_in_until_extended(auth_app):
    admin = _client(auth_app, ADMIN)
    admin.post("/api/admin/accounts", json={"username": "thu", "password": "secret123"})
    friend = _client(auth_app, {"username": "thu", "password": "secret123"})
    me = friend.get("/api/account/me").json()
    assert me["plan"]["trial"] is True and me["plan"]["expires_at"]
    # The trial ends: the open session stops working and a new login is refused.
    accounts.set_plan("thu", "trial", _now() - timedelta(minutes=1))
    assert friend.get("/api/account/me").status_code == 401
    r = TestClient(auth_app).post("/api/account/login", json={"username": "thu", "password": "secret123"})
    assert r.status_code == 401 and "hết hạn" in r.json()["detail"]
    row = next(a for a in admin.get("/api/admin/accounts").json()["accounts"] if a["username"] == "thu")
    assert row["expired"] is True
    # Extend → the trial runs again from today; moving to a paid plan removes the end date.
    assert admin.post("/api/admin/accounts/thu/extend").json()["expired"] is False
    _client(auth_app, {"username": "thu", "password": "secret123"})
    assert admin.patch("/api/admin/accounts/thu", json={"plan": "premium"}).json()["plan_expires"] is None
    assert admin.post("/api/admin/accounts/thu/extend").status_code == 400  # not on the trial any more


def test_plans_saved_before_the_trial_keep_accounts_on_their_plan(auth_app):
    """The plans of an older build (no trial, default Premium): accounts "on the default" stay on Premium."""
    accounts.create_user("cu", "secret123")  # plan NULL
    accounts.set_setting(plans.SETTING_KEY, {"plans": [{"id": "vip", "name": "VIP", "features": []},
                                                       {"id": "premium", "name": "Premium", "features": plans.FEATURE_KEYS}],
                                             "default": "premium"})
    plans.forget()
    data = plans.load()
    assert [p["id"] for p in data["plans"]] == ["trial", "vip", "premium"] and data["default"] == "trial"
    assert accounts.get_user("cu")["plan"] == "premium" and accounts.get_user("cu")["plan_expires"] is None
    assert accounts.get_user("akiragosho")["plan"] is None  # the admin needs no plan


def test_only_the_admin_sees_the_plans(auth_app):
    accounts.create_user("ban", "secret123")
    friend = _client(auth_app, {"username": "ban", "password": "secret123"})
    assert friend.get("/api/admin/plans").status_code == 403
    assert friend.put("/api/admin/plans", json={"plans": [{"name": "Hack", "features": plans.FEATURE_KEYS}]}).status_code == 403
    # An account from before plans existed keeps every feature (it lands on Premium).
    assert set(friend.get("/api/account/me").json()["features"]) == set(plans.FEATURE_KEYS)


def test_my_account_profile_and_logging_out_elsewhere(auth_app):
    admin = _client(auth_app, ADMIN)
    admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "vip"})
    here = _client(auth_app, {"username": "ban", "password": "secret123"})
    there = _client(auth_app, {"username": "ban", "password": "secret123"})
    r = here.put("/api/account/profile", json={"display_name": "  Bạn   Nam ", "phone": "0901 234 567", "email": "nam@example.com", "contact": "zalo 0901"})
    assert r.status_code == 200 and r.json()["profile"] == {"display_name": "Bạn Nam", "phone": "0901 234 567",
                                                            "email": "nam@example.com", "contact": "zalo 0901"}
    assert here.put("/api/account/profile", json={"email": "khong-dung"}).status_code == 400
    assert here.get("/api/account/me").json()["profile"]["display_name"] == "Bạn Nam"
    assert here.get("/api/account/upgrades").json() == {"requests": []}
    assert here.post("/api/account/logout-others").json()["logged_out"] == 1
    assert there.get("/api/account/me").status_code == 401
    assert here.get("/api/account/me").status_code == 200


def test_auto_posting_stops_when_the_plan_loses_facebook(auth_app, monkeypatch):
    admin = _client(auth_app, ADMIN)
    admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "pro"})
    _client(auth_app, {"username": "ban", "password": "secret123"})  # active account = ban
    assert plans.active_allows("facebook") is False and plans.active_allows("dub") is True
    import asyncio

    from flowboard.services import autopilot, scheduler
    assert asyncio.run(scheduler.tick()) == 0
    assert asyncio.run(autopilot.tick()) == 0
