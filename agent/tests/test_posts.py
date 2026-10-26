"""Facebook posts: the writer's prompt + parsing, and the library routes."""
import json

import pytest

from flowboard.services import post_writer


def _answer(**over):
    data = {"reply": "Mình viết bài hỏi ý kiến nhé.", "title": "Cơm cháy hỏi ý kiến",
            "body": "Cả nhà ăn cơm cháy cay hay không cay? 🤔\n\nMình thì...", "hashtags": ["comchay", "#AnVat", "#comchay"],
            "image_prompts": ["A plate of crispy scorched rice", "A zip bag of snack", "extra"]}
    data.update(over)
    return json.dumps(data, ensure_ascii=False)


@pytest.mark.asyncio
async def test_brief_product_and_clip_go_to_the_writer_and_answer_is_cleaned(monkeypatch):
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"], seen["system"] = prompt, system_prompt
        return "```json\n" + _answer() + "\n```"

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    out = await post_writer.write_post(
        {"kind": "discussion", "topic": "cay hay không cay", "tone": "funny", "length": "short", "cta": "link", "images": 2},
        product={"name": "Cơm cháy siêu chà bông", "price": "129.000đ", "selling_points": "Giòn rụm"},
        clip={"name": "Cơm cháy — clip", "lines": ["Giòn rụm luôn", ""]},
    )
    p = seen["prompt"]
    assert "Hỏi ý kiến" in p and "cay hay không cay" in p and "Cơm cháy siêu chà bông" in p and "129.000đ" in p
    assert "Giòn rụm luôn" in p and "Images requested: 2" in p and "first comment" in p
    assert "never invent" in seen["system"]
    assert out["hashtags"] == ["#comchay", "#AnVat"]          # '#' added, duplicate dropped
    assert len(out["image_prompts"]) == 2                    # capped to what was asked
    assert out["body"].startswith("Cả nhà ăn cơm cháy")


@pytest.mark.asyncio
async def test_chat_revision_sends_the_current_draft_and_message(monkeypatch):
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"] = prompt
        return _answer(body="Bản ngắn hơn")

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    out = await post_writer.write_post({}, current={"body": "Bản cũ dài", "hashtags": []},
                                       message="viết ngắn lại, thêm 1 ảnh",
                                       history=[{"role": "user", "text": "viết bài review"}])
    assert "CURRENT DRAFT" in seen["prompt"] and "Bản cũ dài" in seen["prompt"]
    assert "viết ngắn lại" in seen["prompt"] and "SELLER: viết bài review" in seen["prompt"]
    assert out["body"] == "Bản ngắn hơn"


@pytest.mark.asyncio
async def test_an_empty_post_is_an_error(monkeypatch):
    async def fake_llm(*a, **k):
        return _answer(body="  ")

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    with pytest.raises(post_writer.PostWriterError):
        await post_writer.write_post({"kind": "review"})


def test_write_route_and_library(client, monkeypatch):
    async def fake_llm(*a, **k):
        return _answer()

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    opts = client.get("/api/posts/options").json()
    assert {k["key"] for k in opts["kinds"]} >= {"discussion", "review", "minigame"}
    board = client.post("/api/boards", json={"name": "Clip test"}).json()
    client.post("/api/nodes", json={"board_id": board["id"], "type": "video", "data": {"narration": "Câu thoại 1"}})
    ch = client.post("/api/channels", json={"name": "Page test", "platforms": ["facebook"]}).json()
    # no channel / page picked: refused before any token is spent
    r = client.post("/api/posts/write", json={"brief": {"kind": "review"}, "board_id": board["id"]})
    assert r.status_code == 400 and "kênh" in r.json()["detail"]
    r = client.post("/api/posts/write", json={"brief": {"kind": "review"}, "channel_id": 999})
    assert r.status_code == 400
    r = client.post("/api/posts/write", json={"brief": {"kind": "review", "images": 1}, "board_id": board["id"], "channel_id": ch["id"]})
    assert r.status_code == 200 and r.json()["post"]["image_prompts"] == ["A plate of crispy scorched rice"]

    saved = client.post("/api/posts", json={"kind": "review", "title": "T", "body": "Nội dung", "hashtags": "#a #b",
                                            "board_id": board["id"], "images": ["m1"]}).json()
    assert client.patch(f"/api/posts/{saved['id']}", json={"body": "Sửa rồi"}).json()["body"] == "Sửa rồi"
    rows = client.get("/api/posts", params={"board_id": board["id"]}).json()
    assert len(rows) == 1 and rows[0]["images"] == ["m1"] and rows[0]["hashtags"] == "#a #b"
    assert client.post("/api/posts", json={"body": " "}).status_code == 400
    assert client.delete(f"/api/posts/{saved['id']}").json() == {"ok": True}
    assert client.get("/api/posts").json() == [] or all(p["id"] != saved["id"] for p in client.get("/api/posts").json())


@pytest.mark.asyncio
async def test_a_text_revision_keeps_the_image_prompts_unless_images_are_mentioned(monkeypatch):
    async def fake_llm(*a, **k):
        return _answer(image_prompts=[])

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    current = {"body": "Bản cũ", "hashtags": [], "image_prompts": ["A desk with snacks"]}
    out = await post_writer.write_post({}, current=current, message="ngắn hơn")
    assert out["image_prompts"] == ["A desk with snacks"]
    out = await post_writer.write_post({}, current=current, message="bỏ ảnh đi")
    assert out["image_prompts"] == []


def test_series_episodes_feed_the_next_one(client, monkeypatch):
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"] = prompt
        return _answer(body="Tập tiếp theo")

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    assert client.get("/api/posts/series").json() == []
    ch = client.post("/api/channels", json={"name": "Page test", "platforms": ["facebook"]}).json()["id"]
    r = client.post("/api/posts/write", json={"brief": {}, "series": "Chuyện nhà chuối", "channel_id": ch}).json()
    assert r["series"] == "Chuyện nhà chuối" and r["episode"] == 1
    assert "EPISODE 1" in seen["prompt"] and "first episode" in seen["prompt"] and "Câu chuyện nhiều kỳ" in seen["prompt"]
    client.post("/api/posts", json={"body": "Tập 1: mình mua chuối", "series": "Chuyện nhà chuối", "episode": 1, "kind": "serial"})
    client.post("/api/posts", json={"body": "Tập 2: chuối chín hết", "series": "Chuyện nhà chuối", "episode": 2, "kind": "serial"})
    r = client.post("/api/posts/write", json={"brief": {"kind": "serial"}, "series": "Chuyện nhà chuối", "channel_id": ch}).json()
    assert r["episode"] == 3
    p = seen["prompt"]
    assert "EPISODE 3" in p and "Tập 1: Tập 1: mình mua chuối" in p and "Tập 2: Tập 2: chuối chín hết" in p and "hook for episode 4" in p
    s = client.get("/api/posts/series").json()
    assert s == [{"name": "Chuyện nhà chuối", "episodes": 2, "last_episode": 2, "last_title": "", "channel_id": None}]
    assert client.get("/api/posts").json()[0]["series"] == "Chuyện nhà chuối"


@pytest.mark.asyncio
async def test_revise_image_prompt_keeps_the_scene_and_applies_the_wish(monkeypatch):
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"], seen["system"] = prompt, system_prompt
        return '"Photorealistic cozy living room, a young Vietnamese woman turning to her husband with a pregnancy test, warm light, no text"'

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    out = await post_writer.revise_image_prompt("Photorealistic cozy living room, woman shows test, no text", "quay về phía chồng, ánh sáng ấm hơn")
    assert out.startswith("Photorealistic") and '"' not in out
    assert "CURRENT PROMPT" in seen["prompt"] and "quay về phía chồng" in seen["prompt"]
    with pytest.raises(post_writer.PostWriterError):
        await post_writer.revise_image_prompt("x", "   ")


def test_revise_image_route(client, monkeypatch):
    async def fake_llm(*a, **k):
        return "A brighter version of the same scene, no text, no logos"

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    r = client.post("/api/posts/revise-image", json={"prompt": "A scene", "request": "sáng hơn"})
    assert r.status_code == 200 and r.json()["prompt"].startswith("A brighter")
    assert client.post("/api/posts/revise-image", json={"prompt": "A scene", "request": ""}).status_code == 422


@pytest.mark.asyncio
async def test_no_call_to_action_by_default_and_reach_options_reach_the_prompt(monkeypatch):
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"], seen["system"] = prompt, system_prompt
        return _answer()

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    await post_writer.write_post({"kind": "tips"})
    p = seen["prompt"]
    assert "CALL TO ACTION: no call to action" in p and "REACH" not in p and "Opening line" not in p
    assert "engagement bait" in seen["system"]
    await post_writer.write_post({"kind": "tips", "cta": "comment", "hook": "number", "format": "list", "emoji": "few",
                                  "boosts": ["save", "open_loop", "bogus"]})
    p = seen["prompt"]
    assert "CALL TO ACTION: invite readers to comment" in p
    assert "Opening line: open with a number promise" in p and "Layout: the core as a scannable list" in p
    assert "Emoji: at most 2 emoji" in p
    assert "REACH (do all of these): make part of it a mini checklist" in p and "tease something early" in p


def test_options_list_the_reach_choices(client):
    o = client.get("/api/posts/options").json()
    assert o["ctas"][0]["key"] == "none"
    assert {"hooks", "formats", "boosts", "emojis"} <= set(o)
    assert o["hooks"][0]["key"] == "auto" and any(b["key"] == "save" for b in o["boosts"])


def test_write_batch_side_by_side_and_as_a_story(client, monkeypatch):
    seen = []

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen.append(prompt)
        n = len(seen)
        return _answer(title=f"Bài {n}", body=f"Nội dung {n}")

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    ch = client.post("/api/channels", json={"name": "Page", "platforms": ["facebook"]}).json()["id"]
    assert client.post("/api/posts/write-batch", json={"brief": {}, "n": 3}).status_code == 400  # no channel
    r = client.post("/api/posts/write-batch", json={"brief": {"kind": "tips"}, "n": 3, "channel_id": ch})
    assert r.status_code == 200, r.text
    posts = r.json()["posts"]
    assert len(posts) == 3 and all(p["id"] and p["channel_id"] == ch for p in posts)
    assert all("BATCH: this is post" in p for p in seen)
    hooks = {p["brief"]["hook"] for p in posts}
    assert len(hooks) == 3  # each opens differently
    assert len(client.get("/api/posts").json()) == 3
    # a story: consecutive episodes, each reading the one before
    seen.clear()
    r = client.post("/api/posts/write-batch", json={"brief": {}, "n": 3, "channel_id": ch, "series": "Chuyện bầu"}).json()
    eps = [(p["series"], p["episode"]) for p in r["posts"]]
    assert eps == [("Chuyện bầu", 1), ("Chuyện bầu", 2), ("Chuyện bầu", 3)]
    assert "EPISODE 1" in seen[0] and "EPISODE 2" in seen[1] and "Nội dung 1" in seen[1] and "Nội dung 2" in seen[2]
    # continuing the same series later starts at episode 4
    r = client.post("/api/posts/write-batch", json={"brief": {}, "n": 2, "channel_id": ch, "series": "Chuyện bầu"}).json()
    assert [p["episode"] for p in r["posts"]] == [4, 5]
    assert client.post("/api/posts/write-batch", json={"brief": {}, "n": 6, "channel_id": ch}).status_code == 422


def test_series_list_is_per_channel_and_never_merges_two_pages(client):
    a = client.post("/api/channels", json={"name": "Trang A", "platforms": ["facebook"]}).json()["id"]
    b = client.post("/api/channels", json={"name": "Trang B", "platforms": ["facebook"]}).json()["id"]
    for ch, ep in ((a, 1), (a, 2), (b, 1)):
        client.post("/api/posts", json={"body": "x", "series": "Nhật ký", "episode": ep, "channel_id": ch})
    client.post("/api/posts", json={"body": "y", "series": "Hệ mặt trời", "episode": 1, "channel_id": b})
    everything = client.get("/api/posts/series").json()
    assert sorted((r["name"], r["channel_id"], r["episodes"]) for r in everything) == [
        ("Hệ mặt trời", b, 1), ("Nhật ký", a, 2), ("Nhật ký", b, 1)]
    only_a = client.get(f"/api/posts/series?channel_id={a}").json()
    assert [(r["name"], r["episodes"]) for r in only_a] == [("Nhật ký", 2)]
