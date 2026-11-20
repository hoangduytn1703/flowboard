"""The Flow tab signed in to one Google account while the pinned project is another's: Flow takes every video and drops
it (pictures still come back). 18/11: four days of dropped videos on clip #155 — the tab was akiragosho2000, the pinned
project hoangduytn1703's. DFlow now says so before sending, and offers the fix."""
from __future__ import annotations

import asyncio
import time

import pytest
from sqlmodel import select

from flowboard import config
from flowboard.db import get_session
from flowboard.db.models import AppSetting
from flowboard.services import account_pool as ap
from flowboard.services import app_env, flow_project, setup_status
from flowboard.services.flow_client import ExtConn, flow_client

OWNERS = "11111111-1111-4111-8111-111111111111"  # the project of owner@gmail.com, pinned
THEIRS = "22222222-2222-4222-8222-222222222222"  # the project the Flow tab has open (seller's own)


def _forget_projects() -> None:
    with get_session() as s:
        for row in s.exec(select(AppSetting).where(AppSetting.key.startswith(ap.PROJECT_FOR))).all():
            s.delete(row)
        s.commit()


def _remember(email: str, pid: str) -> None:
    with get_session() as s:
        s.add(AppSetting(key=f"{ap.PROJECT_FOR}{email}", value=pid))
        s.commit()


@pytest.fixture()
def tab(monkeypatch, tmp_path):
    """Pinned: owner@gmail.com's project. The Flow tab: seller@gmail.com, inside the seller's own project."""
    monkeypatch.setattr(config, "FLOW_PROJECT_ID", "")
    page = {"email": "seller@gmail.com", "credits": "900", "tier": "PRO",
            "tabUrl": f"https://flow.google.com/fx/vi/tools/flow/project/{THEIRS}"}
    conn = ExtConn(id=7, ws=object(), connected_at=time.time(), version="0.6.1")
    conn.email, conn.tab_project = page["email"], THEIRS
    monkeypatch.setattr(flow_client, "_conns", {7: conn})
    monkeypatch.setattr(flow_client, "_active", 7)
    monkeypatch.setattr(flow_client, "account_listeners", [])

    async def send(method, params=None, timeout=0, conn=None):
        if method == "read_account":
            return {"data": dict(page)}
        return {"data": {}}

    monkeypatch.setattr(flow_client, "_send", send)
    monkeypatch.setattr(app_env, "env_file", lambda: tmp_path / ".env")
    monkeypatch.setattr(setup_status, "_ai_cache", {"ok": True, "label": "test"})
    tier = app_env.current_tier()
    ap._save({"auto": True, "accounts": []})
    _forget_projects()
    flow_project.set_override(OWNERS)
    _remember("owner@gmail.com", OWNERS)
    yield conn
    app_env.apply_tier(tier)
    flow_project.set_override(None)
    ap._save({"auto": True, "accounts": []})
    _forget_projects()


def test_the_wrong_account_is_named_and_nothing_is_sent(tab, client):
    st = client.get("/api/setup/status").json()
    wrong = st["flow"]["mismatch"]
    assert wrong["email"] == "seller@gmail.com" and wrong["owners"] == ["owner@gmail.com"]
    assert wrong["suggest_project"] == THEIRS
    assert not st["can_generate"]
    step = next(s for s in st["steps"] if s["id"] == "project")
    assert not step["ok"] and "owner@gmail.com" in step["detail"] and "seller@gmail.com" in step["detail"]
    # the worker refuses the video at once instead of letting Flow drop it minutes later
    err, pid = asyncio.run(ap.account_pool.ensure_credits(12))
    assert err.startswith(ap.WRONG_ACCOUNT) and "seller@gmail.com" in err and pid is None


def test_the_tab_on_the_owners_account_fits(tab, client):
    tab.email = "Owner@gmail.com"
    st = client.get("/api/setup/status").json()
    assert st["flow"]["mismatch"] is None and st["can_generate"]
    assert asyncio.run(ap.account_pool.ensure_credits(12)) == (None, None)


def test_a_project_nobody_is_known_to_own_is_not_questioned(tab, client):
    _forget_projects()
    assert client.get("/api/setup/status").json()["flow"]["mismatch"] is None


def test_use_the_accounts_own_project(tab, client):
    st = client.post("/api/setup/check", json={"use_account_project": True}).json()
    assert st["flow"]["project_id"] == THEIRS and st["flow"]["mismatch"] is None and st["can_generate"]
    assert any("seller@gmail.com" in c for c in st["changed"])
    # remembered for that account: switching back to it later re-pins it
    with get_session() as s:
        assert s.get(AppSetting, f"{ap.PROJECT_FOR}seller@gmail.com").value == THEIRS


def test_keep_the_project_when_it_is_shared(tab, client):
    st = client.post("/api/setup/check", json={"keep_project": True}).json()
    assert st["flow"]["project_id"] == OWNERS and st["flow"]["mismatch"] is None and st["can_generate"]


def test_a_new_account_on_the_tab_is_not_recorded_as_owning_anothers_project(tab):
    ap.account_pool.on_account_read({"email": "seller@gmail.com", "credits": 900, "tier": "PRO"})
    assert ap.account_pool.get("seller@gmail.com")["project_id"] == THEIRS
    # …so the warning stays: the pool did not make the wrong project look like the seller's
    assert ap.account_pool.mismatch()["owners"] == ["owner@gmail.com"]
