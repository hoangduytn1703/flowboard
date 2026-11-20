"""Reference video / product page plans: Gemini models race (a lite model's
answer is held briefly for a stronger one), the picked AI steps in when
Google is overloaded, and a CLI reads a video as one contact sheet."""
import asyncio
import json
import shutil
import subprocess
import time

import httpx
import pytest

from flowboard.services import plan_ai
from flowboard.services.llm import gemini_api, registry, secrets

PLAN = {"category": "fashion", "product_seen": "túi", "plan": [
    {"title_vi": "Cảnh 1", "image_prompt_en": "a bag", "motion_prompt_en": "walks", "narration_vi": "Đẹp ghê"},
    {"title_vi": "Cảnh 2", "image_prompt_en": "the bag close", "motion_prompt_en": "turns", "narration_vi": "Xem giỏ nha"},
]}


@pytest.fixture(autouse=True)
def _fast(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWBOARD_SECRETS_PATH", str(tmp_path / "secrets.json"))
    gemini_api.pool.states.clear()
    monkeypatch.setattr(gemini_api, "RACE_RETRY_S", 0.01)
    monkeypatch.setattr(gemini_api, "RACE_RETRY_MAX_S", 0.02)
    monkeypatch.setattr(gemini_api, "RACE_PREFER_S", 0.3)
    yield
    gemini_api.pool.states.clear()


def _client_with(handler):
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    class Patched(real):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    return Patched


def _ok(text: str) -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def _busy() -> httpx.Response:
    return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE", "message": "high demand"}})


def _model(request: httpx.Request) -> str:
    return request.url.path.rsplit("/", 1)[-1].split(":")[0]


def test_the_race_takes_the_lite_answer_when_every_bigger_model_is_overloaded(monkeypatch):
    secrets.set_gemini_keys(["k1", "k2", "k3"])
    calls: dict[str, int] = {}

    def handler(request):
        m = _model(request)
        calls[m] = calls.get(m, 0) + 1
        return _ok(json.dumps({"by": m})) if m == "gemini-3.1-flash-lite" else _busy()

    monkeypatch.setattr(httpx, "AsyncClient", _client_with(handler))
    t = time.monotonic()
    res = asyncio.run(gemini_api.race([gemini_api.text_part("x")], json.loads, deadline_s=3.0))
    assert res.model == "gemini-3.1-flash-lite" and res.value == {"by": "gemini-3.1-flash-lite"}
    # held for RACE_PREFER_S while the overloaded ones kept retrying, never the whole deadline
    assert 0.25 <= time.monotonic() - t < 2.5
    assert calls["gemini-3.5-flash"] >= 2 and calls["gemini-3.8-flash"] >= 2


def test_a_stronger_answer_inside_the_hold_beats_the_lite_one(monkeypatch):
    secrets.set_gemini_keys(["k1", "k2"])
    seen: dict[str, int] = {}

    def handler(request):
        m = _model(request)
        seen[m] = seen.get(m, 0) + 1
        if m == "gemini-3.1-flash-lite":
            return _ok('{"by": "lite"}')
        if m == "gemini-3.5-flash" and seen[m] >= 3:
            return _ok('{"by": "strong"}')
        return _busy()

    monkeypatch.setattr(httpx, "AsyncClient", _client_with(handler))
    res = asyncio.run(gemini_api.race([gemini_api.text_part("x")], json.loads, deadline_s=3.0))
    assert res.model == "gemini-3.5-flash" and res.value == {"by": "strong"}


def test_a_model_that_takes_no_thinking_level_is_asked_plainly_and_keeps_its_key(monkeypatch):
    secrets.set_gemini_keys(["k1"])
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body.get("generationConfig", {}))
        if "thinkingConfig" in body.get("generationConfig", {}):
            return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT",
                                                       "message": "Thinking level is not valid for this model"}})
        return _ok('{"ok": 1}')

    monkeypatch.setattr(httpx, "AsyncClient", _client_with(handler))
    res = asyncio.run(gemini_api.race([gemini_api.text_part("x")], json.loads,
                                      models=[("gemini-3.5-flash", "low")], deadline_s=3.0))
    assert res.value == {"ok": 1}
    assert bodies[0]["thinkingConfig"] == {"thinkingLevel": "low"} and "thinkingConfig" not in bodies[-1]
    assert not any(s["parked"] for s in gemini_api.pool.snapshot())  # "not valid" never parks the key for hours


def test_when_every_model_stays_overloaded_the_race_says_so_at_its_deadline(monkeypatch):
    secrets.set_gemini_keys(["k1"])
    monkeypatch.setattr(httpx, "AsyncClient", _client_with(lambda request: _busy()))
    t = time.monotonic()
    with pytest.raises(gemini_api.RaceLost, match="quá tải"):
        asyncio.run(gemini_api.race([gemini_api.text_part("x")], json.loads, deadline_s=0.5))
    assert time.monotonic() - t < 3.0


def test_the_picked_ai_steps_in_when_google_is_overloaded(monkeypatch):
    secrets.set_gemini_keys(["k1"])
    monkeypatch.setattr(plan_ai, "BACKUP_AFTER_S", 0.3)
    monkeypatch.setattr(httpx, "AsyncClient", _client_with(lambda request: _busy()))
    asked = {}

    async def picked(feature, *, vision=False):
        return "claude"

    async def run_llm(feature, prompt, **kw):
        asked.update(feature=feature, prompt=prompt, **kw)
        return "```json\n" + json.dumps(PLAN) + "\n```"

    monkeypatch.setattr(registry, "picked_ai", picked)
    monkeypatch.setattr(registry, "run_llm", run_llm)
    out = asyncio.run(plan_ai.plan_from_text("ASK", system="SYS", schema={"type": "OBJECT"}, accept=gemini_api.parse_json))
    assert out["by"] == "Claude" and out["plan"] == PLAN["plan"]
    assert asked["feature"] == "auto_prompt" and asked["effort"] == "low" and asked["gemini_backup"] is False
    assert "ASK" in asked["prompt"] and "JSON schema" in asked["prompt"]


def test_a_quick_gemini_answer_never_wakes_the_backup(monkeypatch):
    secrets.set_gemini_keys(["k1"])
    monkeypatch.setattr(httpx, "AsyncClient", _client_with(lambda request: _ok(json.dumps(PLAN))))
    backup_calls = []

    async def picked(feature, *, vision=False):
        return "claude"

    async def run_llm(*a, **kw):
        backup_calls.append(1)
        return json.dumps(PLAN)

    monkeypatch.setattr(registry, "picked_ai", picked)
    monkeypatch.setattr(registry, "run_llm", run_llm)
    out = asyncio.run(plan_ai.plan_from_text("ASK", system="SYS", schema={}, accept=json.loads))
    assert out["by"] == "Gemini 3.5 Flash" and not backup_calls


def test_a_race_lost_early_calls_the_backup_without_waiting(monkeypatch):
    secrets.set_gemini_keys(["k1"])
    monkeypatch.setattr(plan_ai, "BACKUP_AFTER_S", 30.0)

    def refused(request):  # every key out of quota: the race is over at once
        return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "per day"}})

    monkeypatch.setattr(httpx, "AsyncClient", _client_with(refused))

    async def picked(feature, *, vision=False):
        return "claude"

    async def run_llm(*a, **kw):
        return json.dumps(PLAN)

    monkeypatch.setattr(registry, "picked_ai", picked)
    monkeypatch.setattr(registry, "run_llm", run_llm)
    t = time.monotonic()
    out = asyncio.run(plan_ai.plan_from_text("ASK", system="SYS", schema={}, accept=json.loads))
    assert out["by"] == "Claude" and time.monotonic() - t < 5.0


def test_no_gemini_and_no_picked_ai_is_a_clear_error(monkeypatch):
    async def picked(feature, *, vision=False):
        return None

    monkeypatch.setattr(registry, "picked_ai", picked)
    with pytest.raises(plan_ai.PlanError, match="Gemini API key"):
        asyncio.run(plan_ai.plan_from_text("ASK", system="SYS", schema={}, accept=json.loads))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_video_reaches_a_cli_as_one_contact_sheet_with_the_speech(monkeypatch, tmp_path):
    video = tmp_path / "ref.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=360x640:rate=25",
                    "-t", "4", "-pix_fmt", "yuv420p", str(video)], check=True)
    monkeypatch.setattr(plan_ai, "hear", lambda v, w, stop: ["[0.0-1.5] túi này đẹp lắm"])
    seen = {}

    async def picked(feature, *, vision=False):
        assert feature == "vision" and vision
        return "claude"

    async def run_llm(feature, prompt, **kw):
        sheet = kw["attachments"][0]
        seen.update(prompt=prompt, sheet_bytes=open(sheet, "rb").read()[:3])
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", sheet],
                               capture_output=True, text=True, check=True)
        seen["size"] = probe.stdout.strip()
        return json.dumps(PLAN)

    monkeypatch.setattr(registry, "picked_ai", picked)
    monkeypatch.setattr(registry, "run_llm", run_llm)
    out = asyncio.run(plan_ai.plan_from_video(video, "ASK", system="SYS", schema={}, accept=json.loads,
                                              duration=4.0))
    assert out["by"].startswith("Claude (xem 12 khung hình")
    assert seen["sheet_bytes"] == b"\xff\xd8\xff"  # a JPEG
    w, h = (int(x) for x in seen["size"].split(","))
    assert w > 4 * 300 and h > 3 * 500  # 4 x 3 tiles of 320 px wide frames
    assert "túi này đẹp lắm" in seen["prompt"] and "frame times 1: 0.2s" in seen["prompt"]
