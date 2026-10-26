"""Mẫu đang hot: read a post / video, keep the breakdown, write our own version."""
import json

import pytest

from flowboard.services import post_writer, swipes

ANALYSIS = {"title": "Mẹ bầu kể chuyện đêm mất ngủ", "summary": "Kể chuyện rồi chốt mẹo.", "hook_type": "pain",
            "hook": "3 giờ sáng, mình lại dậy lần thứ tư…", "structure": ["Bước 1: nỗi khổ", "Bước 2: thử cách", "Bước 3: kết quả", "Bước 4: hỏi"],
            "why_it_works": ["ai cũng từng", "cụ thể"], "triggers": ["đồng cảm"], "format": "kể chuyện ngôi thứ nhất",
            "cta": "câu hỏi cuối", "skeleton": "[giờ], mình lại [vấn đề]…\n[cách thử]\n[kết quả]\nCòn mọi người thì sao?", "tags": ["mẹ bầu", "kể chuyện"]}


@pytest.fixture
def llm(monkeypatch):
    seen = {}

    async def fake(feature, prompt, *, system_prompt=None, timeout=0):
        seen.setdefault("prompts", []).append(prompt)
        if "You analyse one social post" in (system_prompt or ""):
            return json.dumps(ANALYSIS)
        return json.dumps({"reply": "ok", "title": "Bài theo mẫu", "body": "Bài của mình", "hashtags": ["#mebau"], "image_prompts": [], "first_comment": ""})

    monkeypatch.setattr(swipes, "run_llm", fake)
    monkeypatch.setattr(post_writer, "run_llm", fake)
    return seen


def test_platform_and_kind_detection():
    assert swipes.is_video_link("https://www.tiktok.com/@a/video/123") and swipes.is_video_link("https://v.douyin.com/abc")
    assert swipes.is_video_link("https://www.facebook.com/reel/99") and not swipes.is_video_link("https://www.facebook.com/page/posts/1")
    assert swipes._platform("https://www.threads.net/@x/post/1") == "threads" and swipes._platform("https://fb.watch/x") == "facebook"


def test_analyze_text_and_adapt_post(client, llm):
    r = client.post("/api/swipes/analyze", json={"text": "Bài gốc đủ dài để phân tích: 3 giờ sáng mình lại dậy lần thứ tư, mắt cay xè…"})
    assert r.status_code == 200, r.text
    sw = r.json()
    assert sw["kind"] == "post" and sw["platform"] == "text" and sw["title"] == ANALYSIS["title"]
    assert sw["analysis"]["hook_type"] == "pain" and sw["tags"] == ["mẹ bầu", "kể chuyện"]
    assert "CONTENT:\nBài gốc" in llm["prompts"][0]
    assert [x["id"] for x in client.get("/api/swipes").json()] == [sw["id"]]
    ch = client.post("/api/channels", json={"name": "Mẹ bầu", "platforms": ["facebook"]}).json()
    prod = client.post("/api/products", json={"name": "Gối bầu", "category": "home", "aff_link": "https://s.shopee.vn/g"}).json()
    r = client.post(f"/api/swipes/{sw['id']}/adapt", json={"as": "post", "channel_id": ch["id"], "product_id": prod["id"], "wish": "nhắc freeship"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["as"] == "post" and out["body"] == "Bài của mình"
    p = llm["prompts"][-1]
    assert "FOLLOW THE STRUCTURE OF THIS PROVEN POST" in p and "Hook type: pain" in p and "Bước 1: nỗi khổ" in p and "nhắc freeship" in p
    assert "do not copy sentences" in p
    saved = client.get("/api/posts").json()[0]
    assert saved["id"] == out["post_id"] and saved["channel_id"] == ch["id"] and saved["brief"]["swipe_id"] == sw["id"]
    assert saved["first_comment"].endswith("https://s.shopee.vn/g")
    assert client.get(f"/api/swipes/{sw['id']}").json()["uses"] == 1
    # a channel is required; a product is required for a clip
    assert client.post(f"/api/swipes/{sw['id']}/adapt", json={"as": "post", "channel_id": 999}).status_code == 400
    assert client.post(f"/api/swipes/{sw['id']}/adapt", json={"as": "clip", "channel_id": ch["id"]}).status_code == 400
    assert client.delete(f"/api/swipes/{sw['id']}").json() == {"ok": True}
    assert client.get("/api/swipes").json() == []


def test_analyze_needs_a_link_or_enough_text(client, llm):
    assert client.post("/api/swipes/analyze", json={}).status_code == 400
    r = client.post("/api/swipes/analyze", json={"text": "ngắn quá"})
    assert r.status_code == 400 and "Dán link" in r.json()["detail"]


def test_post_link_goes_through_the_extension(client, llm, monkeypatch):
    from flowboard.services import channel_page

    async def fake_read(url):
        return {"url": url, "title": "Bầu bì không khó", "text": "Facebook\n" * 5 + "Bài viết thật đây, đủ dài để tính là nội dung. " * 4, "via": "chrome"}

    monkeypatch.setattr(channel_page, "read_page", fake_read)
    r = client.post("/api/swipes/analyze", json={"url": "https://www.facebook.com/baubikhongkho/posts/123"})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "post" and r.json()["platform"] == "facebook" and r.json()["url"].startswith("https://www.facebook.com")
    assert "Facebook\nFacebook" not in llm["prompts"][-1]  # UI noise dropped


def test_adapt_clip_tailors_the_board_on_the_swipe(client, llm, monkeypatch):
    sw = client.post("/api/swipes/analyze", json={"text": "Bài gốc đủ dài để phân tích, kể chuyện đêm mất ngủ và mẹo nhỏ."}).json()
    ch = client.post("/api/channels", json={"name": "Mẹ bầu", "platforms": ["facebook"]}).json()
    prod = client.post("/api/products", json={"name": "Gối bầu", "category": "home"}).json()
    got = {}

    async def fake_tailor(board_id, pairs, *, instructions=None):
        got.update(board_id=board_id, pairs=pairs, instructions=instructions)
        return {"updated": len(pairs), "nodes": {}}

    monkeypatch.setattr("flowboard.services.script_tailor.tailor_board", fake_tailor)
    r = client.post(f"/api/swipes/{sw['id']}/adapt", json={"as": "clip", "channel_id": ch["id"], "product_id": prod["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["as"] == "clip" and r.json()["tailored"] and r.json()["name"].startswith("Gối bầu — theo mẫu")
    assert got["board_id"] == r.json()["board_id"] and len(got["pairs"]) >= 3 and all(v for _i, v in got["pairs"])
    assert "Follow the beats" in got["instructions"] and "Bước 2: thử cách" in got["instructions"]
