"""The first-run guide (services/setup_status): what is missing, and what the agent settles on its own."""
from __future__ import annotations

import time

import pytest

from flowboard import config
from flowboard.services import app_env, flow_project, setup_status
from flowboard.services.flow_client import ExtConn, _tab_project, flow_client

PROJECT = "1dfd992a-4149-4f97-9d68-a1ede77d3fc3"


@pytest.fixture(autouse=True)
def no_project_in_env(monkeypatch):
    """A fresh install: no Flow project in .env either."""
    monkeypatch.setattr(config, "FLOW_PROJECT_ID", "")


@pytest.fixture()
def chrome(monkeypatch, tmp_path):
    """An extension of our own: connected, with a Flow tab whose account panel answers what the test says."""
    page = {"email": "seller@gmail.com", "credits": "1.250", "tier": "ULTRA",
            "tabUrl": f"https://flow.google.com/fx/vi/tools/flow/project/{PROJECT}"}
    conn = ExtConn(id=7, ws=object(), connected_at=time.time(), version="0.6.1")
    monkeypatch.setattr(flow_client, "_conns", {7: conn})
    monkeypatch.setattr(flow_client, "_active", 7)
    monkeypatch.setattr(flow_client, "account_listeners", [])

    async def send(method, params=None, timeout=0, conn=None):
        if method == "read_account":
            return {"error": page["error"]} if page.get("error") else {"data": dict(page)}
        return {"data": {"opened": True}}

    monkeypatch.setattr(flow_client, "_send", send)
    monkeypatch.setattr(app_env, "env_file", lambda: tmp_path / ".env")
    monkeypatch.setattr(setup_status, "_ai_cache", {"ok": None, "label": ""})
    tier = app_env.current_tier()
    yield page
    app_env.apply_tier(tier)
    flow_project.set_override(None)


def _step(status, step_id):
    return next(s for s in status["steps"] if s["id"] == step_id)


def test_a_fresh_install_says_what_is_missing_in_order(client, monkeypatch):
    monkeypatch.setattr(flow_client, "_conns", {})
    monkeypatch.setattr(flow_client, "_active", None)
    st = client.get("/api/setup/status").json()
    assert [s["id"] for s in st["steps"]] == ["extension", "flow", "project", "ai", "product", "clip"]
    assert not st["ready"] and not st["can_generate"]
    assert not _step(st, "extension")["ok"] and "extension" in _step(st, "extension")["detail"].lower()
    assert not _step(st, "project")["ok"] and not _step(st, "product")["ok"]
    # looking again without an extension changes nothing and does not fail
    assert client.post("/api/setup/check").json()["changed"] == []


def test_the_open_project_and_the_plan_are_picked_up_from_the_flow_tab(client, chrome):
    app_env.apply_tier("PAYGATE_TIER_ONE")
    st = client.post("/api/setup/check").json()
    assert st["flow"]["email"] == "seller@gmail.com" and st["flow"]["credits"] == 1250
    assert st["flow"]["project_id"] == PROJECT and st["flow"]["plan"] == "Ultra"
    assert sorted(st["changed"]) == ["dự án Flow đang mở", "gói Flow Ultra"]
    assert app_env.current_tier() == "PAYGATE_TIER_TWO" and "PAYGATE_TIER_TWO" in app_env.env_file().read_text(encoding="utf-8")
    assert st["can_generate"] and all(_step(st, i)["ok"] for i in ("extension", "flow", "project"))
    # a second look changes nothing
    assert client.post("/api/setup/check").json()["changed"] == []


def test_a_pinned_project_is_kept_unless_the_seller_asks_for_the_open_one(client, chrome):
    other = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    flow_project.set_override(other)
    st = client.post("/api/setup/check").json()
    assert st["flow"]["project_id"] == other and st["flow"]["tab_project"] == PROJECT
    st = client.post("/api/setup/check", json={"use_tab_project": True}).json()
    assert st["flow"]["project_id"] == PROJECT and "dự án Flow đang mở" in st["changed"]


def test_the_flow_home_page_is_not_a_project_and_a_closed_tab_is_named(client, chrome):
    chrome["tabUrl"] = "https://flow.google.com/"
    st = client.post("/api/setup/check").json()
    assert st["flow"]["project_id"] is None and not st["can_generate"]
    assert "Dự án mới" in _step(st, "project")["detail"]
    chrome["error"] = "NO_FLOW_TAB"
    flow_client.active_conn.email = None
    st = client.post("/api/setup/check").json()
    assert not _step(st, "flow")["ok"] and "flow.google.com" in _step(st, "flow")["detail"]


def test_an_old_extension_is_not_ready_and_the_plan_chip_is_read_loosely(client, chrome):
    flow_client.active_conn.version = "0.4.1"
    st = client.get("/api/setup/status").json()
    assert not _step(st, "extension")["ok"] and "bản cũ" in _step(st, "extension")["detail"]
    assert setup_status.plan_of("Google AI Pro") == "PAYGATE_TIER_ONE" and setup_status.plan_of("ultra") == "PAYGATE_TIER_TWO"
    assert setup_status.plan_of("") is None and setup_status.plan_of("FREE") is None
    assert _tab_project("https://flow.google.com/fx/tools/flow/project/new") is None
    assert _tab_project(None) is None


def test_gemini_keys_count_as_the_ai_and_products_as_the_next_step(client, chrome, monkeypatch):
    from flowboard.services.llm import secrets

    monkeypatch.setattr(secrets, "get_gemini_keys", lambda: [])
    monkeypatch.setattr(secrets, "read_feature_config", lambda: {})
    st = client.post("/api/setup/check").json()
    assert not _step(st, "ai")["ok"] and not st["ready"] and st["can_generate"]
    monkeypatch.setattr(secrets, "get_gemini_keys", lambda: ["k1", "k2"])
    st = client.post("/api/setup/check").json()
    assert _step(st, "ai")["ok"] and "2 key" in _step(st, "ai")["detail"] and st["ready"]
    client.post("/api/products", json={"name": "Áo thun", "description": "a white t-shirt", "category": "fashion"})
    assert _step(client.get("/api/setup/status").json(), "product")["ok"]
