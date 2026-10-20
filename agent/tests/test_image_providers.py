"""Image generation through OpenAI / xAI instead of Flow: request shapes,
error mapping, the worker hook, and the key routes. HTTP is faked with
``httpx.MockTransport`` — no real call ever leaves this file."""
from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from flowboard.services import image_providers as ip

PNG = b"\x89PNG\r\n\x1a\n" + bytes(16) + b"fake-png-bytes"
B64 = base64.b64encode(PNG).decode("ascii")


@pytest.fixture
def secrets_path(tmp_path, monkeypatch):
    p = tmp_path / "secrets.json"
    monkeypatch.setenv("FLOWBOARD_SECRETS_PATH", str(p))
    return p


def _mock(monkeypatch, handler):
    """Route every AsyncClient the module builds through ``handler``."""
    seen: list[httpx.Request] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    def client(timeout=ip.GENERATE_TIMEOUT_S):
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), timeout=timeout)

    monkeypatch.setattr(ip, "_client", client)
    return seen


def _ok_image(_req):
    return httpx.Response(200, json={"created": 1, "data": [{"b64_json": B64}]})


# ── generate ───────────────────────────────────────────────────────────


def test_openai_generations_body_and_b64_decode(monkeypatch):
    seen = _mock(monkeypatch, _ok_image)
    raw = asyncio.run(ip.generate("openai", "a lipstick on marble", aspect_ratio="IMAGE_ASPECT_RATIO_PORTRAIT",
                                  reference_images=[], api_key="sk-test"))
    assert raw == PNG
    req = seen[0]
    assert req.url == "https://api.openai.com/v1/images/generations"
    assert req.headers["authorization"] == "Bearer sk-test"
    body = json.loads(req.content)
    assert body == {"model": "gpt-image-1", "prompt": "a lipstick on marble", "size": "1024x1536",
                    "quality": "medium", "n": 1}
    assert "response_format" not in body  # rejected by GPT image models


def test_openai_uses_edits_multipart_when_references_given(monkeypatch):
    seen = _mock(monkeypatch, _ok_image)
    raw = asyncio.run(ip.generate("openai", "product on a desk", aspect_ratio="IMAGE_ASPECT_RATIO_LANDSCAPE",
                                  reference_images=[PNG, b"\xff\xd8\xff" + bytes(20)], api_key="sk-test"))
    assert raw == PNG
    req = seen[0]
    assert req.url == "https://api.openai.com/v1/images/edits"
    ctype = req.headers["content-type"]
    assert ctype.startswith("multipart/form-data")
    content = req.content
    assert content.count(b'name="image[]"') == 2
    assert b'filename="ref0.png"' in content and b'filename="ref1.jpg"' in content
    assert b'name="size"\r\n\r\n1536x1024' in content
    assert b'name="model"\r\n\r\ngpt-image-1' in content


def test_xai_generations_body(monkeypatch):
    seen = _mock(monkeypatch, _ok_image)
    raw = asyncio.run(ip.generate("xai", "sneaker on a court", aspect_ratio="IMAGE_ASPECT_RATIO_SQUARE",
                                  reference_images=[PNG], api_key="xai-test"))
    assert raw == PNG
    req = seen[0]
    assert req.url == "https://api.x.ai/v1/images/generations"
    body = json.loads(req.content)
    assert body == {"model": ip.XAI_MODEL, "prompt": "sneaker on a court", "aspect_ratio": "1:1",
                    "response_format": "b64_json", "n": 1}


def test_generate_reads_key_from_secrets(secrets_path, monkeypatch):
    from flowboard.services.llm import secrets
    secrets.set_api_key("xai", "xai-stored")
    seen = _mock(monkeypatch, _ok_image)
    asyncio.run(ip.generate("xai", "p", aspect_ratio=None, reference_images=None))
    assert seen[0].headers["authorization"] == "Bearer xai-stored"
    secrets.set_api_key("xai", None)
    with pytest.raises(ip.ImageProviderError, match="Chưa có API key"):
        asyncio.run(ip.generate("xai", "p", aspect_ratio=None, reference_images=None))


@pytest.mark.parametrize("status, needle", [
    (401, "API key sai hoặc hết hạn"),
    (403, "API key sai hoặc hết hạn"),
    (429, "hết quota"),
    (500, "HTTP 500 — server exploded"),
])
def test_error_mapping(monkeypatch, status, needle):
    _mock(monkeypatch, lambda _r: httpx.Response(status, json={"error": {"message": "server exploded"}}))
    with pytest.raises(ip.ImageProviderError) as exc:
        asyncio.run(ip.generate("openai", "p", aspect_ratio=None, reference_images=None, api_key="k"))
    assert needle in str(exc.value)
    assert "OpenAI GPT Image" in str(exc.value)


def test_empty_data_is_an_error(monkeypatch):
    _mock(monkeypatch, lambda _r: httpx.Response(200, json={"data": []}))
    with pytest.raises(ip.ImageProviderError, match="không có ảnh"):
        asyncio.run(ip.generate("openai", "p", aspect_ratio=None, reference_images=None, api_key="k"))


def test_sizes():
    assert ip.openai_size("IMAGE_ASPECT_RATIO_PORTRAIT") == "1024x1536"
    assert ip.openai_size("IMAGE_ASPECT_RATIO_LANDSCAPE") == "1536x1024"
    assert ip.openai_size("IMAGE_ASPECT_RATIO_SQUARE") == "1024x1024"
    assert ip.openai_size(None) == "1536x1024"
    assert ip.xai_aspect("IMAGE_ASPECT_RATIO_PORTRAIT") == "9:16"
    assert ip.xai_aspect("IMAGE_ASPECT_RATIO_LANDSCAPE") == "16:9"


# ── worker hook ────────────────────────────────────────────────────────


def test_hook_returns_none_for_flow():
    assert asyncio.run(ip.maybe_generate_via_api({"image_provider": "flow", "prompt": "p"})) is None
    assert asyncio.run(ip.maybe_generate_via_api({"prompt": "p"})) is None
    assert asyncio.run(ip.maybe_generate_via_api({"image_provider": "", "prompt": "p"})) is None


def test_hook_rejects_unknown_provider_and_missing_fields():
    assert asyncio.run(ip.maybe_generate_via_api({"image_provider": "dalle", "prompt": "p"})) == \
        ({}, "unknown_image_provider:dalle")
    assert asyncio.run(ip.maybe_generate_via_api({"image_provider": "openai", "prompt": " "})) == ({}, "missing_prompt")
    assert asyncio.run(ip.maybe_generate_via_api({"image_provider": "openai", "prompt": "p"})) == \
        ({}, "missing_project_id")


def test_hook_generates_and_ingests_into_flow(monkeypatch, tmp_path, secrets_path):
    """Reference bytes come from the media cache, the API renders, and the
    PNG goes through the Flow upload path; the result has the keys the
    worker's node patch reads."""
    from flowboard.services.llm import secrets
    secrets.set_api_key("openai", "sk-hook")
    seen = _mock(monkeypatch, _ok_image)
    ref = tmp_path / "ref.png"
    ref.write_bytes(PNG)
    monkeypatch.setattr(ip.media_service, "cached_path", lambda mid: ref if mid == "aa00-0ef1" else None)
    ingested: list[dict] = []

    async def fake_ingest(raw, mime, project_id, file_name, node_id):
        ingested.append({"raw": raw, "mime": mime, "project_id": project_id, "file_name": file_name, "node_id": node_id})
        return {"media_id": f"m-{len(ingested)}", "mime": mime, "size": len(raw), "width": 1024, "height": 1536,
                "aspect_ratio": "IMAGE_ASPECT_RATIO_PORTRAIT"}

    monkeypatch.setattr(ip, "_ingest", fake_ingest)
    result, err = asyncio.run(ip.maybe_generate_via_api({
        "image_provider": "openai", "prompt": "lipstick", "project_id": "proj-1",
        "aspect_ratio": "IMAGE_ASPECT_RATIO_PORTRAIT", "ref_media_ids": ["aa00-0ef1", "zz-missing"],
        "variant_count": 2, "prompts": ["variant A"], "__node_id": 7,
    }))
    assert err is None
    assert result["media_ids"] == ["m-1", "m-2"] and result["media_id"] == "m-1"
    assert result["slot_errors"] == [None, None] and result["partial_error"] is None
    assert result["provider"] == "openai" and result["model"] == "gpt-image-1"
    assert [e["media_id"] for e in result["media_entries"]] == ["m-1", "m-2"]
    assert len(ingested) == 2 and ingested[0]["project_id"] == "proj-1" and ingested[0]["node_id"] == 7
    assert ingested[0]["mime"] == "image/png" and ingested[0]["raw"] == PNG
    # Two API calls (one per variant), both against the edits endpoint
    # because a reference was found; the missing ref is skipped silently.
    assert len(seen) == 2 and all(str(r.url).endswith("/images/edits") for r in seen)
    prompts = sorted(r.content.split(b'name="prompt"\r\n\r\n')[1].split(b"\r\n")[0] for r in seen)
    assert prompts == [b"lipstick", b"variant A"]


def test_hook_reports_api_failure(monkeypatch, secrets_path):
    from flowboard.services.llm import secrets
    secrets.set_api_key("xai", "xai-hook")
    _mock(monkeypatch, lambda _r: httpx.Response(401, text="nope"))
    monkeypatch.setattr(ip.media_service, "cached_path", lambda mid: None)
    result, err = asyncio.run(ip.maybe_generate_via_api({
        "image_provider": "xai", "prompt": "p", "project_id": "proj", "ref_media_ids": [],
    }))
    assert err and "API key" in err and result == {"provider": "xai"}


def test_hook_partial_batch(monkeypatch, secrets_path):
    from flowboard.services.llm import secrets
    secrets.set_api_key("openai", "sk-hook")
    calls = {"n": 0}

    def flaky(_req):
        calls["n"] += 1
        return _ok_image(_req) if calls["n"] == 1 else httpx.Response(429, text="slow down")

    _mock(monkeypatch, flaky)
    monkeypatch.setattr(ip.media_service, "cached_path", lambda mid: None)

    async def fake_ingest(raw, mime, project_id, file_name, node_id):
        return {"media_id": "only-one", "mime": mime, "size": len(raw)}

    monkeypatch.setattr(ip, "_ingest", fake_ingest)
    result, err = asyncio.run(ip.maybe_generate_via_api({
        "image_provider": "openai", "prompt": "p", "project_id": "proj", "variant_count": 2,
    }))
    assert err is None and result["media_ids"] == ["only-one", None]
    assert result["slot_errors"][1] and "hết quota" in result["slot_errors"][1]
    assert result["partial_error"].startswith("1/2 variants failed")


# ── routes ─────────────────────────────────────────────────────────────


@pytest.fixture
def api(client):
    from flowboard.main import app
    from flowboard.routes import image_providers as route
    if not any(getattr(r, "path", "").startswith("/api/image-providers") for r in app.routes):
        app.include_router(route.router)
    return client


def test_routes_list_set_remove(api, secrets_path):
    r = api.get("/api/image-providers")
    assert r.status_code == 200
    rows = {row["id"]: row for row in r.json()}
    assert set(rows) == {"flow", "openai", "xai"}
    assert rows["flow"]["configured"] is True and rows["openai"]["configured"] is False
    assert rows["xai"]["model"] == ip.XAI_MODEL and "tham chiếu" in rows["xai"]["notes_vi"]

    r = api.put("/api/image-providers/openai/key", json={"key": "  sk-abc  "})
    assert r.status_code == 200 and r.json()["configured"] is True
    assert json.loads(secrets_path.read_text())["apiKeys"]["openai"] == "sk-abc"

    r = api.put("/api/image-providers/openai/key", json={"key": ""})
    assert r.status_code == 200 and r.json()["configured"] is False
    assert "openai" not in json.loads(secrets_path.read_text())["apiKeys"]

    assert api.put("/api/image-providers/flow/key", json={"key": "x"}).status_code == 400
    assert api.put("/api/image-providers/nope/key", json={"key": "x"}).status_code == 404


def test_routes_test_key(api, secrets_path, monkeypatch):
    seen = _mock(monkeypatch, lambda req: httpx.Response(
        200, json={"id": "gpt-image-1", "object": "model"} if "openai" in str(req.url)
        else {"data": [{"id": "grok-imagine-image-2.0"}]}))
    # Unsaved key sent in the body.
    r = api.post("/api/image-providers/openai/test", json={"key": "sk-draft"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert seen[-1].url == "https://api.openai.com/v1/models/gpt-image-1"
    assert seen[-1].headers["authorization"] == "Bearer sk-draft"
    # Saved key, no body.
    from flowboard.services.llm import secrets
    secrets.set_api_key("xai", "xai-saved")
    r = api.post("/api/image-providers/xai/test")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert seen[-1].url == "https://api.x.ai/v1/models" and seen[-1].headers["authorization"] == "Bearer xai-saved"
    # No key anywhere.
    r = api.post("/api/image-providers/openai/test")
    assert r.status_code == 200 and r.json()["ok"] is False and "Chưa có API key" in r.json()["message"]
    # Bad key.
    _mock(monkeypatch, lambda _r: httpx.Response(401, text="bad"))
    r = api.post("/api/image-providers/openai/test", json={"key": "sk-bad"})
    assert r.json()["ok"] is False and "API key sai" in r.json()["message"]
    assert api.post("/api/image-providers/flow/test").json()["ok"] is True
