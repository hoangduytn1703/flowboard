"""Several extensions (Chrome profiles) at once: the registry, the active
one, reading the account panel, and the routes that switch accounts."""
import asyncio
import json

import pytest

from flowboard.services import flow_client as fc
from flowboard.services.flow_client import FlowClient


class FakeWs:
    def __init__(self, name="ws") -> None:
        self.name = name
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def _ready(client, ws, version="0.3.0"):
    # extension_ready schedules read_account; run it inside a loop so the
    # task can be created, then drop the pending future it made.
    async def go():
        await client.handle_message({"type": "extension_ready", "flowKeyPresent": False, "version": version}, ws)
        await asyncio.sleep(0)
    asyncio.run(go())
    client._pending.clear()


def test_parse_credits_and_email():
    assert fc._parse_credits("62 tín dụng Google Flow") == 62
    assert fc._parse_credits("1.250 credits") == 1250
    assert fc._parse_credits("1,250 AI credits") == 1250
    assert fc._parse_credits(80) == 80
    assert fc._parse_credits("no digits") is None
    assert fc._clean_email(" a@b.vn ") == "a@b.vn"
    assert fc._clean_email("nope") is None


def test_first_connection_is_active_and_losing_it_promotes_the_next():
    c = FlowClient()
    a, b = FakeWs("a"), FakeWs("b")
    ia = c.set_extension(a)
    ib = c.set_extension(b)
    assert ia != ib and c.active_conn.ws is a and c.connected
    assert [x["id"] for x in c.accounts()] == [ia, ib]
    _ready(c, b, "0.1.0")
    assert c.conn_for(b).version == "0.1.0"
    assert c.extension_version is None  # the active one (a) sent nothing yet
    c.clear_extension(a)
    assert c.active_conn.ws is b and c.extension_version == "0.1.0"
    c.clear_extension(b)
    assert not c.connected and c.accounts() == []


def test_activate_switches_the_socket_commands_go_to():
    c = FlowClient()
    a, b = FakeWs("a"), FakeWs("b")
    ia, ib = c.set_extension(a), c.set_extension(b)
    assert c.activate(ib) and c.active_conn.id == ib
    assert not c.activate(999)

    async def go():
        task = asyncio.create_task(c._send("get_status", {}, timeout=1))
        await asyncio.sleep(0)
        req_id = next(iter(c._pending))
        c.resolve_callback({"id": req_id, "status": 200, "data": "{}"})
        return await task

    asyncio.run(go())
    assert b.sent and b.sent[-1]["method"] == "get_status" and not a.sent


def test_read_account_parses_the_panel_and_fills_the_active_identity():
    c = FlowClient()
    a = FakeWs("a")
    ia = c.set_extension(a)
    c.conn_for(a).version = "0.3.0"

    async def go():
        task = asyncio.create_task(c.read_account(ia))
        await asyncio.sleep(0)
        req_id = next(iter(c._pending))
        assert a.sent[-1]["method"] == "read_account"
        c.resolve_callback({"id": req_id, "status": 200, "data": json.dumps(
            {"email": "x@gmail.com", "credits": "1.250 tín dụng Google Flow", "tier": "pro"})})
        return await task

    out = asyncio.run(go())
    assert out == {"email": "x@gmail.com", "credits": 1250, "tier": "PRO"}
    assert c.credits == 1250 and c.user_info == {"email": "x@gmail.com"}
    acc = c.accounts()[0]
    assert acc["email"] == "x@gmail.com" and acc["active"] and acc["account_error"] is None


def test_read_account_refuses_an_old_extension_without_sending():
    c = FlowClient()
    a = FakeWs("a")
    ia = c.set_extension(a)
    c.conn_for(a).version = "0.2.0"
    assert asyncio.run(c.read_account(ia)) == {"error": "extension_outdated", "version": "0.2.0"}
    assert not a.sent and c.accounts()[0]["account_error"] == "extension_outdated"


def test_account_routes_list_activate_and_repin(client, monkeypatch):
    from flowboard.routes import auth as auth_route
    from flowboard.services.flow_client import flow_client as live

    live.clear_extension()  # other tests may have left sockets behind
    a, b = FakeWs("a"), FakeWs("b")
    ia, ib = live.set_extension(a), live.set_extension(b)
    try:
        live.conn_for(a).email = "one@gmail.com"
        live.conn_for(b).email = "two@gmail.com"
        r = client.get("/api/auth/accounts")
        assert r.status_code == 200
        body = r.json()
        assert [x["email"] for x in body["accounts"]] == ["one@gmail.com", "two@gmail.com"]
        assert body["active_id"] == ia

        # Pinning a project while "one" is active remembers it for that account.
        pinned = {}
        monkeypatch.setattr(auth_route, "effective_project_id", lambda: pinned.get("id", "00000000-0000-4000-8000-000000000000"))
        monkeypatch.setattr(auth_route, "set_override", lambda v: pinned.__setitem__("id", v) or 0)
        auth_route.remember_project_for_active("11111111-1111-4111-8111-111111111111")
        assert auth_route._remembered_project("one@gmail.com") == "11111111-1111-4111-8111-111111111111"

        r = client.post(f"/api/auth/accounts/{ib}/activate")
        assert r.status_code == 200 and r.json()["active_id"] == ib and r.json()["repinned_project_id"] is None
        r = client.post(f"/api/auth/accounts/{ia}/activate")
        assert r.json()["active_id"] == ia
        assert r.json()["repinned_project_id"] == "11111111-1111-4111-8111-111111111111"
        assert client.post("/api/auth/accounts/999/activate").status_code == 404
    finally:
        live.clear_extension()
