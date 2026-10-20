"""Gemini key pool: rotation on quota, parking of refused keys, parsing of
pasted keys. HTTP is faked at the httpx transport level."""
import asyncio
import json

import httpx
import pytest

from flowboard.services.llm import gemini_api, secrets


@pytest.fixture(autouse=True)
def _own_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWBOARD_SECRETS_PATH", str(tmp_path / "secrets.json"))
    gemini_api.pool.states.clear()
    yield
    gemini_api.pool.states.clear()


def _client_with(handler):
    """Patch httpx.AsyncClient so every request goes to ``handler``."""
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    class Patched(real):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    return Patched


def test_parse_keys_splits_any_separator_and_dedupes():
    text = "AQ.one\nAQ.two, AQ.three ; AQ.one\n\n 'AQ.four' "
    assert secrets.parse_keys(text) == ["AQ.one", "AQ.two", "AQ.three", "AQ.four"]
    secrets.set_gemini_keys(["k1", "", "k2", "k1"])
    assert secrets.get_gemini_keys() == ["k1", "k2"]
    secrets.set_gemini_keys([])
    assert secrets.get_gemini_keys() == [] and not gemini_api.configured()


def test_generate_rotates_to_the_next_key_on_quota(monkeypatch):
    secrets.set_gemini_keys(["AQ.key-quota-0000000001", "AQ.key-bad-00000000002", "AQ.key-good-0000000003"])
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers["x-goog-api-key"]
        seen.append(key)
        if key.startswith("AQ.key-quota"):
            return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded per day",
                                                        "details": [{"retryDelay": "31s"}]}})
        if key.startswith("AQ.key-bad"):
            return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid"}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "hello"}]}}]})

    monkeypatch.setattr(httpx, "AsyncClient", _client_with(handler))
    out = asyncio.run(gemini_api.generate_text("hi"))
    assert out == "hello" and [k.split("-")[1] for k in seen] == ["quota", "bad", "good"]
    snap = {s["masked"]: s for s in gemini_api.pool.snapshot()}
    assert snap[gemini_api.mask("AQ.key-quota-0000000001")]["parked"] and 25 <= snap[gemini_api.mask("AQ.key-quota-0000000001")]["parked_for_s"] <= 31
    assert snap[gemini_api.mask("AQ.key-bad-00000000002")]["parked"] and snap[gemini_api.mask("AQ.key-bad-00000000002")]["parked_for_s"] > 3600
    assert not snap[gemini_api.mask("AQ.key-good-0000000003")]["parked"] and snap[gemini_api.mask("AQ.key-good-0000000003")]["calls"] == 1

    # The parked keys are skipped next time; the good one answers straight away.
    seen.clear()
    asyncio.run(gemini_api.generate_text("again"))
    assert [k.split("-")[1] for k in seen] == ["good"]


def test_all_keys_exhausted_raises_a_clear_error(monkeypatch):
    secrets.set_gemini_keys(["k1", "k2"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "slow down"}})

    monkeypatch.setattr(httpx, "AsyncClient", _client_with(handler))
    with pytest.raises(gemini_api.NoKeyAvailable) as exc:
        asyncio.run(gemini_api.generate_text("hi"))
    assert "2 key" in str(exc.value)
    with pytest.raises(gemini_api.NoKeyAvailable):
        asyncio.run(gemini_api.generate_text("hi"))  # everything parked now


def test_non_quota_errors_do_not_rotate(monkeypatch):
    secrets.set_gemini_keys(["k1", "k2"])
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["x-goog-api-key"])
        return httpx.Response(500, json={"error": {"status": "INTERNAL", "message": "boom"}})

    monkeypatch.setattr(httpx, "AsyncClient", _client_with(handler))
    with pytest.raises(gemini_api.GeminiAPIError, match="HTTP 500"):
        asyncio.run(gemini_api.generate_text("hi"))
    assert seen == ["k1"]


def test_generate_sends_schema_system_and_inline_media(monkeypatch, tmp_path):
    secrets.set_gemini_keys(["k1"])
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "```json\n{\"a\": 1}\n```"}]}}]})

    monkeypatch.setattr(httpx, "AsyncClient", _client_with(handler))
    text = asyncio.run(gemini_api.generate_with_media(
        [gemini_api.text_part("before")], img, [gemini_api.text_part("after")],
        model="gemini-3.8-flash", system="sys", response_schema={"type": "OBJECT"}))
    assert gemini_api.parse_json(text) == {"a": 1}
    body = captured["body"]
    assert captured["url"].endswith("/models/gemini-3.8-flash:generateContent")
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    assert body["generationConfig"] == {"responseMimeType": "application/json", "responseSchema": {"type": "OBJECT"}}
    parts = body["contents"][0]["parts"]
    assert parts[0] == {"text": "before"} and parts[2] == {"text": "after"}
    assert parts[1]["inlineData"]["mimeType"] == "image/png"


def test_key_routes_mask_and_test(client, monkeypatch):
    r = client.put("/api/llm/gemini-keys", json={"text": "AQ.abcdefghijklmnop\nAQ.qrstuvwxyz123456"})
    assert r.status_code == 200 and r.json()["count"] == 2
    masked = [k["masked"] for k in r.json()["keys"]]
    assert masked == ["AQ.abc…mnop", "AQ.qrs…3456"] and "AQ.abcdefghijklmnop" not in r.text

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["x-goog-api-key"].endswith("mnop"):
            return httpx.Response(200, json={"models": [{"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]}]})
        return httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED", "message": "API key expired"}})

    monkeypatch.setattr(httpx, "AsyncClient", _client_with(handler))
    r = client.post("/api/llm/gemini-keys/test")
    results = r.json()["results"]
    assert results[0]["ok"] is True and results[0]["models"] == 1
    assert results[1]["ok"] is False and results[1]["error"] == "bị từ chối"
    assert r.json()["keys"][1]["parked"] is True
