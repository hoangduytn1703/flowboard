"""Channel link: validation, reading the page through the extension, the review, and how it feeds the writer."""
import json

import pytest

from flowboard.services import channel_page, channels as svc

REVIEW = {
    "page_name": "Bầu bì không khó", "followers": "16K", "summary": "Page mẹ bầu, đăng video phụ đề vàng.",
    "score": 7.4, "criteria": [{"name": "Độ đều đặn", "score": 8, "note": "ngày 1–2 bài"}, {"bad": 1}],
    "strengths": ["Chủ đề rõ"], "weaknesses": ["Ít kêu gọi mua"], "suggestions": ["Thêm câu hỏi cuối bài", "Ghim link"],
    "house_style": "Câu ngắn, xưng 'các mẹ', 1–2 emoji 🥰, video dọc phụ đề hộp vàng.",
    "sample_hooks": ["Vợ iu nhà các ông có đủ mấy điều sau ko 🥰"], "posts_seen": 6,
}


class _FakeClient:
    def __init__(self, data=None, version="0.6.0", connected=True, error=None):
        self.connected, self.extension_version = connected, version
        self._data, self._error, self.sent = data, error, []

    async def _send(self, method, params, timeout=None):
        self.sent.append((method, params))
        if self._error:
            return {"error": self._error}
        return {"data": json.dumps(self._data)}


def test_link_validation(client):
    r = client.post("/api/channels", json={"name": "Bầu bì", "link": "xem page https://www.facebook.com/profile.php?id=61570744672536 nha"})
    assert r.status_code == 201 and r.json()["link"] == "https://www.facebook.com/profile.php?id=61570744672536"
    assert client.post("/api/channels", json={"name": "X", "link": "https://example.com/shop"}).status_code == 400
    cid = r.json()["id"]
    assert client.post(f"/api/channels/{cid + 99}/review").status_code == 404
    no_link = client.post("/api/channels", json={"name": "Không link"}).json()
    r = client.post(f"/api/channels/{no_link['id']}/review")
    assert r.status_code == 400 and "chưa có link" in r.json()["detail"]


@pytest.mark.asyncio
async def test_read_page_through_the_extension(monkeypatch):
    import flowboard.services.flow_client as fc

    fake = _FakeClient({"url": "https://www.facebook.com/x", "title": "Bầu bì không khó", "text": "Bài viết\n" * 80})
    monkeypatch.setattr(fc, "get_flow_client", lambda: fake)
    page = await channel_page.read_page("https://www.facebook.com/x")
    assert page["via"] == "chrome" and page["title"] == "Bầu bì không khó" and fake.sent[0][0] == "read_channel"
    with pytest.raises(channel_page.ChannelPageError, match="Facebook, TikTok"):
        await channel_page.read_page("https://shopee.vn/x")


@pytest.mark.asyncio
async def test_old_extension_or_login_wall_give_clear_errors(monkeypatch):
    import flowboard.services.flow_client as fc
    import flowboard.services.product_link as pl

    async def no_fetch(url):
        raise RuntimeError("blocked")

    monkeypatch.setattr(pl, "fetch_page", no_fetch)
    monkeypatch.setattr(fc, "get_flow_client", lambda: _FakeClient(version="0.5.0"))
    with pytest.raises(channel_page.ChannelPageError, match="0.6.0"):
        await channel_page.read_page("https://www.facebook.com/x")
    monkeypatch.setattr(fc, "get_flow_client", lambda: _FakeClient({"text": "Log in to Facebook\nEmail\nPassword"}))
    with pytest.raises(channel_page.ChannelPageError, match="đăng nhập"):
        await channel_page.read_page("https://www.facebook.com/x")


def test_review_route_saves_and_feeds_the_writer(client, monkeypatch):
    seen = {}

    async def fake_read(url):
        return {"url": url, "title": "Bầu bì không khó", "description": "", "text": "Vợ iu nhà các ông…", "via": "chrome"}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"] = prompt
        return "```json\n" + json.dumps(REVIEW, ensure_ascii=False) + "\n```"

    monkeypatch.setattr(channel_page, "read_page", fake_read)
    monkeypatch.setattr(channel_page, "run_llm", fake_llm)
    c = client.post("/api/channels", json={"name": "Bầu bì", "category": "mom_baby", "goal": "bán đai bầu",
                                           "link": "https://www.facebook.com/bau"}).json()
    row = client.post(f"/api/channels/{c['id']}/review").json()
    rv = row["page_review"]
    assert "bán đai bầu" in seen["prompt"] and "Vợ iu nhà các ông" in seen["prompt"]
    assert rv["score"] == 7 and rv["criteria"] == [{"name": "Độ đều đặn", "score": 8, "note": "ngày 1–2 bài"}]
    assert rv["via"] == "chrome" and rv["posts_seen"] == 6 and rv["url"] == "https://www.facebook.com/bau"
    block = svc.channel_block(row)
    assert "Page link: https://www.facebook.com/bau" in block and "match this" in block and "Vợ iu nhà các ông" in block
    # a channel with only a page review can be brainstormed
    assert svc.brainstorm_due(row, 0) is False
    # changing the link drops the old review
    row = client.patch(f"/api/channels/{c['id']}", json={"link": "https://www.tiktok.com/@bau"}).json()
    assert row["page_review"] is None and row["link"] == "https://www.tiktok.com/@bau"


def test_channel_link_migration(tmp_path):
    from sqlalchemy import create_engine, inspect

    from flowboard.db import ensure_channel_link_columns

    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.connect() as conn:
        conn.exec_driver_sql("CREATE TABLE channel (id INTEGER PRIMARY KEY, name VARCHAR)")
        conn.commit()
    assert ensure_channel_link_columns(eng) is True
    assert ensure_channel_link_columns(eng) is False
    with eng.connect() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("channel")}
    assert {"link", "page_review"} <= cols


def test_clean_text_drops_facebook_ui_noise():
    raw = "Bầu bì không khó\nFacebook\nFacebook\n\n·\nVợ iu nhà các ông\nVợ iu nhà các ông\n621\nFacebook"
    assert channel_page.clean_text(raw) == "Bầu bì không khó\nVợ iu nhà các ông\n621"


def test_normalize_link_accepts_http_and_bare_hosts(client):
    assert channel_page.normalize_link("http://tiktok.com/goodbOi95") == "https://tiktok.com/goodbOi95"
    assert channel_page.normalize_link("www.tiktok.com/@goodboi95/") == "https://www.tiktok.com/@goodboi95"
    assert channel_page.normalize_link("xem page https://www.facebook.com/bau nha") == "https://www.facebook.com/bau"
    assert channel_page.link_allowed("https://tiktok.com/goodbOi95") and not channel_page.link_allowed("https://example.com/x")
    r = client.post("/api/channels", json={"name": "TikTok", "platforms": ["tiktok"], "link": "http://tiktok.com/goodbOi95"})
    assert r.status_code == 201 and r.json()["link"] == "https://tiktok.com/goodbOi95"
