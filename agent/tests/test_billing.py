"""Plan upgrades by bank transfer: the admin sets the bank, each plan lists its terms + prices, an account gets a
VietQR with the amount and transfer text, files a request after paying, and the admin approves it by hand (auth ON)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from flowboard import accounts, billing, config, plans
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
    assert c.post("/api/account/login", json=creds).status_code == 200
    return c


def _tlv(payload: str) -> dict:
    out, i = {}, 0
    while i < len(payload):
        tag, n = payload[i:i + 2], int(payload[i + 2:i + 4])
        out[tag] = payload[i + 4:i + 4 + n]
        i += 4 + n
    return out


def test_vietqr_payload_follows_the_napas_layout():
    assert billing.crc16("123456789") == "29B1"  # CRC-16/CCITT-FALSE check value
    qr = billing.vietqr_payload("970436", "0123456789", 199000, "ban - Premium")
    top = _tlv(qr)
    assert top["00"] == "01" and top["01"] == "12" and top["53"] == "704" and top["58"] == "VN"
    assert top["54"] == "199000" and _tlv(top["62"])["08"] == "ban - Premium"
    merchant = _tlv(top["38"])
    assert merchant["00"] == "A000000727" and merchant["02"] == "QRIBFTTA"
    assert _tlv(merchant["01"]) == {"00": "970436", "01": "0123456789"}
    assert top["63"] == billing.crc16(qr[:-4])


def test_transfer_text_drops_accents_and_stays_short():
    assert billing.transfer_text("{username} - {plan}", "ban.a", "VIP Vàng") == "ban.a - VIP Vang"
    assert billing.transfer_text("Nâng cấp {plan} cho {username}", "đức", "Pro") == "Nang cap Pro cho duc"
    assert len(billing.transfer_text("{username}" * 20, "abcdef", "x")) <= billing.TEXT_MAX


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _set_terms(admin, terms: dict) -> dict:
    """The admin edits "📦 Gói & tính năng": the terms of some plans."""
    data = admin.get("/api/admin/plans").json()
    body = [dict(pl, terms=terms.get(pl["id"], pl.get("terms") or [])) for pl in data["plans"]]
    r = admin.put("/api/admin/plans", json={"plans": body})
    assert r.status_code == 200, r.text
    return r.json()


def test_terms_are_cleaned():
    terms = plans.normalize_terms({"vip": [
        {"months": 12, "price": "990.000", "list_price": "1.200.000"},
        {"months": 1, "price": 99000, "list_price": 50000},   # list price below the price → dropped
        {"months": 1, "price": 1},                             # same length twice → the first wins
        {"months": 5, "price": 1000},                          # not a length we sell
        {"months": 0, "price": 2_000_000},
        {"months": 3, "price": 0},                             # no price → no term
    ], "pro": []})
    assert terms == {"vip": [{"months": 1, "price": 99000, "list_price": 0},
                             {"months": 12, "price": 990000, "list_price": 1200000},
                             {"months": 0, "price": 2000000, "list_price": 0}]}
    assert "terms" not in billing.normalize({"terms": {"vip": [{"months": 1, "price": 1}]}})  # prices live in the plans
    assert billing.transfer_text("{username} - {plan} {term}", "ban", "VIP", "6 tháng") == "ban - VIP 6 thang"


def test_prices_kept_with_the_bank_move_into_the_plans(auth_app):
    """Builds before 8/11 kept one price per plan (then terms) with the bank settings: they become the plans' terms."""
    accounts.set_setting(plans.SETTING_KEY, {"plans": [{"id": "trial", "name": "Dùng thử", "features": [], "days": 7},
                                                       {"id": "vip", "name": "VIP", "features": []},
                                                       {"id": "premium", "name": "Premium", "features": []}], "default": "trial"})
    accounts.set_setting(billing.SETTING_KEY, {"bank_bin": "970436", "account_no": "1", "prices": {"premium": 299000}})
    plans.forget()
    by_id = {pl["id"]: pl for pl in plans.load()["plans"]}
    assert by_id["premium"]["terms"] == [{"months": 0, "price": 299000, "list_price": 0}] and by_id["vip"]["terms"] == []
    assert "terms" not in by_id["trial"]
    # saved once → stays (a later edit to the bank settings no longer touches prices)
    accounts.set_setting(billing.SETTING_KEY, {"bank_bin": "970436", "account_no": "1", "terms": {"vip": [{"months": 1, "price": 9}]}})
    plans.forget()
    assert {pl["id"]: pl["terms"] for pl in plans.load()["plans"][1:]}["vip"] == []


def test_an_account_pays_for_a_term_and_the_admin_approves(auth_app):
    admin = _client(auth_app, ADMIN)
    admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "vip", "months": 0})
    friend = _client(auth_app, {"username": "ban", "password": "secret123"})
    offer = friend.get("/api/account/upgrade").json()
    assert offer["current"]["id"] == "vip" and offer["ready"] is False and offer["pending"] is None
    assert friend.post("/api/account/upgrade/quote", json={"plan_id": "premium", "months": 6}).status_code == 400  # not set up
    saved = _set_terms(admin, {"premium": [{"months": 6, "price": "499.000", "list_price": "600.000"}, {"months": 0, "price": 1500000}]})
    assert next(pl for pl in saved["plans"] if pl["id"] == "premium")["terms"][0] == {"months": 6, "price": 499000, "list_price": 600000}
    assert saved["term_months"] == [1, 3, 6, 12, 24, 0]
    r = admin.put("/api/admin/billing", json={
        "bank_bin": "970436", "account_no": "0123 456 789", "account_name": "Nguyễn Văn A", "note": "Chuyển xong bấm Đã chuyển"})
    body = r.json()
    s = body["settings"]
    assert s["account_no"] == "0123456789" and s["account_name"] == "NGUYEN VAN A" and s["template"] == "{username} - {plan}"
    assert body["sample"]["qr"].startswith("000201") and body["sample"]["amount"] == 499000
    offer = friend.get("/api/account/upgrade").json()
    premium = next(p for p in offer["plans"] if p["id"] == "premium")
    assert offer["ready"] and [t["months"] for t in premium["terms"]] == [6, 0]
    q = friend.post("/api/account/upgrade/quote", json={"plan_id": "premium", "months": 6}).json()
    assert q["amount"] == 499000 and q["list_price"] == 600000 and q["term"] == "6 tháng" and q["renew"] is False
    assert q["content"] == "ban - Premium" and q["bank_name"] == "Vietcombank" and _tlv(q["qr"])["54"] == "499000"
    ends = datetime.fromisoformat(q["ends_at"])
    assert timedelta(days=180) <= ends - _now() <= timedelta(days=185)
    assert friend.post("/api/account/upgrade/quote", json={"plan_id": "premium", "months": 1}).status_code == 400  # not sold
    assert friend.post("/api/account/upgrade/quote", json={"plan_id": "pro", "months": 0}).status_code == 400      # no price
    assert friend.post("/api/account/upgrade/quote", json={"plan_id": "vip", "months": 0}).status_code == 400      # vip forever
    # "Tôi đã chuyển khoản" → a pending request; filing again replaces it.
    friend.post("/api/account/upgrade/request", json={"plan_id": "premium", "months": 0})
    pending = friend.post("/api/account/upgrade/request", json={"plan_id": "premium", "months": 6}).json()
    assert pending["status"] == "pending" and pending["amount"] == 499000 and pending["term"] == "6 tháng"
    assert [r["status"] for r in admin.get("/api/admin/billing").json()["requests"]] == ["pending", "cancelled"]
    # Approve → Premium for 6 months.
    out = admin.post(f"/api/admin/billing/requests/{pending['id']}/approve").json()
    assert out["requests"][0]["status"] == "approved"
    user = accounts.get_user("ban")
    assert user["plan"] == "premium" and timedelta(days=180) <= user["plan_expires"] - _now() <= timedelta(days=185)
    me = friend.get("/api/account/me").json()
    assert me["plan"]["id"] == "premium" and me["plan"]["expires_at"]
    assert admin.post(f"/api/admin/billing/requests/{pending['id']}/approve").status_code == 400  # done already
    # Renewing the same plan keeps the time left: 6 more months on top.
    renew = friend.post("/api/account/upgrade/request", json={"plan_id": "premium", "months": 6}).json()
    admin.post(f"/api/admin/billing/requests/{renew['id']}/approve")
    assert timedelta(days=360) <= accounts.get_user("ban")["plan_expires"] - _now() <= timedelta(days=370)


def test_a_paid_plan_that_ran_out_locks_the_account(auth_app):
    admin = _client(auth_app, ADMIN)
    row = admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "vip", "months": 1}).json()
    assert row["plan"] == "vip" and row["plan_expires"]
    friend = _client(auth_app, {"username": "ban", "password": "secret123"})
    accounts.set_plan("ban", "vip", _now() - timedelta(minutes=1))
    assert friend.get("/api/account/me").status_code == 401
    r = TestClient(auth_app).post("/api/account/login", json={"username": "ban", "password": "secret123"})
    assert r.status_code == 401 and "Gói đang dùng" in r.json()["detail"]
    # The admin renews 3 months (counted from today, the old end has passed) → back in.
    assert admin.post("/api/admin/accounts/ban/extend").status_code == 400  # a paid plan needs a term
    out = admin.post("/api/admin/accounts/ban/extend", json={"months": 3}).json()
    assert out["expired"] is False
    assert timedelta(days=88) <= datetime.fromisoformat(out["plan_expires"]) - _now() <= timedelta(days=93)
    _client(auth_app, {"username": "ban", "password": "secret123"})
    # Stack 1 month onto the 3 months left; another plan always counts from today; then forever.
    stacked = admin.patch("/api/admin/accounts/ban", json={"plan": "vip", "months": 1, "stack": True}).json()
    assert timedelta(days=117) <= datetime.fromisoformat(stacked["plan_expires"]) - _now() <= timedelta(days=124)
    year = admin.patch("/api/admin/accounts/ban", json={"plan": "pro", "months": 12, "stack": True}).json()
    assert year["plan"] == "pro" and timedelta(days=364) <= datetime.fromisoformat(year["plan_expires"]) - _now() <= timedelta(days=367)
    assert admin.patch("/api/admin/accounts/ban", json={"plan": "pro", "months": 0}).json()["plan_expires"] is None
    assert admin.patch("/api/admin/accounts/ban", json={"plan": "pro", "months": 5}).status_code == 400
    trial = admin.patch("/api/admin/accounts/ban", json={"plan": "trial", "days": 3}).json()
    assert timedelta(days=2) < datetime.fromisoformat(trial["plan_expires"]) - _now() <= timedelta(days=3)
    # any end date the admin picks: the end of that day, Vietnam time
    picked = admin.patch("/api/admin/accounts/ban", json={"plan": "vip", "expires_on": "2030-01-31"}).json()
    assert picked["plan"] == "vip" and picked["plan_expires"].startswith("2030-01-31T16:59:59")
    assert admin.patch("/api/admin/accounts/ban", json={"expires_on": "31/01/2030"}).status_code == 400


def test_reject_cancel_and_who_may_see_what(auth_app):
    admin = _client(auth_app, ADMIN)
    admin.put("/api/admin/billing", json={"bank_bin": "970422", "account_no": "123"})
    _set_terms(admin, {"premium": [{"months": 1, "price": 100000}]})
    admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "vip"})
    friend = _client(auth_app, {"username": "ban", "password": "secret123"})
    assert friend.get("/api/admin/billing").status_code == 403
    assert admin.get("/api/account/upgrade").status_code == 400  # the admin has everything
    req = friend.post("/api/account/upgrade/request", json={"plan_id": "premium", "months": 1}).json()
    admin.post(f"/api/admin/billing/requests/{req['id']}/reject")
    assert accounts.get_user("ban")["plan"] == "vip"
    friend.post("/api/account/upgrade/request", json={"plan_id": "premium", "months": 1})
    assert friend.post("/api/account/upgrade/cancel").json() == {"ok": True}
    assert friend.get("/api/account/upgrade").json()["pending"] is None
