"""Đồng bộ từ Facebook: a Page's own posts read back — made by hand → on the calendar, matched to saved posts."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from flowboard.services import facebook_publish, fb_sync


def _fb_time(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class _Page:
    """A fake Graph API with one page: /me/accounts (to connect it) and /published_posts."""

    def __init__(self, posts):
        self.posts, self.fail, self.calls = posts, False, []
        self.reels: list = []
        self.no_insights = False

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if path.endswith("/me"):
            return httpx.Response(200, json={"id": "u1", "name": "Duy"})
        if path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": [{"id": "page9", "name": "Trang test", "access_token": "PAGE_TOKEN_xxxxxxxxxxxx"}]})
        if path.endswith("/page9/published_posts"):
            if self.fail:
                return httpx.Response(400, json={"error": {"message": "Error validating access token", "code": 190}})
            if self.no_insights and "insights" in request.url.params.get("fields", ""):
                return httpx.Response(400, json={"error": {"message": "(#10) This endpoint requires the 'read_insights' permission", "code": 10}})
            if "insights" not in request.url.params.get("fields", ""):
                return httpx.Response(200, json={"data": [{k: v for k, v in x.items() if k != "insights"} for x in self.posts]})
            return httpx.Response(200, json={"data": self.posts})
        if path.endswith("/page9/video_reels"):
            return httpx.Response(200, json={"data": self.reels})
        return httpx.Response(404, json={"error": {"message": "no", "code": 803}})


@pytest.fixture
def page(monkeypatch):
    def install(posts):
        fake = _Page(posts)
        real = httpx.AsyncClient

        def client(*a, **k):
            k["transport"] = httpx.MockTransport(fake.handler)
            return real(*a, **k)

        monkeypatch.setattr(facebook_publish.httpx, "AsyncClient", client)
        return fake
    return install


def _connected_channel(client, name="Chúng ta hay tò mò"):
    ch = client.post("/api/channels", json={"name": name, "platforms": ["facebook"]}).json()
    r = client.post(f"/api/channels/{ch['id']}/facebook", json={"token": "USER_TOKEN_yyyyyyyyyyyyyy", "page_id": "page9"})
    assert r.status_code == 200, r.text
    return ch


def _raw(fb_id, when, message, *, reel_id=None, photo=True):
    att = ({"media_type": "video", "type": "video_inline", "target": {"id": reel_id}, "url": f"https://www.facebook.com/reel/{reel_id}/"}
           if reel_id else {"media_type": "photo", "type": "photo", "target": {"id": f"ph_{fb_id}"}, "url": "https://www.facebook.com/photo.php?fbid=1"})
    return {"id": fb_id, "created_time": _fb_time(when), "message": message, "permalink_url": f"https://www.facebook.com/{fb_id}",
            "status_type": "added_video" if reel_id else "added_photos", "full_picture": "https://scontent.example/p.jpg" if photo else None,
            "attachments": {"data": [att]}}


def test_hand_made_posts_show_up_and_tool_posts_are_not_listed_twice(client, page):
    now = datetime.now(timezone.utc)
    body = "Tập 7 | Sao Thổ và chiếc vành đai đang biến mất. Tập trước mình kể về cơn bão trên Sao Mộc, hôm nay mình lật sang trang mới."
    fake = page([])
    ch = _connected_channel(client)
    other = client.post("/api/channels", json={"name": "Trang khác", "platforms": ["facebook"]}).json()
    saved = client.post("/api/posts", json={"body": body, "hashtags": "#vutru #saotho", "channel_id": ch["id"], "title": "Tập 7"}).json()
    loose = client.post("/api/posts", json={"body": "Một bài hoàn toàn khác về cách chọn kính thiên văn cho người mới bắt đầu", "channel_id": ch["id"]}).json()
    # the tool published one post and one Reel itself
    from flowboard.db import get_session
    from flowboard.db.models import Schedule
    with get_session() as s:
        for fid in ("page9_tool", "reel777"):
            s.add(Schedule(kind="post", post_id=loose["id"], channel_id=ch["id"], scheduled_at=now - timedelta(days=1),
                           status="posted", result={"by": "facebook", "post_id": fid}))
        s.commit()
    # the saved post is also planned on this page (would go out twice) and on another page (left alone)
    later = _iso(now + timedelta(days=2))
    planned = client.post("/api/schedule", json={"kind": "post", "post_id": saved["id"], "at": later}).json()
    elsewhere = client.post("/api/schedule", json={"kind": "post", "post_id": saved["id"], "channel_id": other["id"], "at": later}).json()
    fake.posts = [
        # pasted from the tool with a word changed and the hashtags moved
        _raw("page9_hand", now - timedelta(minutes=30), "#saotho " + body.replace("hôm nay", "bữa nay") + "\n#vutru"),
        _raw("page9_other", now - timedelta(hours=3), "Ad đang cố gắng xây dựng nội dung kênh, mọi người ủng hộ nha ❤️"),
        _raw("page9_tool", now - timedelta(days=1), "đăng bằng tool"),
        _raw("page9_reelpost", now - timedelta(days=1), "Reel bằng tool", reel_id="reel777"),
        _raw("page9_handreel", now - timedelta(days=2), "Rơi vào Kepler-452b — Hôm nay bạn đi đâu?", reel_id="reel888"),
    ]
    r = client.post("/api/schedule/facebook/sync", json={})
    assert r.status_code == 200, r.text
    out = r.json()["channels"][0]
    assert (out["fetched"], out["manual"], out["matched"], out["skipped_slots"]) == (5, 3, 1, 1)
    items = client.get("/api/schedule/facebook", params={"from": _iso(now - timedelta(days=7)), "to": _iso(now + timedelta(days=1))}).json()
    by_id = {x["fb_id"]: x for x in items["items"]}
    assert set(by_id) == {"page9_hand", "page9_other", "page9_handreel"}  # the tool's own two are not listed again
    assert by_id["page9_hand"]["post_id"] == saved["id"] and by_id["page9_hand"]["post_title"] == "Tập 7"
    assert by_id["page9_other"]["post_id"] is None and by_id["page9_handreel"]["reel"]
    assert items["channels"][0]["manual"] == 3 and items["channels"][0]["at"]
    # Bài đã lưu: the saved post carries when it went up by hand; the other one does not
    rows = {p["id"]: p for p in client.get("/api/posts").json()}
    assert rows[saved["id"]]["fb_manual"]["link"] == "https://www.facebook.com/page9_hand"
    assert rows[loose["id"]]["fb_manual"] is None
    # its planned slot on this page is skipped (never published twice); the other page's stays
    slots = {x["id"]: x for x in client.get("/api/schedule", params={"from": _iso(now), "to": _iso(now + timedelta(days=5))}).json()["items"]}
    assert slots[planned["id"]]["status"] == "skipped" and "đăng tay" in slots[planned["id"]]["note"]
    assert slots[elsewhere["id"]]["status"] == "planned"
    # deleted on Facebook → gone here too; a recent sync is not repeated when a page opens
    fake.posts = fake.posts[1:]
    again = client.post("/api/schedule/facebook/sync", json={"channel_id": ch["id"]}).json()["channels"][0]
    assert again["removed"] == 1 and again["matched"] == 0
    assert {p["id"]: p for p in client.get("/api/posts").json()}[saved["id"]]["fb_manual"] is None
    assert client.post("/api/schedule/facebook/sync", json={"max_age": 600}).json()["channels"] == []


def test_a_bad_token_is_reported_and_kept_for_the_page(client, page):
    fake = page([])
    ch = _connected_channel(client)
    fake.fail = True
    r = client.post("/api/schedule/facebook/sync", json={"channel_id": ch["id"]})
    assert r.status_code == 400 and "Đọc bài của Page" in r.json()["detail"]
    st = client.get("/api/schedule/facebook/status").json()["channels"][0]
    assert st["error"] and st["at"]
    # syncing every page reports it per page instead of failing the call
    out = client.post("/api/schedule/facebook/sync", json={}).json()
    assert out["channels"][0]["error"]


def test_matching_keeps_the_original_not_a_later_copy():
    went_up = datetime(2026, 10, 29, 16, 0, tzinfo=timezone.utc)
    text = fb_sync.norm_text("Hôm nay mình kể chuyện Sao Thổ và chiếc vành đai đẹp nhất hệ Mặt Trời đang mỏng dần theo thời gian")
    original = (10, text, went_up - timedelta(days=1))
    copy_made_later = (12, text, went_up + timedelta(days=1))
    older_twin = (9, text, went_up - timedelta(days=2))
    msg = "Hôm nay mình kể chuyện Sao Thổ và chiếc vành đai đẹp nhất hệ Mặt Trời đang mỏng dần theo thời gian #vutru"
    assert fb_sync.best_match(msg, went_up, [original, copy_made_later]) == 10
    assert fb_sync.best_match(msg, went_up, [original, older_twin]) == 9  # equally good → the oldest
    assert fb_sync.best_match(msg, went_up, [original, older_twin], keep=10) == 10  # the link does not jump
    assert fb_sync.best_match("❤️", went_up, [original]) is None
    assert fb_sync.best_match("Một chuyện chẳng liên quan gì đến vũ trụ cả, chỉ là bữa trưa hôm nay", went_up, [original]) is None


def _with_numbers(raw, *, likes=0, comments=0, shares=0, views=None, viewers=None):
    raw = {**raw, "reactions": {"data": [], "summary": {"total_count": likes}}, "comments": {"data": [], "summary": {"total_count": comments}}}
    if shares:
        raw["shares"] = {"count": shares}
    if views is not None:
        raw["insights"] = {"data": [
            {"name": "post_media_view", "period": "lifetime", "values": [{"value": views}]},
            {"name": "post_total_media_view_unique", "period": "lifetime", "values": [{"value": viewers}]},
            {"name": "post_total_media_view_unique", "period": "day", "values": [{"value": 0}, {"value": 0}]},
            {"name": "post_clicks", "period": "lifetime", "values": [{"value": 2}]},
        ]}
    return raw


def test_numbers_are_read_back_for_posts_and_reels(client, page):
    now = datetime.now(timezone.utc)
    fake = page([])
    ch = _connected_channel(client)
    saved = client.post("/api/posts", json={"body": "Bài tool đăng có ảnh", "channel_id": ch["id"]}).json()
    from flowboard.db import get_session
    from flowboard.db.models import Schedule
    with get_session() as s:
        s.add(Schedule(kind="post", post_id=saved["id"], channel_id=ch["id"], scheduled_at=now - timedelta(days=1),
                       status="posted", result={"by": "facebook", "post_id": "page9_tool"}))
        s.commit()
    fake.posts = [
        _with_numbers(_raw("page9_tool", now - timedelta(days=1), "Bài tool đăng có ảnh"), likes=3, comments=1, shares=2, views=120, viewers=80),
        _with_numbers(_raw("page9_reel", now - timedelta(hours=5), "Hôm nay bạn đi đâu? Rơi xuống K2-18b", reel_id="v55"), likes=1, views=33, viewers=20),
    ]
    graph = {str(i): round(1 - i / 40, 4) for i in range(41)}
    fake.reels = [{"id": "v55", "length": 62.4, "video_insights": {"data": [
        {"name": "fb_reels_total_plays", "period": "lifetime", "values": [{"value": 33}]},
        {"name": "fb_reels_replay_count", "period": "lifetime", "values": [{"value": 2}]},
        {"name": "post_video_avg_time_watched", "period": "lifetime", "values": [{"value": 15540}]},
        {"name": "post_video_view_time", "period": "lifetime", "values": [{"value": 481750}]},
        {"name": "post_video_followers", "period": "lifetime", "values": [{"value": 1}]},
        {"name": "post_video_retention_graph", "period": "lifetime", "values": [{"value": graph}]},
    ]}}]
    out = client.post("/api/schedule/facebook/sync", json={}).json()["channels"][0]
    assert out["stats_error"] is None
    # the tool's own post: numbers on its calendar slot and on the saved post
    slots = client.get("/api/schedule", params={"from": _iso(now - timedelta(days=3)), "to": _iso(now)}).json()["items"]
    st = next(x for x in slots if x["status"] == "posted")["stats"]
    assert (st["views"], st["viewers"], st["reactions"], st["comments"], st["shares"], st["clicks"]) == (120, 80, 3, 1, 2, 2)
    assert {p["id"]: p for p in client.get("/api/posts").json()}[saved["id"]]["fb_stats"]["views"] == 120
    # a Reel made by hand: plays, watch time, retention (41 points in order) on its calendar card
    hand = client.get("/api/schedule/facebook", params={"from": _iso(now - timedelta(days=1)), "to": _iso(now + timedelta(hours=1))}).json()["items"]
    rs = next(x for x in hand if x["fb_id"] == "page9_reel")["stats"]
    assert (rs["plays"], rs["replays"], rs["avg_watch_s"], rs["watch_time_s"], rs["followers"], rs["length_s"]) == (33, 2, 15.5, 482, 1, 62.4)
    assert len(rs["retention"]) == 41 and rs["retention"][0] == 1 and rs["retention"][40] == 0 and rs["views"] == 33
    # without read_insights the posts are still read (❤ 💬 ↗ fresh), that is said, and the last views are kept
    fake.no_insights = True
    fake.posts[0]["reactions"]["summary"]["total_count"] = 5
    out = client.post("/api/schedule/facebook/sync", json={"channel_id": ch["id"]}).json()["channels"][0]
    assert out["fetched"] == 2 and "read_insights" in out["stats_error"]
    st = {p["id"]: p for p in client.get("/api/posts").json()}[saved["id"]]["fb_stats"]
    assert st["reactions"] == 5 and st["views"] == 120
