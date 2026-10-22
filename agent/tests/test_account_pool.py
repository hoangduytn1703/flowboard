"""The Flow account pool: credit gate, switching to the next account and
waiting for the Flow tab to follow, bookkeeping after jobs."""
import asyncio
import json

import pytest

from flowboard.services import account_pool as ap
from flowboard.services.flow_client import flow_client


class FakeWs:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


@pytest.fixture
def pool(monkeypatch):
    p = ap.AccountPool()
    flow_client.clear_extension()
    pinned = {"id": "00000000-0000-4000-8000-000000000000"}
    monkeypatch.setattr(ap, "effective_project_id", lambda: pinned["id"])
    monkeypatch.setattr(ap, "set_override", lambda v: pinned.__setitem__("id", v) or 0)
    monkeypatch.setattr(ap, "SWITCH_POLL_S", 0.01)
    monkeypatch.setattr(ap, "SWITCH_WAIT_S", 2)
    # Start from an empty pool.
    ap._save({"auto": True, "accounts": []})
    yield p, pinned
    ap._save({"auto": True, "accounts": []})
    flow_client.clear_extension()


def _signed_in(email, credits=None):
    ws = FakeWs()
    flow_client.set_extension(ws)
    flow_client.active_conn.email = email
    flow_client.active_conn.credits = credits
    flow_client.active_conn.version = "0.3.0"
    return ws


def test_job_cost_from_params():
    assert ap.job_cost({"duration_s": 8}) == 12
    assert ap.job_cost({"duration_s": 4, "variant_count": 2}) == 12
    assert ap.job_cost({"video_quality": "quality", "start_media_id": "x"}) == 100
    assert ap.job_cost({"start_media_id": "x"}) == 20
    assert ap.job_cost({"prompt": "an image"}) == 0


def test_upsert_validates_and_normalises(pool):
    p, _ = pool
    acc = p.upsert(" A@Gmail.com ", project_id="https://flow.google.com/project/11111111-1111-4111-8111-111111111111", credits=80)
    assert acc["email"] == "a@gmail.com" and acc["project_id"] == "11111111-1111-4111-8111-111111111111" and acc["credits"] == 80
    with pytest.raises(ValueError):
        p.upsert("nope")
    with pytest.raises(ValueError):
        p.upsert("b@gmail.com", project_id="not-a-uuid")
    assert p.remove("a@gmail.com") and not p.remove("a@gmail.com")


def test_account_read_registers_the_signed_in_account_with_the_pinned_project(pool):
    p, pinned = pool
    p.on_account_read({"email": "a@gmail.com", "credits": 62, "tier": "PRO"})
    acc = p.get("a@gmail.com")
    assert acc["project_id"] == pinned["id"] and acc["credits"] == 62 and acc["tier"] == "PRO"


def test_ensure_credits_passes_when_enough_or_unknown(pool):
    p, _ = pool
    _signed_in("a@gmail.com")
    p.upsert("a@gmail.com", project_id="11111111-1111-4111-8111-111111111111", credits=80)
    assert asyncio.run(p.ensure_credits(25)) == (None, None)
    p.upsert("a@gmail.com", credits=None)
    assert asyncio.run(p.ensure_credits(25)) == (None, None)
    assert asyncio.run(p.ensure_credits(0)) == (None, None)
    p.set_auto(False)
    p.upsert("a@gmail.com", credits=5)
    assert asyncio.run(p.ensure_credits(25)) == (None, None)


def test_ensure_credits_switches_and_waits_for_the_flow_tab(pool, monkeypatch):
    p, pinned = pool
    ws = _signed_in("a@gmail.com")
    p.upsert("a@gmail.com", project_id="11111111-1111-4111-8111-111111111111", credits=10)
    p.upsert("b@gmail.com", project_id="22222222-2222-4222-8222-222222222222")
    reads = iter([
        {"email": "a@gmail.com", "credits": 10, "tier": "PRO"},   # still on A
        {"email": "b@gmail.com", "credits": 100, "tier": "PRO"},  # user switched
    ])

    async def fake_read(conn_id=None):
        info = next(reads)
        for fn in flow_client.account_listeners:
            fn(info)
        p.on_account_read(info)
        return info

    async def fake_send(method, params, timeout=None, conn=None):
        ws.sent.append({"method": method, "params": params})
        return {"status": 200, "data": "{}"}

    monkeypatch.setattr(flow_client, "read_account", fake_read)
    monkeypatch.setattr(flow_client, "_send", fake_send)

    err, pid = asyncio.run(p.ensure_credits(25))
    assert err is None and pid == "22222222-2222-4222-8222-222222222222"
    assert pinned["id"] == pid                      # project re-pinned
    assert p.pending is None and p.last_switch["to_email"] == "b@gmail.com"
    assert p.get("a@gmail.com")["exhausted_at"]      # A marked dry
    assert any(m["method"] == "open_flow_tab" and m["params"]["email"] == "b@gmail.com" for m in ws.sent)


def test_ensure_credits_times_out_with_a_clear_message(pool, monkeypatch):
    p, _ = pool
    ws = _signed_in("a@gmail.com")
    p.upsert("a@gmail.com", project_id="11111111-1111-4111-8111-111111111111", credits=0)
    p.upsert("b@gmail.com", project_id="22222222-2222-4222-8222-222222222222")

    async def fake_read(conn_id=None):
        return {"email": "a@gmail.com", "credits": 0, "tier": "PRO"}

    async def fake_send(method, params, timeout=None, conn=None):
        return {"status": 200, "data": "{}"}

    monkeypatch.setattr(flow_client, "read_account", fake_read)
    monkeypatch.setattr(flow_client, "_send", fake_send)
    err, pid = asyncio.run(p.ensure_credits(25))
    assert err and "b@gmail.com" in err and pid == "22222222-2222-4222-8222-222222222222"
    assert p.pending and p.pending["to_email"] == "b@gmail.com"


def test_no_other_account_is_a_plain_error(pool, monkeypatch):
    p, _ = pool
    _signed_in("a@gmail.com")
    p.upsert("a@gmail.com", project_id="11111111-1111-4111-8111-111111111111", credits=3)
    err, pid = asyncio.run(p.ensure_credits(25))
    assert err and "không còn tài khoản" in err and pid is None


def test_note_result_decrements_and_flags_credit_errors(pool):
    p, _ = pool
    _signed_in("a@gmail.com")
    p.upsert("a@gmail.com", project_id="11111111-1111-4111-8111-111111111111", credits=50)
    p.note_result({"duration_s": 8}, None)
    assert p.get("a@gmail.com")["credits"] == 38
    p.note_result({"prompt": "img"}, None)
    assert p.get("a@gmail.com")["credits"] == 38
    p.note_result({"duration_s": 8}, "RESOURCE_EXHAUSTED: insufficient credits")
    acc = p.get("a@gmail.com")
    assert acc["credits"] == 0 and acc["exhausted_at"]


def test_pool_routes(client, pool, monkeypatch):
    from flowboard.routes import auth as auth_route  # noqa: F401
    from flowboard.services import account_pool as mod
    monkeypatch.setattr(mod, "account_pool", pool[0])
    r = client.put("/api/auth/pool/accounts", json={"email": "c@gmail.com", "project_id": "33333333-3333-4333-8333-333333333333", "label": "Acc C"})
    assert r.status_code == 200 and r.json()["accounts"][0]["label"] == "Acc C"
    assert client.put("/api/auth/pool/accounts", json={"email": "bad"}).status_code == 400
    assert client.put("/api/auth/pool/auto", json={"auto": False}).json()["auto"] is False
    assert client.get("/api/auth/pool").json()["accounts"][0]["email"] == "c@gmail.com"
    assert client.post("/api/auth/pool/switch", json={"email": "zz@gmail.com"}).status_code == 404
    assert client.delete("/api/auth/pool/accounts/c@gmail.com").status_code == 200
    assert client.delete("/api/auth/pool/accounts/c@gmail.com").status_code == 404


def test_only_real_credit_errors_mark_an_account_dry():
    """FLOW_DROPPED_JOB ('… refunded the credits'), timeouts and paygate
    errors once flagged a full account as dry and pinned another account's
    project (2026-10-22)."""
    from flowboard.services.flow_sdk import FLOW_DROPPED_JOB

    assert ap.is_credit_error("RESOURCE_EXHAUSTED: insufficient credits")
    assert ap.is_credit_error("Not enough credits to generate")
    assert not ap.is_credit_error(FLOW_DROPPED_JOB)
    assert not ap.is_credit_error("timeout_waiting_video")
    assert not ap.is_credit_error("paygate_tier_unknown")
    assert not ap.is_credit_error(None)


def test_dropped_video_does_not_exhaust_the_account(pool):
    from flowboard.services.flow_sdk import FLOW_DROPPED_JOB

    p, _ = pool
    _signed_in("a@gmail.com")
    p.upsert("a@gmail.com", project_id="11111111-1111-4111-8111-111111111111", credits=500)
    p.note_result({"duration_s": 8}, FLOW_DROPPED_JOB)
    acc = p.get("a@gmail.com")
    assert acc["credits"] == 500 and not acc.get("exhausted_at")
