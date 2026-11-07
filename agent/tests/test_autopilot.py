"""🤖 Tự động đăng (services/autopilot): fixed slots → the post written ahead with the plan's AI (the other one when
it fails) → an auto slot on the calendar; one run per slot; missed / paused / retried slots; the AI override."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from flowboard.db import get_session
from flowboard.db.models import AutoPlan, AutoRun, Post, Product, Schedule
from flowboard.services import autopilot, post_writer, scheduler
from flowboard.services.llm import registry

TZ = autopilot.TZ


def _channel(client) -> int:
    return client.post("/api/channels", json={"name": "Chúng ta hay tò mò", "platforms": ["facebook"],
                                              "description": "Kiến thức vũ trụ"}).json()["id"]


def _slot_in(minutes: int) -> tuple[int, str]:
    """(weekday, "HH:MM") of a slot ``minutes`` from now, Vietnam time."""
    at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).astimezone(TZ)
    return at.weekday(), f"{at:%H:%M}"


def _fake_post(title="Sao Thổ có thể nổi trên nước?"):
    return {"title": title, "body": f"{title}\nSao Thổ nhẹ hơn nước.", "hashtags": ["#vutru"], "first_comment": "",
            "image_prompts": ["Saturn floating"]}


@pytest.fixture
def connected(monkeypatch):
    monkeypatch.setattr(scheduler, "can_auto", lambda cid: bool(cid))


def _run_tick():
    async def go():
        n = await autopilot.tick()
        tasks = list(autopilot._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return n
    return asyncio.run(go())


def _plan(client, cid, minutes=60, **over):
    day, hhmm = _slot_in(minutes)
    body = {"channel_id": cid, "days": [day], "times": [hhmm], "lead_minutes": 120,
            "brief": {"kind": "tips", "images": 0}, **over}
    r = client.post("/api/autopilot/plans", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_slots_follow_vietnam_time_and_weekdays():
    start = datetime(2026, 11, 9, 0, 0, tzinfo=TZ).astimezone(timezone.utc)  # Monday 00:00 VN
    slots = autopilot.slots_between([0, 2], ["20:00", "07:30"], start, start + timedelta(days=7))
    local = [s.astimezone(TZ).strftime("%a %H:%M") for s in slots]
    assert local == ["Mon 07:30", "Mon 20:00", "Wed 07:30", "Wed 20:00"]
    assert slots[1] == datetime(2026, 11, 9, 13, 0, tzinfo=timezone.utc)
    assert autopilot.describe_when([0, 2], ["20:00"]) == "T2 T4 · 20:00"


def test_a_plan_needs_days_times_and_a_connected_page(client, monkeypatch):
    cid = _channel(client)
    r = client.post("/api/autopilot/plans", json={"channel_id": cid, "days": [1], "times": ["20:00"]})
    assert r.status_code == 400 and "kết nối Facebook Page" in r.json()["detail"]
    monkeypatch.setattr(scheduler, "can_auto", lambda c: True)
    assert client.post("/api/autopilot/plans", json={"channel_id": cid, "days": [], "times": ["20:00"]}).status_code == 400
    assert client.post("/api/autopilot/plans", json={"channel_id": cid, "days": [1], "times": ["25:00"]}).status_code == 400
    p = client.post("/api/autopilot/plans", json={"channel_id": cid, "days": [1, 1, 3], "times": ["9:05", "20:00"]}).json()
    assert p["days"] == [1, 3] and p["times"] == ["09:05", "20:00"] and p["ai"] == "claude" and p["name"].startswith("Tự động")


def test_a_slot_coming_up_gets_its_post_written_and_scheduled_once(client, connected, monkeypatch):
    seen = []

    async def fake_write(brief, **kw):
        seen.append((registry.AI_OVERRIDE.get(), brief, kw.get("extra") or ""))
        return _fake_post()

    monkeypatch.setattr(post_writer, "write_post", fake_write)
    plan = _plan(client, _channel(client))
    assert _run_tick() == 1
    assert _run_tick() == 0  # the slot has its run: nothing written twice
    with get_session() as s:
        runs = s.exec(__import__("sqlmodel").select(AutoRun)).all()
        assert len(runs) == 1 and runs[0].status == "ready" and runs[0].ai_used == "claude"
        post = s.get(Post, runs[0].post_id)
        slot = s.get(Schedule, runs[0].schedule_id)
    assert post.brief["auto_plan"] == plan["id"] and post.brief["kind"] == "tips"
    assert slot.auto is True and slot.status == "planned" and slot.post_id == post.id
    assert seen[0][0] == "claude" and "nobody reads it" in seen[0][2]
    rows = client.get("/api/autopilot/plans").json()
    assert rows[0]["runs"][0]["status"] == "scheduled" and rows[0]["runs"][0]["post_title"] == post.title


def test_the_other_ai_writes_when_the_first_fails(client, connected, monkeypatch):
    async def fake_write(brief, **kw):
        if registry.AI_OVERRIDE.get() == "claude":
            raise post_writer.PostWriterError("LLM failed: claude CLI exited 1: hết lượt")
        return _fake_post()

    monkeypatch.setattr(post_writer, "write_post", fake_write)
    _plan(client, _channel(client))
    _run_tick()
    with get_session() as s:
        run = s.exec(__import__("sqlmodel").select(AutoRun)).one()
    assert run.status == "ready" and run.ai_used == "gemini" and "Claude CLI" in run.note


def test_writing_that_keeps_failing_waits_then_tries_again(client, connected, monkeypatch):
    async def broken(brief, **kw):
        raise post_writer.PostWriterError("không có mạng")

    monkeypatch.setattr(post_writer, "write_post", broken)
    _plan(client, _channel(client))
    _run_tick()
    with get_session() as s:
        run = s.exec(__import__("sqlmodel").select(AutoRun)).one()
    assert run.status == "waiting" and "không có mạng" in run.error and run.attempts == 1 and run.next_try_at is not None
    assert _run_tick() == 0  # not before its next try
    with get_session() as s:
        run = s.exec(__import__("sqlmodel").select(AutoRun)).one()
        run.next_try_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        s.add(run)
        s.commit()
    monkeypatch.setattr(post_writer, "write_post", lambda brief, **kw: asyncio.sleep(0, result=_fake_post()))
    assert _run_tick() == 1
    with get_session() as s:
        run = s.exec(__import__("sqlmodel").select(AutoRun)).one()
    assert run.status == "ready" and run.attempts == 2


def test_a_slot_passed_while_the_agent_was_off_is_missed_not_posted(client, connected, monkeypatch):
    monkeypatch.setattr(post_writer, "write_post", lambda brief, **kw: pytest.fail("a passed slot is never written"))
    plan = _plan(client, _channel(client), minutes=-60)
    with get_session() as s:
        row = s.get(AutoPlan, plan["id"])
        row.enabled_at = datetime.now(timezone.utc) - timedelta(hours=3)
        s.add(row)
        s.commit()
    _run_tick()
    with get_session() as s:
        run = s.exec(__import__("sqlmodel").select(AutoRun)).one()
    assert run.status == "missed" and "Agent không chạy" in run.error


def test_pausing_cancels_what_was_queued(client, connected, monkeypatch):
    monkeypatch.setattr(post_writer, "write_post", lambda brief, **kw: asyncio.sleep(0, result=_fake_post()))
    plan = _plan(client, _channel(client))
    _run_tick()
    r = client.patch(f"/api/autopilot/plans/{plan['id']}", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    with get_session() as s:
        run = s.exec(__import__("sqlmodel").select(AutoRun)).one()
        slot = s.get(Schedule, run.schedule_id)
        post = s.get(Post, run.post_id)
    assert run.status == "skipped" and slot.status == "skipped" and post is not None  # the post stays in Bài đã lưu


def test_products_are_taken_in_turn(client, connected):
    cid = _channel(client)
    with get_session() as s:
        ids = []
        for name in ("Gối bầu", "Đầm bầu"):
            p = Product(name=name)
            s.add(p)
            s.commit()
            s.refresh(p)
            ids.append(p.id)
    plan_row = _plan(client, cid, product_mode="rotate", product_ids=ids)
    with get_session() as s:
        plan = s.get(AutoPlan, plan_row["id"])
    first = autopilot._pick_product(plan)
    with get_session() as s:
        s.add(AutoRun(plan_id=plan.id, slot_at=datetime.now(timezone.utc), status="ready", product_id=first))
        s.commit()
    second = autopilot._pick_product(plan)
    assert {first, second} == set(ids)


def test_a_series_plan_writes_the_next_episode(client, connected, monkeypatch):
    cid = _channel(client)
    with get_session() as s:
        for ep in (1, 2):
            s.add(Post(title=f"Tập {ep}", body="…", channel_id=cid, series="Hệ Mặt Trời", episode=ep, brief={"kind": "story"}))
        s.commit()
    got = {}

    async def fake_write(brief, **kw):
        got["series"] = kw.get("series")
        return _fake_post("Tập 3: Sao Thổ")

    monkeypatch.setattr(post_writer, "write_post", fake_write)
    _plan(client, cid, series="Hệ Mặt Trời")
    _run_tick()
    assert got["series"]["episode"] == 3 and len(got["series"]["previous"]) == 2
    with get_session() as s:
        run = s.exec(__import__("sqlmodel").select(AutoRun)).one()
        assert s.get(Post, run.post_id).episode == 3


def test_use_ai_routes_run_llm(monkeypatch):
    from flowboard.services.llm import gemini_api, secrets

    async def fake_gemini(prompt, **kw):
        return f"gemini:{kw['model']}"

    monkeypatch.setattr(gemini_api, "configured", lambda: True)
    monkeypatch.setattr(gemini_api, "generate_text", fake_gemini)
    monkeypatch.setattr(secrets, "read_feature_config", lambda: {"auto_prompt": {"provider": "claude", "model": "sonnet"}})
    calls = {}

    class FakeClaude:
        supports_vision = True
        efforts: list = []

        async def is_available(self):
            return True

        async def run(self, prompt, **kw):
            calls.update(kw)
            return "claude"

    monkeypatch.setitem(registry._PROVIDERS, "claude", FakeClaude())

    async def go():
        with registry.use_ai("gemini"):
            a = await registry.run_llm("auto_prompt", "hi")
        with registry.use_ai("claude"):
            b = await registry.run_llm("auto_prompt", "hi")
        return a, b, await registry.run_llm("auto_prompt", "hi")

    a, b, c = asyncio.run(go())
    assert a == f"gemini:{registry.GEMINI_TEXT_MODEL}" and b == "claude" and c == "claude"
    assert calls["model"] == "sonnet"  # the seller's pinned Claude model
