"""Clip from a reference video: the mismatch verdict, the board spec, and
the three routes with Gemini faked."""
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Board, Edge, Node
from flowboard.services import reference_video as rv


def _analysis(score=0.9, relevant=True, character=True):
    return {
        "category": "fashion", "product_seen": "a white t-shirt", "hook": "street walk", "style": "lifestyle",
        "tone": "warm", "has_person": True, "voice_transcript_vi": "",
        "scenes": [{"start_s": 0, "end_s": 4, "shot": "full", "action": "walks in"}],
        "plan": [
            {"title_vi": "Mở đầu", "image_prompt_en": "Full-body photo of the model wearing the product from the reference photo on a street",
             "motion_prompt_en": "0-3s walks. 3-8s smiles.", "narration_vi": "Mọi người ơi, áo này đẹp lắm"},
            {"title_vi": "Cận", "image_prompt_en": "Close-up of the fabric of the product from the reference photo",
             "motion_prompt_en": "0-8s hand strokes fabric.", "narration_vi": "Vải mát, ghé giỏ hàng nhé"},
        ],
        "script_vi": "Kịch bản ngắn",
        "character": {"gender": "female", "country": "vn", "vibe": "clean", "extras_en": "long hair"} if character else None,
        "match": {"relevant": relevant, "score": score, "reason_vi": "Cùng là áo thun"},
    }


def _product(category="fashion"):
    return {"id": 1, "name": "Áo thun SAIGON", "category": category, "description": "a white t-shirt",
            "price": "189k", "selling_points": "Cotton", "link": "", "media_ids": ["a1b2c3d4-0000-4000-8000-000000000001"],
            "aspect_ratio": None}


def test_normalize_blocks_a_product_that_does_not_fit():
    out = rv.normalize(_analysis(score=0.1, relevant=False), _product("food"))
    assert out["blocked"] is True and "đồ ăn" in out["block_reason"] and "Áo thun SAIGON" in out["block_reason"]
    ok = rv.normalize(_analysis(), _product())
    assert ok["blocked"] is False and ok["category_vi"] == "thời trang"
    none = rv.normalize(_analysis(score=0.0, relevant=False), None)  # no product: nothing to mismatch
    assert none["blocked"] is False
    with pytest.raises(rv.ReferenceVideoError, match="at least 2"):
        rv.normalize({**_analysis(), "plan": _analysis()["plan"][:1]}, None)


def test_board_spec_mirrors_the_template_shape():
    spec = rv.board_spec(rv.normalize(_analysis(), None), None)
    keys = [n["key"] for n in spec["nodes"]]
    assert keys == ["script", "model", "product", "s1", "v1", "s2", "v2"]
    assert ["model", "s1"] in spec["edges"] and ["product", "s2"] in spec["edges"] and ["s2", "v2"] in spec["edges"]
    v1 = next(n for n in spec["nodes"] if n["key"] == "v1")
    assert v1["data"]["narration"] == "Mọi người ơi, áo này đẹp lắm"
    s1 = next(n for n in spec["nodes"] if n["key"] == "s1")
    assert "reference photo exactly" in s1["data"]["prompt"]
    # no person in the video → no character node, scenes hang off the product only
    spec2 = rv.board_spec(rv.normalize(_analysis(character=False), None), None)
    assert "model" not in [n["key"] for n in spec2["nodes"]]


def test_routes_upload_analyze_build(client, tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWBOARD_SECRETS_PATH", str(tmp_path / "s.json"))
    from flowboard.services.llm import secrets
    secrets.set_gemini_keys(["k1"])
    client.post("/api/products", json=_product())

    r = client.post("/api/reference-video/upload", files={"file": ("ad.mp4", b"\x00" * 64, "video/mp4")})
    assert r.status_code == 200, r.text
    media_id = r.json()["media_id"]
    assert client.get(f"/media/{media_id}").status_code == 200
    assert client.post("/api/reference-video/upload", files={"file": ("x.txt", b"hi", "text/plain")}).status_code == 415

    async def fake_analyze(path, product, *, scenes=None, model=None, voiceless=False):
        return rv.normalize(_analysis(score=0.2 if product and product["category"] == "food" else 0.9,
                                      relevant=not (product and product["category"] == "food")), product)

    with patch.object(rv, "analyze", fake_analyze):
        r = client.post("/api/reference-video/analyze", json={"media_id": media_id, "product_id": 1})
    assert r.status_code == 200 and r.json()["blocked"] is False
    analysis = r.json()["analysis"]

    # a mismatching product is refused unless forced
    client.post("/api/products", json={**_product("food"), "name": "Bánh tráng"})
    bad = rv.normalize(_analysis(score=0.2, relevant=False), {**_product("food"), "id": 2, "name": "Bánh tráng"})
    r = client.post("/api/reference-video/build", json={"media_id": media_id, "product_id": 2, "analysis": bad})
    assert r.status_code == 409 and "Bánh tráng" in r.text
    r = client.post("/api/reference-video/build", json={"media_id": media_id, "product_id": 2, "analysis": bad, "force": True})
    assert r.status_code == 200

    r = client.post("/api/reference-video/build", json={"media_id": media_id, "product_id": 1, "analysis": analysis})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Áo thun SAIGON — theo video mẫu"
    with get_session() as s:
        board = s.get(Board, body["id"])
        nodes = {n.short_id: n for n in s.exec(select(Node).where(Node.board_id == body["id"])).all()}
        edges = s.exec(select(Edge).where(Edge.board_id == body["id"])).all()
    qt = board.data["quicktool"]
    assert qt["template_id"] == "reference_video" and qt["source_media_id"] == media_id and qt["product_id"] == 1
    product = nodes[body["nodes"]["product"]]
    assert product.status == "done" and product.data["mediaId"] == "a1b2c3d4-0000-4000-8000-000000000001"
    assert nodes[body["nodes"]["v2"]].data["narration"] == "Vải mát, ghé giỏ hàng nhé"
    assert len(edges) == 2 * 2 + 2  # (model+product) → each scene, scene → video
    assert client.post("/api/reference-video/analyze", json={"media_id": "deadbeef" * 4}).status_code == 404


def test_fetch_route_downloads_with_ytdlp(client, monkeypatch, tmp_path):
    from flowboard.routes import reference_video as route
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    seen = {}

    def fake_run(cmd, capture_output, timeout, check):
        class P:
            returncode = 0
            stdout = b""
            stderr = b""
        if "yt-dlp" not in str(cmd[0]):
            return P()  # ffprobe on the fake file: nothing to report
        seen["cmd"] = cmd
        out = str(cmd[cmd.index("-o") + 1])
        Path(out.replace("%(ext)s", "mp4")).write_bytes(b"\x00" * 10)
        P.stdout = b"title::My TikTok ad\n"
        return P()

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: f"C:/{name}.exe")
    r = client.post("/api/reference-video/fetch", json={"url": "https://www.tiktok.com/@shop/video/123"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "My TikTok ad" and r.json()["size"] == 10
    assert "--no-plugin-dirs" in seen["cmd"] and "--max-filesize" in seen["cmd"]
    assert client.get(f"/media/{r.json()['media_id']}").status_code == 200

    assert client.post("/api/reference-video/fetch", json={"url": "https://example.com/v.mp4"}).status_code == 400

    def failing(cmd, capture_output, timeout, check):
        class P:
            returncode = 1
            stdout = b""
            stderr = b"WARNING: x\nERROR: Unsupported URL: nope\n"
        return P()
    monkeypatch.setattr(subprocess, "run", failing)
    r = client.post("/api/reference-video/fetch", json={"url": "https://youtu.be/abc"})
    assert r.status_code == 502 and "Unsupported URL" in r.text
