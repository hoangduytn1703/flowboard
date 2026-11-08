"""Phase C: the app logs in through the DFlow website (cloud_api.py) — no database owner line on the machine.

A fake website (httpx.MockTransport) plays dflow-web's /api/app/*: password check, lock / end date, the account's own
database login (a SQLite file here), the account's settings, signed media links, upgrade requests."""
import base64
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from flowboard import accounts, cloud_api, config, licensing, plans
from flowboard.db import session as db_session
from flowboard.services import file_store

SITE = "https://site.test"
BUCKET = "https://bucket.test"


class FakeSite:
    def __init__(self, tmp):
        self.tmp = tmp
        self.accounts = {"ban": {"id": 7, "password": "secret123", "plan": "vip", "plan_expires": None, "disabled": 0,
                                 "license": None, "profile": None}}
        self.settings: dict[str, object] = {}
        self.shared: dict[str, object] = {"plans": None, "billing": None, "license_epoch": None}
        self.bucket: dict[str, bytes] = {}
        self.tokens: dict[str, str] = {}
        self.requests: list[dict] = []
        self.offline = False
        self.calls: list[str] = []

    def payload(self, name: str) -> dict:
        a = self.accounts[name]
        return {"account": {"id": a["id"], "username": name, "created_at": "2026-11-01T00:00:00", "role": "user",
                            "disabled": a["disabled"], "plan": a["plan"], "plan_expires": a["plan_expires"],
                            "profile": a["profile"], "license": a["license"]},
                "settings": {k: (json.dumps(v) if v is not None else None) for k, v in self.shared.items()},
                "db": {"url": "sqlite:///" + str(self.tmp / f"cloud-{name}.db").replace("\\", "/"), "schema": f"acct_{name}"},
                "site": SITE}

    def who(self, request: httpx.Request):
        tok = request.headers.get("authorization", "").removeprefix("Bearer ")
        name = next((n for n, t in self.tokens.items() if t == tok), None)
        if name is None:
            return None, httpx.Response(401, json={"detail": "Phiên đăng nhập của app đã hết — đăng nhập lại."})
        if self.accounts[name]["disabled"]:
            return None, httpx.Response(403, json={"detail": "Tài khoản này đã bị khoá."})
        return name, None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.offline:
            raise httpx.ConnectError("offline", request=request)
        url = str(request.url)
        self.calls.append(f"{request.method} {request.url.path}")
        if url.startswith(BUCKET + "/put/"):
            self.bucket[url[len(BUCKET) + 5:]] = request.read()
            return httpx.Response(200)
        if url.startswith(BUCKET + "/get/"):
            key = url[len(BUCKET) + 5:]
            return httpx.Response(200, content=self.bucket[key]) if key in self.bucket else httpx.Response(404)
        path = request.url.path
        body = json.loads(request.content or b"null") if request.method in ("POST", "PUT") else None
        if path == "/api/app/login":
            a = self.accounts.get(body["username"])
            if a is None or a["password"] != body["password"]:
                return httpx.Response(401, json={"detail": "Sai tên đăng nhập hoặc mật khẩu."})
            if a["disabled"]:
                return httpx.Response(403, json={"detail": "Tài khoản này đã bị khoá."})
            self.tokens[body["username"]] = f"tok-{body['username']}-{time.time_ns()}"
            return httpx.Response(200, json={"token": self.tokens[body["username"]], **self.payload(body["username"])})
        name, err = self.who(request)
        if err is not None:
            return err
        if path == "/api/app/me":
            return httpx.Response(200, json=self.payload(name))
        if path == "/api/app/settings":
            key = request.url.params.get("key") if request.method == "GET" else body["key"]
            if not (key == f"secrets:{name}" or key.startswith(f"fb_token:{name}:")):
                return httpx.Response(403, json={"detail": "Không được đọc mục này."})
            if request.method == "GET":
                return httpx.Response(200, json={"key": key, "value": self.settings.get(key)})
            self.settings[key] = body["value"]
            return httpx.Response(200, json={"ok": True})
        if path == "/api/app/media":
            mine = f"{name}/"
            if body["op"] in ("put", "get"):
                if any(not k.startswith(mine) for k in body["keys"]):
                    return httpx.Response(403, json={"detail": "Chỉ được dùng file của chính tài khoản."})
                return httpx.Response(200, json={"urls": {k: f"{BUCKET}/{body['op']}/{k}" for k in body["keys"]}})
            if body["op"] == "list":
                items = [{"key": k, "size": len(v)} for k, v in self.bucket.items() if k.startswith(body["prefix"])]
                return httpx.Response(200, json={"items": items, "next": None})
            if body["op"] == "delete":
                self.bucket.pop(body["key"], None)
                return httpx.Response(200, json={"ok": True})
        if path == "/api/app/upgrade":
            pend = next((r for r in reversed(self.requests) if r["username"] == name and r["status"] == "pending"), None)
            return httpx.Response(200, json={"pending": pend, "requests": [r for r in self.requests if r["username"] == name]})
        if path == "/api/app/upgrade/request":
            for r in self.requests:
                if r["username"] == name and r["status"] == "pending":
                    r["status"] = "cancelled"
            row = {"id": len(self.requests) + 1, "username": name, "plan_id": body["plan_id"], "plan_name": body["plan_id"].upper(),
                   "amount": 49000, "months": body["months"], "term": "1 tháng", "content": f"{name} - VIP", "status": "pending",
                   "created_at": "2026-11-08T10:00:00", "decided_at": None}
            self.requests.append(row)
            return httpx.Response(200, json={"request": row})
        if path == "/api/app/upgrade/cancel":
            for r in self.requests:
                if r["username"] == name and r["status"] == "pending":
                    r["status"] = "cancelled"
            return httpx.Response(200, json={"ok": True})
        if path == "/api/app/account/password":
            a = self.accounts[name]
            if body["current"] != a["password"]:
                return httpx.Response(400, json={"detail": "Mật khẩu hiện tại không đúng."})
            a["password"] = body["new"]
            self.tokens[name] = f"tok-{name}-{time.time_ns()}"
            return httpx.Response(200, json={"ok": True, "token": self.tokens[name]})
        return httpx.Response(404, json={"detail": "no such route"})


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWBOARD_AUTH", "on")
    monkeypatch.setenv("FLOWBOARD_CLOUD_API", SITE)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(accounts, "_ROOT_STORAGE", data)
    monkeypatch.setattr(accounts, "_ROOT_DB", data / "flowboard.db")
    monkeypatch.setattr(config, "STORAGE_DIR", data)
    monkeypatch.setattr(config, "DB_PATH", data / "flowboard.db")
    fake = FakeSite(tmp_path)
    mock = httpx.Client(transport=httpx.MockTransport(fake))
    monkeypatch.setattr(cloud_api, "_http", mock)
    monkeypatch.setattr(httpx, "put", lambda url, **kw: mock.put(url, **{k: v for k, v in kw.items() if k != "timeout"}))
    monkeypatch.setattr(httpx, "stream", lambda method, url, **kw: mock.stream(method, url))
    cloud_api.reset()
    accounts.reset_central()
    accounts.deactivate()
    file_store.reset()
    default_engine = db_session.current_engine()
    from flowboard.main import app
    accounts.startup()
    yield SimpleNamespace(fake=fake, app=app, client=TestClient(app), data=data)
    accounts.deactivate()
    accounts.reset_central()
    cloud_api.reset()
    file_store.reset()
    db_session.set_engine(default_engine)


def _login(site, password="secret123"):
    return site.client.post("/api/account/login", json={"username": "ban", "password": password})


def test_nothing_is_seeded_and_the_login_page_points_at_the_site(site):
    assert accounts.via_api() and accounts.list_users() == []  # no admin with a public password on this machine
    status = site.client.get("/api/app/connect").json()
    assert status["cloud"] is True and status["site"]["signup"] == f"{SITE}/dang-ky"


def test_login_goes_through_the_site_and_opens_the_accounts_own_database(site):
    assert _login(site, "nope").status_code == 401
    r = _login(site)
    assert r.status_code == 200, r.text
    me = site.client.get("/api/account/me").json()
    assert me["username"] == "ban" and me["site"]["admin"] == f"{SITE}/quan-tri"
    user = accounts.get_user("ban")
    assert user["id"] == 7 and user["backend"]["via"] == "api" and user["backend"]["schema"] == "acct_ban"
    assert cloud_api.token("ban") == site.fake.tokens["ban"]
    assert site.client.post("/api/boards", json={"name": "Clip qua web"}).status_code in (200, 201)
    assert (site.fake.tmp / "cloud-ban.db").is_file()  # the line the site handed out, not a local guess


def test_the_accounts_keys_live_on_the_site_not_on_this_machine(site):
    assert _login(site).status_code == 200
    accounts.set_setting("secrets:ban", {"geminiApiKeys": ["k1"]})
    assert site.fake.settings["secrets:ban"] == {"geminiApiKeys": ["k1"]}
    cloud_api.reset()  # another minute, another read
    assert accounts.get_setting("secrets:ban") == {"geminiApiKeys": ["k1"]}
    accounts.set_setting("fb_token:ban:3", "EAAG…")
    assert site.fake.settings["fb_token:ban:3"] == "EAAG…"
    with accounts.central_engine().connect() as c:  # nothing of it in the local store
        keys = {r.key for r in c.execute(accounts.settings_t.select()).all()}
    assert not any(k.startswith(("secrets:", "fb_token:")) for k in keys)


def test_media_goes_up_and_down_with_signed_links(site):
    assert _login(site).status_code == 200
    site.client.get("/api/account/me")
    accounts.activate(accounts.get_user("ban"))
    clip = config.STORAGE_DIR / "media" / "clip.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"video-bytes")
    assert file_store.enabled() and file_store.upload_now(clip)
    assert site.fake.bucket["ban/media/clip.mp4"] == b"video-bytes"
    assert file_store.list_keys() == {"ban/media/clip.mp4"}
    clip.unlink()
    assert file_store.ensure_local(str(clip)) == clip and clip.read_bytes() == b"video-bytes"
    assert not file_store.download("ban/media/missing.mp4")  # 404 is "not there", not an error
    assert file_store.status()["download_errors"] == 0


def test_a_lock_on_the_site_logs_the_machine_out_at_the_next_check(site):
    assert _login(site).status_code == 200
    assert site.client.get("/api/account/me").status_code == 200
    site.fake.accounts["ban"]["disabled"] = 1
    assert cloud_api.refresh("ban") is False
    accounts._session_cache.clear()
    assert site.client.get("/api/account/me").status_code == 401
    r = _login(site)
    assert r.status_code == 401 and "khoá" in r.json()["detail"]
    site.fake.offline = True  # and no way in offline either
    assert _login(site).status_code == 401


def test_offline_login_uses_the_copy_for_a_while(site):
    assert _login(site).status_code == 200
    site.client.post("/api/account/logout")
    site.fake.offline = True
    assert _login(site).status_code == 200  # the site was seen minutes ago
    site.client.post("/api/account/logout")
    assert _login(site, "wrong").status_code == 401
    accounts.set_setting("api_seen:ban", time.time() - cloud_api.OFFLINE_OK_S - 60)
    r = _login(site)
    assert r.status_code == 401 and "site.test" in r.json()["detail"]


def test_upgrade_requests_are_filed_on_the_site(site):
    site.fake.shared["plans"] = {"plans": [
        {"id": "trial", "name": "Dùng thử", "features": [], "days": 7},
        {"id": "vip", "name": "VIP", "features": ["posts"], "terms": [{"months": 1, "price": 49000, "list_price": 0}]}],
        "default": "trial"}
    site.fake.shared["billing"] = {"bank_bin": "970436", "account_no": "0123456789", "account_name": "NGUYEN VAN A",
                                   "template": "{username} - {plan}", "note": ""}
    site.fake.accounts["ban"]["plan"] = "trial"
    assert _login(site).status_code == 200
    offer = site.client.get("/api/account/upgrade").json()
    assert [p["id"] for p in offer["plans"]] == ["vip"] and offer["ready"] and offer["pending"] is None
    r = site.client.post("/api/account/upgrade/request", json={"plan_id": "vip", "months": 1})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert site.fake.requests[0]["plan_id"] == "vip"
    assert site.client.get("/api/account/upgrade").json()["pending"]["id"] == 1
    assert [x["id"] for x in site.client.get("/api/account/upgrades").json()["requests"]] == [1]
    assert site.client.post("/api/account/upgrade/cancel").status_code == 200


def test_password_change_goes_to_the_site_and_keeps_this_machine_in(site):
    assert _login(site).status_code == 200
    old = cloud_api.token("ban")
    r = site.client.post("/api/account/password", json={"current": "secret123", "new": "moi-hon-123"})
    assert r.status_code == 200, r.text
    assert site.fake.accounts["ban"]["password"] == "moi-hon-123" and cloud_api.token("ban") != old
    assert site.client.get("/api/account/me").status_code == 200
    site.client.post("/api/account/logout")
    site.fake.offline = True
    assert _login(site, "moi-hon-123").status_code == 200  # the local copy learnt the new one too


def test_bucket_and_admin_pages_are_the_sites_business(site):
    assert _login(site).status_code == 200
    assert site.client.put("/api/cloud/s3", json={"endpoint": "x", "bucket": "b", "keyId": "k", "secret": "s"}).status_code == 409
    assert site.client.post("/api/cloud/migrate").status_code == 409
    assert site.client.get("/api/cloud/status").json()["via_api"] is True


def test_the_signed_licence_from_the_site_decides(site, monkeypatch):
    """Strict like the installed app: the licence the website signed (bound to the account's id) is what counts."""
    web = Ed25519PrivateKey.generate()
    monkeypatch.setattr(licensing, "WEB_PUBLIC_KEY_B64", base64.b64encode(web.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode())
    monkeypatch.setenv("FLOWBOARD_LICENSE_STRICT", "1")
    licensing.reset()

    def seal(payload):
        body = licensing.canonical(payload)
        return licensing._b64(body) + "." + licensing._b64(web.sign(licensing._LICENCE_TAG + body))

    from flowboard import __version__

    site.fake.shared["license_epoch"] = {"at": "2026-11-08T00:00:00"}
    site.fake.shared["min_app"] = {"v": __version__}
    site.fake.shared["min_app:sig"] = {"sig": licensing._b64(web.sign(licensing._doc_bytes("min_app", {"v": __version__})))}
    r = _login(site)
    assert r.status_code == 401 and "cấp quyền" in r.json()["detail"]  # no licence → no entry
    site.fake.accounts["ban"]["license"] = seal({"v": 1, "u": "ban", "id": 7, "r": "user", "p": "vip", "n": "VIP", "f": ["posts"],
                                                 "e": None, "x": 0, "lh": "", "t": 1})
    assert _login(site).status_code == 200
    me = site.client.get("/api/account/me").json()
    assert me["plan"]["id"] == "vip" and me["features"] == ["posts"]
    site.fake.accounts["ban"]["license"] = seal({"v": 1, "u": "ban", "id": 8, "r": "admin", "p": "", "n": "x", "f": list(plans.FEATURE_KEYS),
                                                 "e": None, "x": 0, "lh": "", "t": 2})  # someone else's id: worthless
    assert cloud_api.refresh("ban") is True
    accounts._session_cache.clear()
    assert site.client.get("/api/account/me").status_code == 401
