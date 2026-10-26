"""Gói nội dung: one product → clip board + Facebook post + TikTok caption."""
import json

from flowboard.services import post_writer


def _setup(client, monkeypatch):
    seen = []

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen.append(prompt)
        platform = "tiktok" if "TikTok caption" in prompt else "fb"
        return json.dumps({"reply": "ok", "title": f"Bài {platform}", "body": f"Nội dung {platform}", "hashagss": [],
                           "hashtags": ["#comchay"], "image_prompts": [], "first_comment": ""})

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)

    async def no_tailor(spec, product, **kw):  # the LLM rewrite of the script is tested elsewhere
        return spec

    monkeypatch.setattr("flowboard.routes.templates.tailor_spec", no_tailor)
    ch = client.post("/api/channels", json={"name": "Bếp", "platforms": ["facebook", "tiktok"]}).json()
    prod = client.post("/api/products", json={"name": "Cơm cháy chà bông", "category": "food", "price": "35k",
                                              "aff_link": "https://s.shopee.vn/cc1"}).json()
    return ch, prod, seen


def test_bundle_makes_clip_post_and_caption(client, monkeypatch):
    ch, prod, seen = _setup(client, monkeypatch)
    assert client.get("/api/bundles/options").json()["post_kinds"][0]["key"] == "review"
    r = client.post("/api/bundles", json={"product_id": prod["id"], "channel_id": ch["id"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["errors"] == {}
    assert out["clip"]["template_id"] == prod["template_id"] and out["clip"]["name"].startswith("Cơm cháy chà bông")
    board = next(b for b in client.get("/api/boards", params={"summary": "true"}).json() if b["id"] == out["clip"]["id"])
    assert board["data"]["quicktool"]["product_id"] == prod["id"] and board["data"]["quicktool"]["channel_id"] == ch["id"]
    assert out["post"]["kind"] == "review" and out["post"]["body"] == "Nội dung fb"
    assert out["post"]["first_comment"].endswith("https://s.shopee.vn/cc1")  # the affiliate link rides in the first comment
    assert out["tiktok"]["kind"] == "tiktok_caption" and out["tiktok"]["body"] == "Nội dung tiktok"
    posts = client.get("/api/posts", params={"board_id": out["clip"]["id"]}).json()
    assert {p["kind"] for p in posts} == {"review", "tiktok_caption"} and all(p["channel_id"] == ch["id"] for p in posts)
    # both writers saw the clip's voice lines and the product
    assert all("PRODUCT: Cơm cháy chà bông" in p for p in seen) and all("THIS POST ACCOMPANIES A SHORT VIDEO" in p for p in seen)


def test_bundle_parts_are_optional_and_failures_are_per_part(client, monkeypatch):
    ch, prod, _ = _setup(client, monkeypatch)
    r = client.post("/api/bundles", json={"product_id": prod["id"], "channel_id": ch["id"], "with_clip": False, "with_tiktok": False, "post_kind": "tips"})
    assert r.status_code == 200 and r.json()["clip"] is None and r.json()["tiktok"] is None and r.json()["post"]["kind"] == "tips"
    assert client.post("/api/bundles", json={"product_id": prod["id"], "channel_id": ch["id"], "with_clip": False, "with_post": False, "with_tiktok": False}).status_code == 400
    assert client.post("/api/bundles", json={"product_id": 999, "channel_id": ch["id"]}).status_code == 400
    assert client.post("/api/bundles", json={"product_id": prod["id"], "channel_id": 999}).status_code == 400

    async def broken(*a, **k):
        raise post_writer.PostWriterError("LLM failed: down")

    monkeypatch.setattr(post_writer, "write_post", broken)
    r = client.post("/api/bundles", json={"product_id": prod["id"], "channel_id": ch["id"]})
    assert r.status_code == 200 and r.json()["clip"] and r.json()["post"] is None
    assert "LLM failed" in r.json()["errors"]["post"] and "LLM failed" in r.json()["errors"]["tiktok"]
