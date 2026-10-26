"""Channels: CRUD, counts, the brainstorm profile, and how a channel steers the post writer."""
import json

import pytest

from flowboard.db import ensure_post_channel_column
from flowboard.services import channels as svc
from flowboard.services import post_writer

PROFILE = {
    "positioning": "Trang ăn vặt cho dân văn phòng", "audience": "Dân văn phòng 22-35", "voice": "Thân thiện, xưng mình",
    "pillars": [{"name": "Ăn vặt 3h chiều", "note": "món nhanh"}, "Review thật"],
    "post_mix": "Hỏi ý kiến + review xen kẽ", "do": ["Hỏi cuối bài"], "dont": ["Không bịa giá"],
    "hashtags": ["anvat", "#comchay", "#anvat"], "ideas": ["Hỏi món 3h chiều"], "summary": "Trang ăn vặt văn phòng, giọng bạn bè.",
}


def _channel(client, **over):
    body = {"name": "Bếp Ăn Vặt", "platforms": ["facebook", "tiktok", "bogus"], "category": "food",
            "description": "Bán cơm cháy, bánh tráng", "audience": "dân văn phòng", "goal": "tương tác"}
    body.update(over)
    return client.post("/api/channels", json=body).json()


def test_crud_counts_and_delete_unlinks_posts(client):
    opts = client.get("/api/channels/options").json()
    assert {p["key"] for p in opts["platforms"]} >= {"facebook", "tiktok"} and opts["brainstorm_min_posts"] == 3
    c = _channel(client)
    assert c["platforms"] == ["facebook", "tiktok"] and c["posts"] == 0 and c["brainstorm_due"] is False
    assert client.post("/api/channels", json={"name": " "}).status_code == 400

    board = client.post("/api/boards/from-template", json={"template_id": "fast_food_ad", "channel_id": c["id"]}).json()
    assert board["data"]["quicktool"]["channel_id"] == c["id"]
    for i in range(3):
        client.post("/api/posts", json={"body": f"Bài {i}", "channel_id": c["id"]})
    row = client.get(f"/api/channels/{c['id']}").json()
    assert row["posts"] == 3 and row["clips"] == 1 and row["brainstorm_due"] is True
    assert client.get("/api/posts", params={"channel_id": c["id"]}).json()[0]["channel_id"] == c["id"]

    upd = client.patch(f"/api/channels/{c['id']}", json={"name": "Bếp Mới", "category": "weird"}).json()
    assert upd["name"] == "Bếp Mới" and upd["category"] == "other"
    assert client.delete(f"/api/channels/{c['id']}").json() == {"ok": True}
    assert client.get("/api/channels").json() == []
    assert all(p["channel_id"] is None for p in client.get("/api/posts").json())
    assert client.get(f"/api/boards/{board['id']}").json()["board"]["data"]["quicktool"]["channel_id"] is None


def test_brainstorm_reads_posts_and_clips_and_sets_due_flags(client, monkeypatch):
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"] = prompt
        return json.dumps(PROFILE, ensure_ascii=False)

    monkeypatch.setattr(svc, "run_llm", fake_llm)
    c = _channel(client)
    assert client.post(f"/api/channels/{c['id']}/brainstorm").status_code == 200  # description alone is material
    board = client.post("/api/boards/from-template", json={"template_id": "fast_food_ad", "channel_id": c["id"]}).json()
    video = next(n for n in client.get(f"/api/boards/{board['id']}").json()["nodes"] if n["type"] == "video")
    client.patch(f"/api/nodes/{video['id']}", json={"data": {"narration": "Giòn rụm luôn"}})
    for i in range(3):
        client.post("/api/posts", json={"body": f"Cơm cháy bài {i}", "hashtags": "#comchay", "kind": "review", "channel_id": c["id"]})
    row = client.post(f"/api/channels/{c['id']}/brainstorm").json()
    p = seen["prompt"]
    assert "Bếp Ăn Vặt" in p and "Facebook, TikTok" in p and "Cơm cháy bài 2" in p and "Giòn rụm luôn" in p
    assert "PREVIOUS DIRECTION" in p  # second run refreshes the first
    prof = row["brainstorm"]
    assert prof["post_count"] == 3 and prof["pillars"][1] == {"name": "Review thật", "note": ""}
    assert prof["hashtags"] == ["#anvat", "#comchay"]
    assert row["brainstorm_due"] is False
    assert svc.brainstorm_due(row, 8) is True  # 5 posts later it is stale


def test_brainstorm_errors(client, monkeypatch):
    async def bad(*a, **k):
        return "not json"

    monkeypatch.setattr(svc, "run_llm", bad)
    c = client.post("/api/channels", json={"name": "Trống"}).json()
    r = client.post(f"/api/channels/{c['id']}/brainstorm")
    assert r.status_code == 400 and "chưa có bài viết" in r.json()["detail"].lower()
    client.post("/api/posts", json={"body": "x", "channel_id": c["id"]})
    assert client.post(f"/api/channels/{c['id']}/brainstorm").status_code == 400
    assert client.post("/api/channels/999/brainstorm").status_code == 404


@pytest.mark.asyncio
async def test_writer_follows_the_channel_direction_and_platform(monkeypatch):
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"] = prompt
        return json.dumps({"reply": "ok", "body": "Bài theo kênh", "hashtags": [], "image_prompts": []})

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    channel = {"id": 1, "name": "Bếp Ăn Vặt", "platforms": ["tiktok", "facebook"], "category": "food",
               "description": "Bán cơm cháy", "brainstorm": {**PROFILE, "hashtags": ["#anvat"]}}
    await post_writer.write_post({"kind": "review"}, channel=channel)
    p = seen["prompt"]
    assert "TikTok caption" in p  # first platform of the channel
    assert "PAGE DIRECTION" in p and "Ăn vặt 3h chiều (món nhanh)" in p and "Don't: Không bịa giá" in p
    assert "House hashtags: #anvat" in p
    await post_writer.write_post({"kind": "review", "platform": "instagram"}, channel=channel)
    assert "Instagram caption" in seen["prompt"]  # the brief's platform wins
    await post_writer.write_post({"kind": "review"})
    assert "Facebook post" in seen["prompt"] and "CHANNEL" not in seen["prompt"]


def test_write_route_uses_the_clip_channel(client, monkeypatch):
    async def fake_llm(*a, **k):
        return json.dumps({"reply": "ok", "body": "Bài", "hashtags": [], "image_prompts": []})

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    c = _channel(client)
    board = client.post("/api/boards/from-template", json={"template_id": "fast_food_ad", "channel_id": c["id"]}).json()
    r = client.post("/api/posts/write", json={"brief": {}, "board_id": board["id"]}).json()
    assert r["channel_id"] == c["id"]
    # neither the request nor the clip names a channel → refused
    assert client.post("/api/posts/write", json={"brief": {}}).status_code == 400


def test_post_channel_column_migration(tmp_path):
    from sqlalchemy import create_engine, inspect

    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.connect() as conn:
        conn.exec_driver_sql("CREATE TABLE post (id INTEGER PRIMARY KEY, body VARCHAR)")
        conn.commit()
    assert ensure_post_channel_column(eng) is True
    assert ensure_post_channel_column(eng) is False
    with eng.connect() as conn:
        assert "channel_id" in {c["name"] for c in inspect(conn).get_columns("post")}


def test_channel_takes_up_to_three_categories(client):
    r = client.post("/api/channels", json={"name": "Tò mò", "categories": ["creator", "science", "bogus", "creator", "shop", "other"]}).json()
    assert r["categories"] == ["creator", "science", "shop"] and r["category"] == "creator"
    assert client.get("/api/channels/options").json()["max_categories"] == 3
    legacy = client.post("/api/channels", json={"name": "Cũ", "category": "food"}).json()
    assert legacy["categories"] == ["food"] and legacy["category"] == "food"
    block = svc.channel_block(r)
    assert "Business / page categories: Nhà sáng tạo nội dung số, Khoa học & công nghệ, Cửa hàng / bán lẻ online" in block
    upd = client.patch(f"/api/channels/{r['id']}", json={"categories": []}).json()
    assert upd["categories"] == [] and upd["category"] == ""


def test_channel_categories_migration_seeds_from_category(tmp_path):
    from sqlalchemy import create_engine, text

    from flowboard.db import ensure_channel_categories_column

    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.connect() as conn:
        conn.exec_driver_sql("CREATE TABLE channel (id INTEGER PRIMARY KEY, name VARCHAR, category VARCHAR)")
        conn.exec_driver_sql("INSERT INTO channel (name, category) VALUES ('a', 'food'), ('b', '')")
        conn.commit()
    assert ensure_channel_categories_column(eng) is True
    assert ensure_channel_categories_column(eng) is False
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT category, categories FROM channel ORDER BY id")).fetchall()
    assert [tuple(r) for r in rows] == [("food", '["food"]'), ("", "[]")]
