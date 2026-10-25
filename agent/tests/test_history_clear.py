"""🧹 Dọn lịch sử: finished rows go, queued / running never do."""
from datetime import datetime, timedelta, timezone

from flowboard.db import get_session
from flowboard.db.models import Request


def _seed():
    old = datetime.now(timezone.utc) - timedelta(days=40)
    rows = [
        Request(type="gen_image", status="done"),
        Request(type="gen_video", status="failed"),
        Request(type="gen_video", status="timeout", created_at=old),
        Request(type="gen_image", status="done", created_at=old),
        Request(type="gen_video", status="queued"),
        Request(type="gen_video", status="running", created_at=old),
    ]
    with get_session() as s:
        for r in rows:
            s.add(r)
        s.commit()


def _statuses():
    with get_session() as s:
        return sorted(r.status for r in s.exec(__import__("sqlmodel").select(Request)).all())


def test_dry_run_counts_without_deleting(client):
    _seed()
    r = client.post("/api/history/clear", json={"scope": "all", "dry_run": True}).json()
    assert r == {"count": 4, "deleted": 0, "dry_run": True}
    assert len(_statuses()) == 6


def test_errors_only_then_older_then_all(client):
    _seed()
    assert client.post("/api/history/clear", json={"scope": "errors"}).json()["deleted"] == 2
    assert _statuses() == ["done", "done", "queued", "running"]
    assert client.post("/api/history/clear", json={"scope": "older", "days": 30}).json()["deleted"] == 1
    assert client.post("/api/history/clear", json={"scope": "all"}).json()["deleted"] == 1
    assert _statuses() == ["queued", "running"]  # the worker's jobs stay
    assert client.post("/api/history/clear", json={"scope": "nope"}).status_code == 400
