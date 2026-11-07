"""The desktop app (DFlow.exe → dflow-agent.exe, 7/11): the agent serves the built UI itself, keeps its settings in
its own .env (Settings → 🖥 Máy này instead of editing the file), applies the Flow plan at once, and restarts
through the app. The repo's real .env is never touched here: ENV_FILE points at a temp file."""
from pathlib import Path

import pytest

from flowboard import config
from flowboard.routes import app as app_route
from flowboard.services import app_env, flow_sdk


@pytest.fixture()
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", path)
    monkeypatch.setattr(flow_sdk, "DEFAULT_PAYGATE_TIER", flow_sdk.DEFAULT_PAYGATE_TIER)
    monkeypatch.setattr(config, "DEFAULT_PAYGATE_TIER", config.DEFAULT_PAYGATE_TIER)
    monkeypatch.delenv("FLOWBOARD_PAYGATE_TIER", raising=False)
    return path


def test_env_values_are_written_without_losing_hand_written_lines(env_file):
    env_file.write_bytes("\ufeff# my notes\nFLOWBOARD_FLOW_PROJECT_ID=abc\nOTHER=1\nFLOWBOARD_STORAGE=C:\\old\n".encode("utf-8"))
    app_env.write_values({"FLOWBOARD_STORAGE": None, "FLOWBOARD_PAYGATE_TIER": "PAYGATE_TIER_ONE"})
    text = env_file.read_text(encoding="utf-8")
    assert not text.startswith("\ufeff") and "# my notes" in text and "OTHER=1" in text and "FLOWBOARD_STORAGE" not in text
    assert app_env.read_values() == {"FLOWBOARD_FLOW_PROJECT_ID": "abc", "OTHER": "1", "FLOWBOARD_PAYGATE_TIER": "PAYGATE_TIER_ONE"}
    assert app_env.db_host("postgresql://user:pa55@ep-x.neon.tech/db?sslmode=require") == "ep-x.neon.tech"


def test_settings_apply_the_plan_at_once_and_flag_restart_keys(client, env_file, tmp_path):
    r = client.put("/api/app/settings", json={"paygate_tier": "PAYGATE_TIER_ONE"})
    assert r.status_code == 200 and r.json()["plan"] == "Pro"
    assert flow_sdk.resolve_paygate_tier(None) == "PAYGATE_TIER_ONE"  # no restart needed
    r = client.put("/api/app/settings", json={"central_db_url": "FLOWBOARD_CENTRAL_DB_URL=postgresql://u:secret@ep-a.neon.tech/db"})
    body = r.json()
    assert body["cloud_db"] == {"set": True, "host": "ep-a.neon.tech", "active": False}
    assert "FLOWBOARD_CENTRAL_DB_URL" in body["restart_pending"] and "secret" not in r.text
    assert client.put("/api/app/settings", json={"central_db_url": "mysql://nope"}).status_code == 400
    data = tmp_path / "data here"
    r = client.put("/api/app/settings", json={"storage_dir": str(data)})
    assert r.status_code == 200 and data.is_dir() and "FLOWBOARD_STORAGE" in r.json()["restart_pending"]
    assert client.put("/api/app/settings", json={"storage_dir": "relative\\path"}).status_code == 400
    values = app_env.read_values()
    assert values["FLOWBOARD_PAYGATE_TIER"] == "PAYGATE_TIER_ONE" and values["FLOWBOARD_STORAGE"] == str(data)


def test_restart_is_only_for_the_app(client, monkeypatch):
    monkeypatch.setattr(config, "APP_MODE", False)
    assert client.post("/api/app/restart", json={}).status_code == 400
    monkeypatch.setattr(config, "APP_MODE", True)
    exits = []
    monkeypatch.setattr(app_route.threading, "Timer", lambda delay, fn: type("T", (), {"start": lambda self: exits.append(delay)})())
    monkeypatch.setattr("flowboard.routes.running.running", lambda: {"items": [{"title": "Lồng tiếng"}]})
    r = client.post("/api/app/restart", json={})
    assert r.status_code == 409 and "Lồng tiếng" in r.json()["detail"] and not exits
    assert client.post("/api/app/restart", json={"force": True}).json() == {"ok": True, "restarting": True} and exits


def test_a_fresh_install_takes_the_cloud_line_from_the_login_page(client, env_file, monkeypatch):
    """Open endpoint: the friend's accounts live on the cloud store, so the line must be pasted before logging in."""
    monkeypatch.setenv("FLOWBOARD_CENTRAL_DB_URL", "")
    assert client.get("/api/app/connect").json()["cloud"] is False
    assert client.post("/api/app/connect", json={"central_db_url": "mysql://nope"}).status_code == 400
    assert client.post("/api/app/connect", json={"central_db_url": "  "}).status_code == 400
    probed = []
    monkeypatch.setattr(app_route, "_probe_cloud", lambda url: probed.append(url))
    monkeypatch.setattr(config, "APP_MODE", True)
    exits = []
    monkeypatch.setattr(app_route.threading, "Timer", lambda delay, fn: type("T", (), {"start": lambda self: exits.append(delay)})())
    r = client.post("/api/app/connect", json={"central_db_url": "FLOWBOARD_CENTRAL_DB_URL=postgresql://u:secret@ep-a.neon.tech/db"})
    assert r.json() == {"ok": True, "restarting": True} and exits and "secret" not in r.text
    assert probed == ["postgresql://u:secret@ep-a.neon.tech/db"]
    assert app_env.read_values()["FLOWBOARD_CENTRAL_DB_URL"] == "postgresql://u:secret@ep-a.neon.tech/db"
    assert client.get("/api/app/connect").json() == {"app": True, "cloud": False, "restart_pending": True}
    # Once this machine is on the cloud, the open door is shut (changes go through Settings after login).
    monkeypatch.setenv("FLOWBOARD_CENTRAL_DB_URL", "postgresql://u:secret@ep-a.neon.tech/db")
    assert client.post("/api/app/connect", json={"central_db_url": "postgresql://x@evil/db"}).status_code == 409


def test_a_wrong_cloud_line_is_refused_before_saving(client, env_file, monkeypatch):
    monkeypatch.setenv("FLOWBOARD_CENTRAL_DB_URL", "")
    r = client.post("/api/app/connect", json={"central_db_url": "postgresql://u:pw@127.0.0.1:1/db"})
    assert r.status_code == 400 and "Không kết nối được" in r.json()["detail"] and "pw@" not in r.text
    assert "FLOWBOARD_CENTRAL_DB_URL" not in app_env.read_values()


def test_the_built_ui_is_served_with_a_spa_fallback(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from flowboard import web_ui

    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html>DFlow</html>", encoding="utf-8")
    (web / "assets" / "app-1.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    monkeypatch.setenv("FLOWBOARD_WEB_DIR", str(web))
    app = FastAPI()

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    assert web_ui.mount(app)
    c = TestClient(app)
    assert c.get("/api/health").json() == {"ok": True}  # real routes win
    assert c.get("/").text == "<html>DFlow</html>" and c.get("/").headers["cache-control"] == "no-cache"
    assert c.get("/clips/12/export").text == "<html>DFlow</html>"  # React router page after F5
    r = c.get("/assets/app-1.js")
    assert r.text == "console.log(1)" and "immutable" in r.headers["cache-control"]
    assert c.get("/api/unknown").status_code == 404 and c.get("/media/x").status_code == 404
    assert c.get("/%2e%2e/secret.txt").text == "<html>DFlow</html>"  # never a file outside the UI folder
    monkeypatch.setenv("FLOWBOARD_WEB_DIR", str(tmp_path / "missing"))
    assert not web_ui.mount(FastAPI())


def test_status_names_the_extension_folder(client, env_file):
    st = client.get("/api/app/status").json()
    assert st["extension_dir"] and Path(st["extension_dir"], "manifest.json").is_file()
    assert st["env_file"] == str(env_file)
