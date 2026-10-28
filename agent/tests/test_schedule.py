"""Lịch đăng: slots, due reminders, golden hours, publishing through a Facebook Page."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from flowboard.services import facebook_publish, scheduler


def _channel(client, **over):
    body = {"name": "Mẹ bầu", "platforms": ["facebook"], "categories": ["mom_baby"]}
    body.update(over)
    return client.post("/api/channels", json=body).json()


def _post(client, channel_id, **over):
    body = {"body": "Bài test", "hashtags": "#a #b", "channel_id": channel_id, "first_comment": "Link đây\nhttps://s.shopee.vn/x"}
    body.update(over)
    return client.post("/api/posts", json=body).json()


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _backdate(slot_id, delta):
    """Move a slot into the past behind the API's back (the API refuses past times)."""
    from flowboard.db import get_session
    from flowboard.db.models import Schedule

    with get_session() as s:
        sc = s.get(Schedule, slot_id)
        sc.scheduled_at = datetime.now(timezone.utc) - delta
        s.add(sc)
        s.commit()


def test_slot_lifecycle_and_due(client):
    ch = _channel(client)
    post = _post(client, ch["id"])
    future = datetime.now(timezone.utc) + timedelta(hours=3)
    r = client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "at": _iso(future)})
    assert r.status_code == 201, r.text
    slot = r.json()
    assert slot["channel_id"] == ch["id"] and slot["status"] == "planned" and not slot["due"]
    assert slot["title"] == "Bài test" and slot["channel"] == "Mẹ bầu" and not slot["fb_connected"]
    # listed in the default window; not due yet
    assert [x["id"] for x in client.get("/api/schedule").json()["items"]] == [slot["id"]]
    assert client.get("/api/schedule/due").json()["items"] == []
    # the API refuses a time in the past (creating or moving)
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    r = client.patch(f"/api/schedule/{slot['id']}", json={"at": _iso(past)})
    assert r.status_code == 400 and "đã qua" in r.json()["detail"]
    assert client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "at": _iso(past)}).status_code == 400
    # time passing makes it due; marking it posted records the time
    _backdate(slot["id"], timedelta(minutes=5))
    moved = client.patch(f"/api/schedule/{slot['id']}", json={"note": "đăng nhóm X"}).json()
    assert moved["due"] and moved["note"] == "đăng nhóm X"
    assert [x["id"] for x in client.get("/api/schedule/due").json()["items"]] == [slot["id"]]
    done = client.patch(f"/api/schedule/{slot['id']}", json={"status": "posted"}).json()
    assert done["status"] == "posted" and done["posted_at"] and not done["due"]
    assert client.get("/api/schedule/due").json()["items"] == []
    assert client.delete(f"/api/schedule/{slot['id']}").json() == {"ok": True}
    assert client.delete(f"/api/schedule/{slot['id']}").status_code == 404


def test_slot_needs_an_existing_item_and_a_channel(client):
    r = client.post("/api/schedule", json={"kind": "post", "post_id": 999, "at": _iso(datetime.now(timezone.utc))})
    assert r.status_code == 400 and "bài viết" in r.json()["detail"].lower()
    post = client.post("/api/posts", json={"body": "không kênh"}).json()
    r = client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "at": _iso(datetime.now(timezone.utc))})
    assert r.status_code == 400 and "kênh" in r.json()["detail"]
    r = client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "at": "ngày hôm qua lúc tám giờ"})
    assert r.status_code == 400
    # a naive time is Vietnam time
    assert scheduler.parse_when("2026-10-27T20:00:00").hour == 13


def test_auto_requires_a_connected_page(client):
    ch = _channel(client)
    post = _post(client, ch["id"])
    r = client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "at": _iso(datetime.now(timezone.utc) + timedelta(hours=1)), "auto": True})
    assert r.status_code == 400 and "Facebook Page" in r.json()["detail"]


def test_golden_hours_skip_taken_slots(client):
    ch = _channel(client, platforms=["facebook", "tiktok"])
    hours = client.get("/api/schedule/hours").json()
    assert hours["facebook"] == ["07:30", "12:00", "20:00"]
    sug = client.get("/api/schedule/suggest", params={"channel_id": ch["id"], "limit": 4}).json()["items"]
    assert len(sug) == 4 and all(x["at"].endswith("Z") and "·" in x["label"] for x in sug)
    # the first suggestion, once booked, is not suggested again
    post = _post(client, ch["id"])
    client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "at": sug[0]["at"]})
    again = client.get("/api/schedule/suggest", params={"channel_id": ch["id"], "limit": 4}).json()["items"]
    assert again[0]["at"] == sug[1]["at"]


class _Graph:
    """A fake Graph API: records calls, answers like Facebook."""

    def __init__(self, pages=None, fail=None):
        self.pages, self.fail, self.calls = pages, fail, []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path, dict(request.url.params)))
        if self.fail and self.fail in path:
            return httpx.Response(400, json={"error": {"message": "boom", "code": 100}})
        if path.endswith("/me"):
            return httpx.Response(200, json={"id": "u1", "name": "Duy"})
        if path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": self.pages or []})
        if path.endswith("/photos"):
            return httpx.Response(200, json={"id": f"ph{len(self.calls)}"})
        if path.endswith("/feed"):
            body = request.content.decode()
            self.calls[-1] = (request.method, path, body)
            return httpx.Response(200, json={"id": "p1_123"})
        if path.endswith("/videos"):
            return httpx.Response(200, json={"id": "v1"})
        if path.endswith("/comments"):
            return httpx.Response(200, json={"id": "c1"})
        if "p1_123" in path or "v1" in path:
            return httpx.Response(200, json={"permalink_url": "https://www.facebook.com/p1_123"})
        return httpx.Response(404, json={"error": {"message": "no", "code": 803}})


@pytest.fixture
def graph(monkeypatch):
    def install(g: _Graph):
        real = httpx.AsyncClient

        def client(*a, **k):
            k["transport"] = httpx.MockTransport(g.handler)
            return real(*a, **k)

        monkeypatch.setattr(facebook_publish.httpx, "AsyncClient", client)
        return g
    return install


def test_connect_page_and_publish_post_with_photos(client, graph, monkeypatch, tmp_path):
    g = graph(_Graph(pages=[{"id": "page9", "name": "Mẹ bầu page", "access_token": "PAGE_TOKEN_xxxxxxxxxxxx"}]))
    ch = _channel(client)
    info = client.post("/api/channels/facebook/inspect", json={"token": "USER_TOKEN_yyyyyyyyyyyyyy"}).json()
    assert info["kind"] == "user" and info["pages"] == [{"id": "page9", "name": "Mẹ bầu page"}]  # no tokens leak
    r = client.post(f"/api/channels/{ch['id']}/facebook", json={"token": "USER_TOKEN_yyyyyyyyyyyyyy", "page_id": "page9"})
    assert r.status_code == 200, r.text
    assert r.json()["fb_page_id"] == "page9" and r.json()["fb_connected"]
    assert facebook_publish.get_token(ch["id"]) == "PAGE_TOKEN_xxxxxxxxxxxx"  # the page token, not the user one
    # a post with one picture on disk and one missing
    pic = tmp_path / "a.jpg"
    pic.write_bytes(b"\xff\xd8\xff\xe0jpg")
    monkeypatch.setattr(scheduler, "_media_file", lambda m: pic if m == "m1" else None)
    post = _post(client, ch["id"], images=["m1", "m2"])
    slot = client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "at": _iso(datetime.now(timezone.utc) + timedelta(hours=1)), "auto": True}).json()
    assert slot["auto"]
    out = client.post(f"/api/schedule/{slot['id']}/publish").json()
    assert out["status"] == "posted" and out["result"]["post_id"] == "p1_123" and out["result"]["comment_id"] == "c1"
    assert out["result"]["permalink"] == "https://www.facebook.com/p1_123"
    feed = next(c for c in g.calls if c[1].endswith("/feed"))
    assert "attached_media" in feed[2] and "B%C3%A0i+test" in feed[2] and "%23a+%23b" in feed[2]
    assert sum(1 for c in g.calls if c[1].endswith("/photos")) == 1  # the missing picture is skipped
    assert any(c[1].endswith("/comments") for c in g.calls)
    assert client.post(f"/api/schedule/{slot['id']}/publish").status_code == 400  # already posted
    # disconnect clears the token
    assert not client.delete(f"/api/channels/{ch['id']}/facebook").json()["fb_connected"]
    assert facebook_publish.get_token(ch["id"]) is None


def test_publish_failure_is_recorded_and_tick_publishes_due_auto_slots(client, graph, monkeypatch):
    graph(_Graph(pages=[{"id": "page9", "name": "P", "access_token": "PAGE_TOKEN_xxxxxxxxxxxx"}], fail="/feed"))
    ch = _channel(client)
    client.post(f"/api/channels/{ch['id']}/facebook", json={"token": "USER_TOKEN_yyyyyyyyyyyyyy"})
    post = _post(client, ch["id"])
    slot = client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "at": _iso(datetime.now(timezone.utc) - timedelta(minutes=1)), "auto": True}).json()
    old = client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "at": _iso(datetime.now(timezone.utc) + timedelta(hours=1)), "auto": True}).json()
    _backdate(old["id"], timedelta(hours=5))
    import asyncio
    assert asyncio.run(scheduler.tick()) == 1  # the 5-hour-old one is past the grace, not attempted
    rows = {x["id"]: x for x in client.get("/api/schedule").json()["items"]}
    assert rows[slot["id"]]["status"] == "failed" and "Facebook từ chối" in rows[slot["id"]]["result"]["error"]
    assert rows[old["id"]]["status"] == "failed" and "Quá giờ" in rows[old["id"]]["result"]["error"]
    # moving a failed slot makes it planned again
    assert client.patch(f"/api/schedule/{slot['id']}", json={"at": _iso(datetime.now(timezone.utc) + timedelta(hours=1))}).json()["status"] == "planned"


def test_clip_slot_publishes_the_finished_video(client, graph, monkeypatch, tmp_path):
    g = graph(_Graph(pages=[{"id": "page9", "name": "P", "access_token": "PAGE_TOKEN_xxxxxxxxxxxx"}]))
    ch = _channel(client)
    client.post(f"/api/channels/{ch['id']}/facebook", json={"token": "USER_TOKEN_yyyyyyyyyyyyyy"})
    board = client.post("/api/boards/from-template", json={"template_id": "fast_food_ad", "channel_id": ch["id"]}).json()
    slot = client.post("/api/schedule", json={"kind": "clip", "board_id": board["id"], "at": _iso(datetime.now(timezone.utc))}).json()
    assert slot["channel_id"] == ch["id"] and slot["title"]
    # not exported yet → a clear error on the slot
    out = client.post(f"/api/schedule/{slot['id']}/publish").json()
    assert out["status"] == "failed" and "chưa ghép" in out["result"]["error"]
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    monkeypatch.setattr("flowboard.routes.exports._final_media", lambda bid: "mv1")
    monkeypatch.setattr(scheduler, "_media_file", lambda m: vid)
    client.post("/api/posts", json={"body": "Caption clip", "hashtags": "#clip", "board_id": board["id"], "channel_id": ch["id"]})
    client.patch(f"/api/schedule/{slot['id']}", json={"at": _iso(datetime.now(timezone.utc))})  # failed → planned
    out = client.post(f"/api/schedule/{slot['id']}/publish").json()
    assert out["status"] == "posted" and out["result"]["post_id"] == "v1"
    assert any(c[1].endswith("/videos") for c in g.calls) and not any(c[1].endswith("/feed") for c in g.calls)


def test_facebook_columns_migration(tmp_path):
    import sqlite3

    from sqlalchemy import create_engine, inspect

    from flowboard.db import ensure_channel_facebook_columns

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE channel (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL); INSERT INTO channel (name) VALUES ('x');")
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{db}")
    assert ensure_channel_facebook_columns(eng) is True
    assert ensure_channel_facebook_columns(eng) is False
    assert {"fb_page_id", "fb_page_name"} <= {c["name"] for c in inspect(eng).get_columns("channel")}


def test_post_with_a_video_goes_out_as_a_video(client, graph, monkeypatch, tmp_path):
    g = graph(_Graph(pages=[{"id": "page9", "name": "P", "access_token": "PAGE_TOKEN_xxxxxxxxxxxx"}]))
    ch = _channel(client)
    client.post(f"/api/channels/{ch['id']}/facebook", json={"token": "USER_TOKEN_yyyyyyyyyyyyyy"})
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    monkeypatch.setattr(scheduler, "_media_file", lambda m: vid if m == "vid1" else None)
    post = _post(client, ch["id"], images=["m1"], video="vid1")
    assert post["video"] == "vid1"
    slot = client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "at": _iso(datetime.now(timezone.utc))}).json()
    out = client.post(f"/api/schedule/{slot['id']}/publish").json()
    assert out["status"] == "posted" and out["result"]["post_id"] == "v1"
    assert any(c[1].endswith("/videos") for c in g.calls) and not any(c[1].endswith("/photos") for c in g.calls)
    # a posted slot cannot be moved
    r = client.patch(f"/api/schedule/{slot['id']}", json={"at": _iso(datetime.now(timezone.utc) + timedelta(hours=2))})
    assert r.status_code == 400


def test_a_post_written_for_a_clip_goes_out_with_the_clip_video(client, graph, monkeypatch, tmp_path):
    from flowboard.db import get_session
    from flowboard.db.models import Node
    from flowboard.services import facebook_publish, scheduler

    ch = client.post("/api/channels", json={"name": "Page", "platforms": ["facebook"]}).json()["id"]
    board = client.post("/api/boards", json={"name": "Clip có bài"}).json()["id"]
    post = client.post("/api/posts", json={"body": "Caption của clip", "board_id": board, "channel_id": ch,
                                           "images": ["img1"], "first_comment": "link"}).json()
    sent = {}

    async def fake_publish(channel_id, page_id, message, *, photos=None, video=None, first_comment=""):
        sent.update(message=message, photos=photos, video=video, first_comment=first_comment)
        return {"post_id": "1_2", "permalink": "", "comment_id": ""}

    monkeypatch.setattr(facebook_publish, "publish_post", fake_publish)
    monkeypatch.setattr(scheduler, "can_auto", lambda cid: True)
    with get_session() as s:
        from flowboard.db.models import Channel
        c = s.get(Channel, ch); c.fb_page_id = "999"; s.add(c); s.commit()
    at = scheduler._now().isoformat()
    slot = client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "channel_id": ch, "at": at}).json()
    # clip not joined yet → a clear error, never a caption-only post
    out = client.post(f"/api/schedule/{slot['id']}/publish").json()
    assert out["status"] == "failed" and "chưa ghép xong" in out["result"]["error"] and not sent
    # joined → the clip goes up as the video, the post's own pictures are not used
    clip = tmp_path / "clip.mp4"; clip.write_bytes(b"0")
    with get_session() as s:
        s.add(Node(board_id=board, short_id="exp1", type="export", x=0, y=0, data={"mediaId": "clipmedia"}, status="done"))
        s.commit()
    monkeypatch.setattr(scheduler, "_media_file", lambda mid: clip if mid == "clipmedia" else None)
    client.patch(f"/api/schedule/{slot['id']}", json={"status": "planned"})
    out = client.post(f"/api/schedule/{slot['id']}/publish").json()
    assert out["status"] == "posted" and sent["video"] == clip and sent["photos"] == [] and sent["first_comment"] == "link"
    assert client.get("/api/posts").json()[0]["clip_video"] == "clipmedia"


def test_saved_posts_say_where_they_stand_on_the_calendar(client):
    """"Bài đã lưu" shows a label for posts already scheduled / posted, so nobody schedules them twice."""
    ch = _channel(client)
    planned, due, posted, skipped, loose = (_post(client, ch["id"], body=f"Bài {i}") for i in range(5))
    soon = datetime.now(timezone.utc) + timedelta(days=1)

    def slot(post, at=soon, **over):
        return client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "at": _iso(at), **over}).json()

    later = slot(planned, soon + timedelta(days=2))
    first = slot(planned)  # two slots: the next one is shown
    _backdate(slot(due)["id"], timedelta(minutes=10))
    client.patch(f"/api/schedule/{slot(posted)['id']}", json={"status": "posted"})
    client.patch(f"/api/schedule/{slot(skipped)['id']}", json={"status": "skipped"})
    rows = {p["id"]: p["schedule"] for p in client.get("/api/posts").json()}
    assert rows[planned["id"]]["status"] == "planned" and rows[planned["id"]]["slot_id"] == first["id"]
    assert rows[planned["id"]]["planned"] == 2 and rows[planned["id"]]["at"].endswith("Z") and later["id"] != first["id"]
    assert rows[due["id"]]["status"] == "due"
    assert rows[posted["id"]]["status"] == "posted"
    assert rows[skipped["id"]] is None and rows[loose["id"]] is None
    # one post, read alone, carries it too
    assert client.patch(f"/api/posts/{planned['id']}", json={"title": "Đổi tên"}).json()["schedule"]["slot_id"] == first["id"]
    # a clip slot counts for the clip's newest post (the caption it goes out with)
    board = client.post("/api/boards/from-template", json={"template_id": "fast_food_ad", "channel_id": ch["id"]}).json()
    old = client.post("/api/posts", json={"body": "Caption cũ", "board_id": board["id"], "channel_id": ch["id"]}).json()
    new = client.post("/api/posts", json={"body": "Caption mới", "board_id": board["id"], "channel_id": ch["id"]}).json()
    client.post("/api/schedule", json={"kind": "clip", "board_id": board["id"], "at": _iso(soon)})
    rows = {p["id"]: p["schedule"] for p in client.get("/api/posts").json()}
    assert rows[new["id"]]["status"] == "planned" and rows[old["id"]] is None


def _form(request: httpx.Request) -> dict[str, bytes]:
    import re as _re

    ctype = request.headers["content-type"]
    if "boundary=" not in ctype:  # no file in it: a plain urlencoded form
        from urllib.parse import parse_qsl

        return {k: v.encode() for k, v in parse_qsl(request.content.decode())}
    boundary = ctype.split("boundary=")[1].encode()
    out = {}
    for part in request.content.split(b"--" + boundary):
        head, _, body = part.partition(b"\r\n\r\n")
        m = _re.search(rb'name="([^"]+)"', head)
        if m:
            out[m.group(1).decode()] = body[:-2] if body.endswith(b"\r\n") else body
    return out


def test_a_big_video_goes_up_in_pieces(monkeypatch, tmp_path):
    """A 152 MB clip in one request got 413 from Facebook (28/10): above CHUNKED_ABOVE the
    video goes start → transfer (the byte range Facebook asks for) → finish."""
    import asyncio

    data = bytes(range(256)) * 10_000  # 2.56 MB
    vid = tmp_path / "big.mp4"
    vid.write_bytes(data)
    got = bytearray()
    phases = []
    step = 1_000_000

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/videos"):
            f = _form(request)
            phase = f["upload_phase"].decode()
            phases.append(phase)
            if phase == "start":
                assert int(f["file_size"]) == len(data)
                return httpx.Response(200, json={"upload_session_id": "s1", "video_id": "v9", "start_offset": "0",
                                                 "end_offset": str(step)})
            if phase == "transfer":
                a = int(f["start_offset"])
                assert a == len(got)
                got.extend(f["video_file_chunk"])
                nxt = len(got)
                return httpx.Response(200, json={"start_offset": str(nxt), "end_offset": str(min(len(data), nxt + step))})
            assert f["description"].decode() == "Xin chào" and f["upload_session_id"] == b"s1"
            return httpx.Response(200, json={"success": True})
        if request.url.path.endswith("/comments"):
            return httpx.Response(200, json={"id": "c1"})
        return httpx.Response(200, json={"permalink_url": "https://www.facebook.com/v9"})

    real = httpx.AsyncClient
    monkeypatch.setattr(facebook_publish.httpx, "AsyncClient",
                        lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)}))
    monkeypatch.setattr(facebook_publish, "get_token", lambda cid: "PAGE_TOKEN")
    monkeypatch.setattr(facebook_publish, "CHUNKED_ABOVE", 1_000_000)
    out = asyncio.run(facebook_publish.publish_post(1, "page9", "Xin chào", video=vid, first_comment="link"))
    assert bytes(got) == data and phases == ["start", "transfer", "transfer", "transfer", "finish"]
    assert out["post_id"] == "v9" and out["comment_id"] == "c1"


def test_too_large_is_said_plainly():
    msg = facebook_publish._error_message(httpx.Response(413, text="<html>Request Entity Too Large</html>"))
    assert "quá lớn" in msg


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="needs ffmpeg")
def test_what_can_be_a_reel(tmp_path):
    import subprocess

    def make(name, size, secs):
        out = tmp_path / name
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=red:s={size}:d={secs}:r=5",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)], check=True)
        return out

    ok = make("ok.mp4", "540x960", 4)
    assert facebook_publish.reel_problem(ok) is None and facebook_publish.reel_warning(ok) is None
    assert "ít nhất 3 giây" in facebook_publish.reel_problem(make("short.mp4", "540x960", 1))
    # the Facebook app takes long Reels (a 3:00 one posted by hand): longer than the API's 90 s only warns
    long = make("long.mp4", "540x960", 95)
    assert facebook_publish.reel_problem(long) is None and "tối đa 90 giây" in facebook_publish.reel_warning(long)
    assert "ngang hơn 16:9" in facebook_publish.reel_warning(make("wide.mp4", "1280x480", 4))
    assert "nhỏ hơn chuẩn Reel" in facebook_publish.reel_warning(make("tiny.mp4", "360x640", 4))


def test_a_video_post_can_go_out_as_a_reel(client, monkeypatch, tmp_path):
    """fb_format "reel": video_reels start → the file to rupload → finish (PUBLISHED, caption) → wait → first comment."""
    vid = tmp_path / "r.mp4"
    vid.write_bytes(b"REELDATA" * 1000)
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        path, host = request.url.path, request.url.host
        if host == "rupload.facebook.com":
            calls.append(("upload", request.headers.get("offset"), request.headers.get("file_size"), len(request.content),
                          request.headers.get("authorization")))
            return httpx.Response(200, json={"success": True})
        if path.endswith("/video_reels"):
            f = _form(request)
            calls.append(("reels", f["upload_phase"].decode(), f.get("video_state", b"").decode(), f.get("description", b"").decode()))
            if f["upload_phase"] == b"start":
                return httpx.Response(200, json={"video_id": "r77", "upload_url": "https://rupload.facebook.com/video-upload/v21.0/r77"})
            return httpx.Response(200, json={"success": True})
        if path.endswith("/comments"):
            calls.append(("comment", path))
            return httpx.Response(200, json={"id": "c9"})
        if "r77" in path and request.url.params.get("fields") == "status":
            calls.append(("status",))
            return httpx.Response(200, json={"status": {"video_status": "ready"}})
        if "r77" in path:
            return httpx.Response(200, json={"permalink_url": "/reel/r77"})
        if path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": [{"id": "page9", "name": "P", "access_token": "PAGE_TOKEN_xxxxxxxxxxxx"}]})
        if path.endswith("/me"):
            return httpx.Response(200, json={"id": "u1", "name": "Duy"})
        return httpx.Response(404, json={"error": {"message": "no", "code": 803}})

    real = httpx.AsyncClient
    monkeypatch.setattr(facebook_publish.httpx, "AsyncClient",
                        lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)}))
    monkeypatch.setattr(facebook_publish, "reel_problem", lambda v: None)
    monkeypatch.setattr(scheduler, "_media_file", lambda m: vid if m == "vid1" else None)
    ch = _channel(client)
    client.post(f"/api/channels/{ch['id']}/facebook", json={"token": "USER_TOKEN_yyyyyyyyyyyyyy"})
    text_only = _post(client, ch["id"])
    r = client.post("/api/schedule", json={"kind": "post", "post_id": text_only["id"], "fb_format": "reel",
                                           "at": _iso(datetime.now(timezone.utc))})
    assert r.status_code == 400 and "Reel cần một video" in r.json()["detail"]
    assert client.get("/api/schedule/reel-check", params={"kind": "post", "post_id": text_only["id"]}).json()["has_video"] is False
    post = client.post("/api/posts", json={"body": "Reel nè", "hashtags": "#reel", "channel_id": ch["id"], "video": "vid1",
                                           "first_comment": "Link ở đây"}).json()
    monkeypatch.setattr(facebook_publish, "reel_warning", lambda v: None)
    assert client.get("/api/schedule/reel-check", params={"kind": "post", "post_id": post["id"]}).json() == \
        {"has_video": True, "ok": True, "reason": None, "warning": None}
    slot = client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "fb_format": "reel",
                                              "at": _iso(datetime.now(timezone.utc))}).json()
    assert slot["fb_format"] == "reel"
    out = client.post(f"/api/schedule/{slot['id']}/publish").json()
    assert out["status"] == "posted", out["result"]
    assert out["result"]["post_id"] == "r77" and out["result"]["permalink"] == "https://www.facebook.com/reel/r77"
    assert calls[0] == ("reels", "start", "", "")
    assert calls[1] == ("upload", "0", str(len(vid.read_bytes())), len(vid.read_bytes()), "OAuth PAGE_TOKEN_xxxxxxxxxxxx")
    assert calls[2][:3] == ("reels", "finish", "PUBLISHED") and "Reel nè" in calls[2][3]
    assert ("status",) in calls and calls[-1][0] == "comment"
    # switching a planned slot back to a normal post
    slot2 = client.post("/api/schedule", json={"kind": "post", "post_id": post["id"], "fb_format": "reel",
                                               "at": _iso(datetime.now(timezone.utc) + timedelta(hours=3))}).json()
    assert client.patch(f"/api/schedule/{slot2['id']}", json={"fb_format": "post"}).json()["fb_format"] == "post"
