"""Signed licences (licensing.py): someone who can edit the account store by hand (the Neon line) cannot give themselves a
plan, admin rights, more time, unlock themselves, take over another account, or swap the bank account — and a machine
without the admin's key can read but not change anyone's rights. Strict mode (like the installed app) with a test key."""
import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from fastapi.testclient import TestClient
from sqlalchemy import select

from flowboard import accounts, billing, config, licensing, plans
from flowboard.db import session as db_session

ADMIN = {"username": "akiragosho", "password": "Password@123"}


def _make_key(path) -> str:
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    path.write_text("# test key\n" + base64.b64encode(raw).decode() + "\n", encoding="utf-8")
    return base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


@pytest.fixture
def signed(tmp_path, monkeypatch):
    keyfile = tmp_path / "keys" / "dflow-license.key"
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", _make_key(keyfile))
    monkeypatch.setenv("FLOWBOARD_LICENSE_KEY", str(keyfile))
    monkeypatch.setenv("FLOWBOARD_LICENSE_STRICT", "1")
    monkeypatch.setenv("FLOWBOARD_AUTH", "on")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(accounts, "_ROOT_STORAGE", data)
    monkeypatch.setattr(accounts, "_ROOT_DB", data / "flowboard.db")
    monkeypatch.setattr(config, "STORAGE_DIR", data)
    monkeypatch.setattr(config, "DB_PATH", data / "flowboard.db")
    accounts.reset_central()
    accounts.deactivate()
    default_engine = db_session.current_engine()
    from flowboard.main import app
    accounts.startup()  # the admin's machine signs this new store (trust on first use)
    yield SimpleNamespace(app=app, keyfile=keyfile, tmp=tmp_path)
    accounts.deactivate()
    accounts.reset_central()
    db_session.set_engine(default_engine)


def _login(app, user, pw):
    c = TestClient(app)
    return c, c.post("/api/account/login", json={"username": user, "password": pw})


def _client(app, creds) -> TestClient:
    c, r = _login(app, creds["username"], creds["password"])
    assert r.status_code == 200, r.text
    return c


def _edit_row(username, **values):
    """What anyone with the Neon line can do: change the row by hand."""
    with accounts.central_engine().begin() as c:
        c.execute(accounts.users.update().where(accounts.users.c.username == username).values(**values))
    accounts._session_cache.clear()  # as seen by another machine / after the 5-minute cache


def _row(username):
    with accounts.central_engine().connect() as c:
        return c.execute(select(accounts.users).where(accounts.users.c.username == username)).first()


def _past() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)


def _no_key(monkeypatch, tmp):
    monkeypatch.setenv("FLOWBOARD_LICENSE_KEY", str(tmp / "elsewhere" / "no.key"))
    licensing.reset()


def test_the_admin_machine_signs_a_new_store_once(signed):
    assert licensing.store_licensed() and licensing.can_sign()
    assert accounts.get_user("akiragosho")["license"] == "ok"
    for key in (plans.SETTING_KEY, billing.SETTING_KEY, "min_app"):
        assert licensing.doc_state(key) == "ok", key
    assert (signed.keyfile.parent / "license-state.json").exists()  # remembered on the admin's machine
    admin = _client(signed.app, ADMIN)
    body = admin.get("/api/admin/accounts").json()
    assert body["licensing"]["can_sign"] is True and body["licensing"]["active"] is True
    assert body["accounts"][0]["license"] == "ok" and body["accounts"][0]["tampered"] is False


def test_hand_edits_of_a_row_count_for_nothing(signed):
    admin = _client(signed.app, ADMIN)
    assert admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "vip", "months": 1}).status_code == 201
    assert _row("ban").license
    friend = _client(signed.app, {"username": "ban", "password": "secret123"})
    assert friend.get("/api/account/me").json()["plan"]["id"] == "vip"
    _edit_row("ban", role="admin", plan="premium", plan_expires=None, disabled=0)
    me = friend.get("/api/account/me").json()
    assert me["plan"]["id"] == "vip" and me["is_admin"] is False and "dub" not in me["features"] and me["plan"]["expires_at"]
    assert friend.get("/api/admin/accounts").status_code == 403
    assert friend.get("/api/dub/jobs").status_code == 403
    row = next(a for a in admin.get("/api/admin/accounts").json()["accounts"] if a["username"] == "ban")
    assert row["plan"] == "vip" and row["tampered"] is True and row["role"] == "user"
    # the plans in the store edited by hand (VIP gets dubbing): the licence still lists VIP's real features
    raw = accounts.get_setting("plans")
    raw["plans"] = [dict(p, features=plans.FEATURE_KEYS) if p["id"] == "vip" else p for p in raw["plans"]]
    accounts.set_setting("plans", raw)
    plans.forget()
    assert "dub" not in friend.get("/api/account/me").json()["features"]
    offer = friend.get("/api/account/upgrade").json()
    assert offer["ready"] is False and "chữ ký" in offer["note"]
    # and the admin's machine refuses to sign with hand-edited plans until the admin saves them again
    r = admin.patch("/api/admin/accounts/ban", json={"plan": "pro", "months": 1})
    assert r.status_code == 403 and "Bảng gói" in r.json()["detail"]
    data = admin.get("/api/admin/plans").json()
    assert data["signed"] == "invalid"
    fixed = [dict(p, features=[k for k in p["features"] if k != "dub"]) if p["id"] == "vip" else p for p in data["plans"]]
    assert admin.put("/api/admin/plans", json={"plans": fixed}).json()["signed"] == "ok"
    assert admin.patch("/api/admin/accounts/ban", json={"plan": "pro", "months": 1}).status_code == 200


def test_copied_forged_and_hand_made_rows_cannot_get_in(signed):
    admin = _client(signed.app, ADMIN)
    admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "vip", "months": 1})
    good = _row("ban").license
    # someone else's licence copied onto your row
    _edit_row("ban", license=_row("akiragosho").license)
    c, r = _login(signed.app, "ban", "secret123")
    assert r.status_code == 401 and "chữ ký" in r.json()["detail"]
    # your licence with the plan changed (the signature no longer matches)
    body, sig = good.split(".")
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["p"], payload["e"] = "premium", None
    forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=") + "." + sig
    _edit_row("ban", license=forged)
    assert _login(signed.app, "ban", "secret123")[1].status_code == 401
    _edit_row("ban", license=good)
    assert _login(signed.app, "ban", "secret123")[1].status_code == 200
    # an account added by hand (an old-style hash anyone can make, admin role, Premium) — and the admin's machine restarting
    with accounts.central_engine().begin() as conn:
        conn.execute(accounts.users.insert().values(
            username="hacker", password_hash="pbkdf2_sha256$1$00$" + __import__("hashlib").pbkdf2_hmac("sha256", b"x123456", b"\0", 1).hex(),
            created_at=datetime.now(), backend="{}", role="admin", disabled=0, plan="premium"))
    assert _login(signed.app, "hacker", "x123456")[1].status_code == 401
    accounts.startup()
    assert _row("hacker").license is None and _login(signed.app, "hacker", "x123456")[1].status_code == 401
    # your own hash copied onto the admin's row: hashes are bound to the account
    _edit_row("akiragosho", password_hash=_row("ban").password_hash)
    assert _login(signed.app, "akiragosho", "secret123")[1].status_code == 401
    # an old-style hash of a known password written onto the admin's row
    import hashlib
    legacy = "pbkdf2_sha256$1000$aa$" + hashlib.pbkdf2_hmac("sha256", b"hacked1", bytes.fromhex("aa"), 1000).hex()
    _edit_row("akiragosho", password_hash=legacy)
    c, r = _login(signed.app, "akiragosho", "hacked1")
    assert r.status_code == 401 and "đặt lại" in r.json()["detail"]


def test_a_session_moved_to_another_account_stops_working(signed):
    admin = _client(signed.app, ADMIN)
    admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "vip", "months": 1})
    friend = _client(signed.app, {"username": "ban", "password": "secret123"})
    admin_id = _row("akiragosho").id
    with accounts.central_engine().begin() as conn:
        conn.execute(accounts.sessions.update().where(accounts.sessions.c.user_id == _row("ban").id).values(user_id=admin_id))
    accounts._session_cache.clear()
    assert friend.get("/api/account/me").status_code == 401


def test_locks_and_end_dates_live_in_the_licence(signed):
    admin = _client(signed.app, ADMIN)
    admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "vip", "months": 1})
    assert admin.patch("/api/admin/accounts/ban", json={"disabled": True}).json()["disabled"] is True
    _edit_row("ban", disabled=0)
    assert _login(signed.app, "ban", "secret123")[1].status_code == 401
    admin.patch("/api/admin/accounts/ban", json={"disabled": False})
    assert _login(signed.app, "ban", "secret123")[1].status_code == 200
    admin.patch("/api/admin/accounts/ban", json={"expires_on": "2020-01-01"})
    _edit_row("ban", plan_expires=None)  # "forever" written by hand
    c, r = _login(signed.app, "ban", "secret123")
    assert r.status_code == 401 and "hết hạn" in r.json()["detail"]


def test_a_machine_without_the_key_reads_but_cannot_change_rights(signed, monkeypatch):
    admin = _client(signed.app, ADMIN)
    admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "vip", "months": 1})
    _no_key(monkeypatch, signed.tmp)
    admin = _client(signed.app, ADMIN)  # licences check with the public key alone
    body = admin.get("/api/admin/accounts").json()
    assert body["licensing"]["can_sign"] is False and {a["username"] for a in body["accounts"]} == {"akiragosho", "ban"}
    for method, path, payload in (
        ("post", "/api/admin/accounts", {"username": "moi", "password": "secret123"}),
        ("patch", "/api/admin/accounts/ban", {"plan": "premium", "months": 0}),
        ("patch", "/api/admin/accounts/ban", {"disabled": True}),
        ("post", "/api/admin/accounts/ban/extend", {"months": 1}),
        ("put", "/api/admin/plans", {"plans": admin.get("/api/admin/plans").json()["plans"]}),
        ("put", "/api/admin/billing", {"bank_bin": "970436", "account_no": "999"}),
    ):
        r = getattr(admin, method)(path, json=payload)
        assert r.status_code == 403 and "khoá ký" in r.json()["detail"], (method, path, r.text)
    # what does not touch anyone's rights still works
    assert admin.patch("/api/admin/accounts/ban", json={"note": "bạn Nam"}).status_code == 200
    assert admin.post("/api/admin/accounts/ban/password", json={"new": "newpass123"}).status_code == 200
    assert _login(signed.app, "ban", "newpass123")[1].status_code == 200


def test_bank_details_and_approvals_cannot_be_rigged(signed):
    admin = _client(signed.app, ADMIN)
    data = admin.get("/api/admin/plans").json()
    body = [dict(p, terms=[{"months": 1, "price": 49000}, {"months": 0, "price": 980000}]) if p["id"] == "vip" else p for p in data["plans"]]
    admin.put("/api/admin/plans", json={"plans": body})
    admin.put("/api/admin/billing", json={"bank_bin": "970436", "account_no": "0123456789", "account_name": "Nguyen Van A"})
    admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "trial"})
    friend = _client(signed.app, {"username": "ban", "password": "secret123"})
    assert friend.post("/api/account/upgrade/quote", json={"plan_id": "vip", "months": 1}).status_code == 200
    # the money would go to someone else's account: not shown
    raw = accounts.get_setting("billing")
    accounts.set_setting("billing", dict(raw, account_no="99999999"))
    assert friend.get("/api/account/upgrade").json()["ready"] is False
    r = friend.post("/api/account/upgrade/quote", json={"plan_id": "vip", "months": 1})
    assert r.status_code == 400 and "đừng chuyển tiền" in r.json()["detail"]
    accounts.set_setting("billing", raw)
    # a request for 1 month (49k) turned into "forever" by hand: the admin's approval refuses the amount
    req = friend.post("/api/account/upgrade/request", json={"plan_id": "vip", "months": 1}).json()
    with billing._engine().begin() as conn:
        conn.execute(billing.upgrades.update().where(billing.upgrades.c.id == req["id"]).values(months=0))
    r = admin.post(f"/api/admin/billing/requests/{req['id']}/approve")
    assert r.status_code == 400 and "không khớp giá" in r.json()["detail"]
    assert accounts.get_user("ban")["plan"] == "trial"


def test_the_store_is_never_re_signed_from_its_rows(signed):
    admin = _client(signed.app, ADMIN)
    admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "vip", "months": 1})
    good = _row("ban").license
    # marker removed + the row and licence changed by hand: the admin's machine restores the marker and signs nothing
    accounts.set_setting(licensing.EPOCH_KEY, None)
    _edit_row("ban", plan="premium", plan_expires=None, license=None)
    licensing.reset()
    assert licensing.ensure_epoch() is None
    assert licensing.store_licensed() and _row("ban").license is None
    assert _login(signed.app, "ban", "secret123")[1].status_code == 401
    # every licence wiped too: still nothing re-signed (remembered on the admin's machine), the admin re-assigns by hand
    _edit_row("akiragosho", license=None)
    accounts.set_setting(licensing.EPOCH_KEY, None)
    licensing.reset()
    assert licensing.ensure_epoch() is None and _row("akiragosho").license is None
    _edit_row("ban", license=good)  # (a backup put back)
    assert _login(signed.app, "ban", "secret123")[1].status_code == 200


def test_app_builds_older_than_the_signed_minimum_are_refused(signed):
    admin = _client(signed.app, ADMIN)
    accounts.set_setting("min_app", {"v": "99.0.0"})
    licensing.sign_doc("min_app", {"v": "99.0.0"})
    accounts._session_cache.clear()
    c, r = _login(signed.app, "akiragosho", "Password@123")
    assert r.status_code == 401 and "đã cũ" in r.json()["detail"]
    assert admin.get("/api/account/me").status_code == 401
    accounts.set_setting("min_app", {"v": "0.0.1"})  # lowered by hand: the signature no longer matches
    c, r = _login(signed.app, "akiragosho", "Password@123")
    assert r.status_code == 401 and "không khớp chữ ký" in r.json()["detail"]


def _seal_with(key: Ed25519PrivateKey, payload: dict) -> str:
    body = licensing.canonical(payload)
    return licensing._b64(body) + "." + licensing._b64(key.sign(licensing._LICENCE_TAG + body))


def test_the_websites_key_counts_like_the_admins(signed, monkeypatch):
    """dflow-web signs with a key of its own: what it signs is valid in the app (licences, documents); a third key is not."""
    web = Ed25519PrivateKey.generate()
    monkeypatch.setattr(licensing, "WEB_PUBLIC_KEY_B64",
                        base64.b64encode(web.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode())
    licensing.reset()
    admin = _client(signed.app, ADMIN)
    assert admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "trial"}).status_code == 201
    payload = {"v": 1, "u": "ban", "id": _row("ban").id, "r": "user", "p": "premium", "n": "Premium",
               "f": list(plans.FEATURE_KEYS), "e": None, "x": 0, "lh": "", "t": 1}
    _edit_row("ban", license=_seal_with(web, payload), plan="premium", plan_expires=None)
    user = accounts.get_user("ban")
    assert user["license"] == "ok" and user["plan"] == "premium" and user["plan_expires"] is None and not user["tampered"]
    assert _login(signed.app, "ban", "secret123")[1].status_code == 200
    # the admin's machine keeps working on top of the website's licence
    r = admin.patch("/api/admin/accounts/ban", json={"plan": "vip", "months": 1})
    assert r.status_code == 200, r.text
    assert accounts.get_user("ban")["plan"] == "vip" and accounts.get_user("ban")["license"] == "ok"
    # a key nobody trusts: no licence
    _edit_row("ban", license=_seal_with(Ed25519PrivateKey.generate(), payload))
    assert accounts.get_user("ban")["license"] == "invalid"
    assert _login(signed.app, "ban", "secret123")[1].status_code == 401
    # documents too: the website saves the plans and signs them
    doc = accounts.get_setting(plans.SETTING_KEY)
    doc["plans"][1]["name"] = "VIP Web"
    accounts.set_setting(plans.SETTING_KEY, doc)
    accounts.set_setting(f"{plans.SETTING_KEY}:sig", {"sig": licensing._b64(web.sign(licensing._doc_bytes(plans.SETTING_KEY, doc))), "at": "x"})
    assert licensing.doc_state(plans.SETTING_KEY) == "ok"


def test_new_code_that_tidies_the_plans_keeps_the_signatures(signed, monkeypatch):
    """Signatures cover what is stored, not what today's code makes of it: a new field / default in plans.normalize or
    billing.normalize must neither hide the QR from customers nor block the admin."""
    admin = _client(signed.app, ADMIN)
    real_plans, real_bill = plans.normalize, billing.normalize
    monkeypatch.setattr(plans, "normalize", lambda raw: {**real_plans(raw), "note": "mới"})
    monkeypatch.setattr(billing, "normalize", lambda raw: {**real_bill(raw), "qr_style": "compact"})
    plans.forget()
    assert licensing.doc_state(plans.SETTING_KEY) == "ok" and licensing.doc_state(billing.SETTING_KEY) == "ok"
    assert billing.trusted()
    r = admin.post("/api/admin/accounts", json={"username": "ban", "password": "secret123", "plan": "vip", "months": 1})
    assert r.status_code == 201 and _row("ban").license


def test_old_hashes_get_the_pepper_at_the_first_login(tmp_path, monkeypatch):
    """A store with an account made before the pepper: signed once (its old hash pinned), then re-hashed at login."""
    keyfile = tmp_path / "keys" / "dflow-license.key"
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", _make_key(keyfile))
    monkeypatch.setenv("FLOWBOARD_LICENSE_KEY", str(keyfile))
    monkeypatch.setenv("FLOWBOARD_LICENSE_STRICT", "1")
    monkeypatch.setenv("FLOWBOARD_AUTH", "on")
    monkeypatch.setattr(accounts, "_ROOT_STORAGE", tmp_path)
    monkeypatch.setattr(accounts, "_ROOT_DB", tmp_path / "flowboard.db")
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "flowboard.db")
    accounts.reset_central()
    accounts.deactivate()
    default_engine = db_session.current_engine()
    try:
        import hashlib
        old = "pbkdf2_sha256$1000$bb$" + hashlib.pbkdf2_hmac("sha256", b"oldpass1", bytes.fromhex("bb"), 1000).hex()
        with accounts.central_engine().begin() as conn:
            conn.execute(accounts.users.insert().values(username="cu", password_hash=old, created_at=datetime.now(),
                                                        backend="{}", role="user", disabled=0, plan="vip"))
        from flowboard.main import app
        accounts.startup()
        assert _row("cu").license
        assert _login(app, "cu", "oldpass1")[1].status_code == 200
        assert _row("cu").password_hash.startswith("dflow2$")
        assert _login(app, "cu", "oldpass1")[1].status_code == 200
    finally:
        accounts.deactivate()
        accounts.reset_central()
        db_session.set_engine(default_engine)
