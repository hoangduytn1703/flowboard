"""📡 Cào video kênh (services/channel_grab, routes/grab): channel links, listings, downloads, the AI's pick."""
import time
from datetime import datetime, timezone

import pytest

from flowboard import plans
from flowboard.services import channel_grab as grab
from flowboard.services import media as media_service


def _listing(n=3, shelf="videos"):
    """What ``yt-dlp --flat-playlist -J`` says about a YouTube shelf."""
    short = shelf == "shorts"
    return {
        "channel": "Kênh Mẫu", "channel_follower_count": 1200, "description": "Mô  tả\nkênh",
        "thumbnails": [{"id": "banner", "url": "https://img.example.com/banner.jpg"},
                       {"id": "avatar_uncropped", "url": "https://img.example.com/avatar.jpg"}],
        "entries": [{
            "id": f"{shelf}{i}", "title": f"  Video  {shelf} {i} ",
            "url": f"https://www.youtube.com/{'shorts/' if short else 'watch?v='}{shelf}{i}",
            "view_count": 1000 * (i + 1), "duration": None if short else 60 * (i + 1),
            "timestamp": None if short else 1_790_000_000 + i * 86400,
            "thumbnails": [{"url": f"https://img.example.com/{shelf}{i}.jpg", "width": 720, "height": 404}],
        } for i in range(n)] + [{"id": "soon", "title": "Sắp chiếu", "url": "https://www.youtube.com/watch?v=soon", "live_status": "is_upcoming"}],
    }


@pytest.fixture
def listed(monkeypatch):
    """yt-dlp replaced: a channel with a videos shelf and a shorts shelf; covers are not fetched."""
    calls = []

    def fake_list(url, limit, stop=None):
        calls.append((url, limit))
        if url.endswith("/shorts"):
            return _listing(2, "shorts")
        return _listing(3, "videos")

    monkeypatch.setattr(grab, "_list", fake_list)
    monkeypatch.setattr(grab, "fetch_image", lambda url, dest: False)
    grab.SCANS.clear()
    grab.DOWNLOADS.clear()
    grab._BATCH.clear()
    return calls


def _wait(test, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if test():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def _scan_done(cid):
    _wait(lambda: grab.scan_of(cid) is not None and grab.scan_of(cid).status != "running")
    return grab.scan_of(cid)


def test_a_pasted_link_names_its_channel():
    yt = grab.parse_channel("xem kênh này https://www.youtube.com/@KenhMau/videos nhé")
    assert yt == {"platform": "youtube", "key": "youtube:@kenhmau", "url": "https://www.youtube.com/@KenhMau", "handle": "@KenhMau"}
    assert grab.parse_channel("youtube.com/@abc")["key"] == "youtube:@abc"
    assert grab.parse_channel("https://m.youtube.com/channel/UCsXVk37bltHxD1rDPwtNM8Q/shorts")["key"] == "youtube:UCsXVk37bltHxD1rDPwtNM8Q"
    assert grab.parse_channel("https://www.youtube.com/playlist?list=PLFs4vir_WsTwEd-nJgVJCZPNL3HALHHpF")["key"].startswith("youtube:list:")
    # a TikTok video's link carries its account
    assert grab.parse_channel("https://www.tiktok.com/@nasa/video/7706264639297850637?x=1")["url"] == "https://www.tiktok.com/@nasa"
    for bad, word in (("https://www.youtube.com/watch?v=abc", "link kênh"), ("https://youtu.be/abc", "link kênh"),
                      ("https://www.instagram.com/nasa/", "Facebook, Instagram"), ("@abc", "Dán link kênh")):
        with pytest.raises(grab.GrabError, match=word):
            grab.parse_channel(bad)
    assert grab.listing_targets("youtube", "https://www.youtube.com/@a", "youtube:@a") == [
        ("https://www.youtube.com/@a/videos", "video"), ("https://www.youtube.com/@a/shorts", "short")]
    assert grab.listing_targets("youtube", "https://www.youtube.com/playlist?list=PL1234567890", "youtube:list:PL1234567890")[0][1] == "video"
    assert grab.normalize_tags(["  #Vũ trụ ", "vũ trụ", "", "khoa học"]) == ["Vũ trụ", "khoa học"]
    assert grab.normalize_limit("abc") == grab.DEFAULT_LIMIT and grab.normalize_limit(9999) == grab.MAX_LIMIT


def test_a_listing_becomes_rows():
    rows = grab.entry_rows(_listing(2), "youtube", "video")
    assert [r["key"] for r in rows] == ["youtube:videos0", "youtube:videos1"]  # the upcoming one is left out
    assert rows[0]["title"] == "Video videos 0" and rows[0]["views"] == 1000 and rows[0]["duration_s"] == 60.0
    assert rows[1]["published_at"] == datetime.fromtimestamp(1_790_086_400, timezone.utc) and rows[1]["position"] == 1
    assert rows[0]["thumb"].endswith("videos0.jpg")
    short = grab.entry_rows(_listing(1, "shorts"), "youtube", "short")[0]
    assert short["kind"] == "short" and short["duration_s"] is None and short["published_at"] is None
    # a channel root lists its shelves as nested playlists
    nested = grab.entry_rows({"entries": [{"_type": "playlist", "title": "X - Videos", "entries": _listing(1)["entries"]},
                                          {"_type": "playlist", "title": "X - Shorts", "entries": _listing(1, "shorts")["entries"]}]},
                             "youtube", "video")
    assert [r["kind"] for r in nested] == ["video", "short"]
    assert grab.entry_rows({"entries": [{"id": "1", "url": "https://www.tiktok.com/@a/video/1"}]}, "tiktok", "video")[0]["thumb"] == ""
    meta = grab.channel_meta(_listing(1))
    assert meta == {"name": "Kênh Mẫu", "followers": 1200, "description": "Mô tả kênh", "avatar": "https://img.example.com/avatar.jpg"}
    assert grab.channel_meta({"entries": [{"channel": "NASA"}]}) == {"name": "NASA"}


def test_adding_a_channel_scans_it_and_a_rescan_marks_the_new_ones(client, listed, monkeypatch):
    r = client.post("/api/grab/channels", json={"url": "https://www.youtube.com/@KenhMau", "tags": ["vũ trụ"], "limit": 30})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    scan = _scan_done(cid)
    assert scan.status == "done" and scan.found == 5, scan.error
    assert [u for u, _ in listed] == ["https://www.youtube.com/@KenhMau/videos", "https://www.youtube.com/@KenhMau/shorts"]
    ch = client.get("/api/grab/channels").json()[0]
    assert ch["name"] == "Kênh Mẫu" and ch["followers"] == 1200 and ch["videos"] == 5 and ch["fresh"] == 0
    assert ch["tags"] == ["vũ trụ"] and ch["platform_label"] == "YouTube" and ch["scanned_at"] and ch["scan"] is None or ch["scan"]["status"] == "done"
    vids = client.get(f"/api/grab/videos?channel_id={cid}").json()
    assert [v["kind"] for v in vids].count("short") == 2 and all(v["download"] == "" and v["media_id"] is None for v in vids)
    assert client.get("/api/grab/state").json() == {"scans": {}, "downloads": {}}

    # the same channel pasted another way is the same row; a new video on the channel is marked fresh, the rest keep their state
    monkeypatch.setattr(grab, "_list", lambda url, limit, stop=None: _listing(4 if url.endswith("/videos") else 2, "videos" if url.endswith("/videos") else "shorts"))
    again = client.post("/api/grab/channels", json={"url": "youtube.com/@kenhmau/shorts", "tags": ["khoa học"]})
    assert again.json()["id"] == cid and again.json()["tags"] == ["vũ trụ", "khoa học"]
    _wait(lambda: grab.scan_of(cid).status != "running" and grab.scan_of(cid).found == 6)
    ch = client.get("/api/grab/channels").json()[0]
    assert ch["videos"] == 6 and ch["fresh"] == 1
    assert [v["title"] for v in client.get("/api/grab/videos").json() if v["fresh"]] == ["Video videos 3"]

    assert client.patch(f"/api/grab/channels/{cid}", json={"tags": ["a", "A", "b"], "note": " ghi chú "}).json()["tags"] == ["a", "b"]
    assert client.post("/api/grab/channels", json={"url": "https://www.youtube.com/watch?v=x"}).status_code == 400
    assert client.patch("/api/grab/channels/999", json={"note": "x"}).status_code == 404
    assert client.delete(f"/api/grab/channels/{cid}").json() == {"deleted": True, "videos": 6}
    assert client.get("/api/grab/channels").json() == [] and client.get("/api/grab/videos").json() == []


def test_a_scan_that_finds_nothing_says_why(client, monkeypatch):
    def refuse(url, limit, stop=None):
        raise grab.GrabError("ERROR: kênh không tồn tại")

    monkeypatch.setattr(grab, "_list", refuse)
    grab.SCANS.clear()
    cid = client.post("/api/grab/channels", json={"url": "https://www.tiktok.com/@khongco"}).json()["id"]
    assert _scan_done(cid).status == "error"
    ch = client.get("/api/grab/channels").json()[0]
    assert "không tồn tại" in ch["scan_error"] and ch["videos"] == 0
    assert grab.outcome("grabscan", str(cid)) == {"ok": False, "message": "ERROR: kênh không tồn tại"}


def test_picked_videos_download_and_go_on_as_files(client, listed, monkeypatch):
    from flowboard.services import video_fetch

    cid = client.post("/api/grab/channels", json={"url": "https://www.tiktok.com/@kenh"}).json()["id"]
    _scan_done(cid)
    vids = client.get("/api/grab/videos").json()
    good, bad = vids[0]["id"], vids[1]["id"]

    def fake_fetch(url, media_id, out_dir, *, max_duration_s=None, stop=None):
        if url.endswith("videos1"):
            raise video_fetch.FetchError("video dài hơn 60 phút")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{media_id}.mp4"
        path.write_bytes(b"not a real video")
        return path, "Tên từ trang"

    monkeypatch.setattr(video_fetch, "fetch_video", fake_fetch)
    assert client.post("/api/grab/download", json={"ids": []}).status_code == 400
    assert client.post("/api/grab/download", json={"ids": [good, bad]}).json() == {"queued": 2, "skipped": 0}
    _wait(lambda: all(grab.download_of(i).status not in ("queued", "running") for i in (good, bad)))
    by_id = {v["id"]: v for v in client.get("/api/grab/videos").json()}
    assert by_id[good]["download"] == "done" and by_id[good]["media_id"] and by_id[good]["downloaded_at"]
    assert (media_service.MEDIA_CACHE_DIR / f"{by_id[good]['media_id']}.mp4").is_file()
    assert by_id[bad]["download"] == "" and "60 phút" in by_id[bad]["download_error"] and by_id[bad]["media_id"] is None
    assert grab.outcome("grabdl", "batch")["ok"] is False and client.get("/api/grab/channels").json()[0]["downloaded"] == 1
    # already here: not downloaded twice; the tools take the downloaded ones as files, in the order asked
    assert client.post("/api/grab/download", json={"ids": [good]}).json() == {"queued": 0, "skipped": 1}
    assert client.post("/api/grab/media", json={"ids": [bad, good, 999]}).json() == [
        {"id": good, "media_id": by_id[good]["media_id"], "name": by_id[good]["title"]}]
    assert client.post("/api/grab/used", json={"ids": [good], "tool": "cut"}).json() == {"marked": 1}
    assert "cut" in {v["id"]: v for v in client.get("/api/grab/videos").json()}[good]["used"]
    assert client.post("/api/grab/used", json={"ids": [good], "tool": "x"}).status_code == 422
    # the file gone from this machine (downloaded on the other one): it reads as not here
    (media_service.MEDIA_CACHE_DIR / f"{by_id[good]['media_id']}.mp4").unlink()
    v = {v["id"]: v for v in client.get("/api/grab/videos").json()}[good]
    assert v["media_id"] is None and v["elsewhere"] is True and v["download"] == ""
    # the channel leaves with its list
    client.delete(f"/api/grab/channels/{cid}")
    assert client.post("/api/grab/media", json={"ids": [good]}).json() == []


def test_a_download_stops_when_asked(client, listed, monkeypatch):
    from flowboard.services import video_fetch

    cid = client.post("/api/grab/channels", json={"url": "https://www.tiktok.com/@kenh"}).json()["id"]
    _scan_done(cid)
    vid = client.get("/api/grab/videos").json()[0]["id"]

    def slow_fetch(url, media_id, out_dir, *, max_duration_s=None, stop=None):
        end = time.time() + 10
        while time.time() < end:
            if stop():
                raise video_fetch.FetchError(video_fetch.STOPPED)
            time.sleep(0.01)
        raise AssertionError("never stopped")

    monkeypatch.setattr(video_fetch, "fetch_video", slow_fetch)
    client.post("/api/grab/download", json={"ids": [vid]})
    _wait(lambda: grab.download_of(vid).status == "running")
    assert client.get("/api/grab/state").json()["downloads"] == {str(vid): {"status": "running", "stopping": False}}
    assert [it["key"] for it in grab.running_items()] == ["grabdl:batch"]
    assert client.post("/api/grab/download/stop", json={"ids": []}).json() == {"stopping": 1}
    _wait(lambda: grab.download_of(vid).status == "error")
    v = client.get("/api/grab/videos").json()[0]
    assert v["download"] == "" and v["download_error"] == ""  # stopping is not an error to show
    assert grab.outcome("grabdl", "batch")["ok"] is True


def test_the_ai_picks_by_the_request(client, listed, monkeypatch):
    cid = client.post("/api/grab/channels", json={"url": "https://www.youtube.com/@KenhMau"}).json()["id"]
    _scan_done(cid)
    ids = [v["id"] for v in client.get("/api/grab/videos").json()]
    seen = {}

    async def fake_llm(feature, prompt, **kw):
        seen["prompt"], seen["system"] = prompt, kw.get("system_prompt")
        return 'Đây: {"picks": [{"n": 2, "why": "nhiều  view"}, {"n": 99, "why": "x"}, {"n": 2, "why": "lặp"}, {"n": 1}], "note": "2 video hợp"}'

    monkeypatch.setattr("flowboard.services.llm.run_llm", fake_llm)
    r = client.post("/api/grab/pick", json={"ids": ids, "prompt": "2 video nhiều view"})
    assert r.status_code == 200, r.text
    assert r.json() == {"picks": [{"id": ids[1], "why": "nhiều view"}, {"id": ids[0], "why": ""}], "note": "2 video hợp"}
    assert "THE SELLER'S REQUEST: 2 video nhiều view" in seen["prompt"] and "[1] views=1000" in seen["prompt"] and "JSON" in seen["system"]
    assert client.post("/api/grab/pick", json={"ids": ids, "prompt": "  "}).status_code == 400
    assert client.post("/api/grab/pick", json={"ids": [], "prompt": "x"}).status_code == 400

    async def broken(feature, prompt, **kw):
        return "không biết"

    monkeypatch.setattr("flowboard.services.llm.run_llm", broken)
    assert "AI chưa chọn được" in client.post("/api/grab/pick", json={"ids": ids, "prompt": "x"}).json()["detail"]


def test_the_plan_gates_the_tool():
    assert plans.feature_for("GET", "/api/grab/channels") == ("grab",)
    assert plans.feature_for("POST", "/api/grab/media") == ("grab", "cut", "dub")
    assert "grab" in plans.FEATURE_KEYS and "grab" in [f["key"] for f in plans.shown_features()]


def test_the_assistant_grabs_channels():
    from flowboard.services import assistant

    out = assistant.parse_answer('{"reply": "ok", "actions": [{"tool": "grab_channel", "args": {"urls": ["https://www.youtube.com/@KenhMau/videos", '
                                 '"https://www.youtube.com/watch?v=x"], "tags": ["vũ trụ"], "limit": 100}}]}')
    a = out["actions"][0]
    assert a["tool"] == "grab_channel" and a["args"] == {"urls": ["https://www.youtube.com/@KenhMau"], "tags": ["vũ trụ"], "limit": 100}
    q = assistant.parse_answer('{"reply": "ok", "actions": [{"tool": "grab_channel", "args": {"urls": ["https://www.facebook.com/nasa"]}}]}')
    assert not q["actions"] and "Facebook, Instagram" in q["reply"]
    assert "📡" in assistant._plan_summary(out["actions"], {"channels": [], "products": []})[0]


def test_a_deeper_scan_does_not_call_old_videos_new(client, monkeypatch):
    """"MỚI" = posted since the last scan: older videos a bigger scan reaches are not, a dated newer one is, and an
    undated one (YouTube Shorts) only when it stands ahead of every short already known."""
    def listing(ids, short=False):
        return {"channel": "K", "entries": [{"id": i, "title": i, "url": f"https://www.youtube.com/{'shorts/' if short else 'watch?v='}{i}",
                                             **({} if short else {"timestamp": 1_790_000_000 + day * 86400})} for i, day in ids]}

    shelves = {"videos": [("v5", 5), ("v4", 4)], "shorts": [("s2", 0), ("s1", 0)]}
    monkeypatch.setattr(grab, "_list", lambda url, limit, stop=None: listing(shelves["shorts"], True) if url.endswith("/shorts") else listing(shelves["videos"]))
    monkeypatch.setattr(grab, "fetch_image", lambda url, dest: False)
    grab.SCANS.clear()
    cid = client.post("/api/grab/channels", json={"url": "https://www.youtube.com/@k"}).json()["id"]
    _scan_done(cid)
    assert not any(v["fresh"] for v in client.get("/api/grab/videos").json())
    shelves["videos"] = [("v6", 6), ("v5", 5), ("v4", 4), ("v3", 3), ("v2", 2)]
    shelves["shorts"] = [("s3", 0), ("s2", 0), ("s1", 0), ("s0", 0)]
    client.post(f"/api/grab/channels/{cid}/scan", json={"limit": 200})
    _wait(lambda: grab.scan_of(cid).status != "running" and grab.scan_of(cid).found == 9)
    assert sorted(v["title"] for v in client.get("/api/grab/videos").json() if v["fresh"]) == ["s3", "v6"]
    assert grab.scan_of(cid).added == 2 and client.get("/api/grab/channels").json()[0]["videos"] == 9


def test_douyin_and_bilibili_links_name_their_channel():
    sec = "MS4wLjABAAAA8U_l6rBzmy7bcy6xOJel4v0RzoR_wfAubGPeJimN__4"
    want = {"platform": "douyin", "key": f"douyin:{sec}", "url": f"https://www.douyin.com/user/{sec}", "handle": ""}
    assert grab.parse_channel(f"https://www.douyin.com/user/{sec}?from_tab_name=main") == want
    assert grab.parse_channel(f"https://www.iesdouyin.com/share/user/{sec}") == want
    bili = {"platform": "bilibili", "key": "bilibili:946974", "url": "https://space.bilibili.com/946974/upload/video", "handle": ""}
    for link in ("https://space.bilibili.com/946974", "space.bilibili.com/946974/video", "https://space.bilibili.com/zh-Hans/946974/upload/video"):
        assert grab.parse_channel(link) == bili
    for bad, word in (("https://www.douyin.com/video/7300000000000000000", "trang cá nhân"), ("https://www.bilibili.com/video/BV1kZWX62ENY", "trang của kênh"),
                      ("https://www.facebook.com/nasa", "Douyin và Bilibili")):
        with pytest.raises(grab.GrabError, match=word):
            grab.parse_channel(bad)


def _chrome_answer():
    """What the extension (capture.js) sends for a Douyin account: trimmed list items, newest first."""
    return {"platform": "douyin", "title": "某某的抖音 - 抖音", "user": {"name": "Kênh Trung", "avatar": "", "followers": 5000}, "items": [
        {"id": "7400000000000000002", "title": " Video  mới ", "created": 1_790_086_400, "duration_ms": 61500, "likes": 1200, "comments": 30,
         "views": None, "cover": "https://p3.douyinpic.com/a.jpeg", "pinned": False, "images": False},
        {"id": "7400000000000000001", "title": "Bài ảnh", "created": 1_790_000_000, "likes": 5, "images": True},
        {"id": "7400000000000000000", "title": "Video cũ", "created": 1_789_000_000, "duration_ms": 9000, "likes": 88, "comments": 1,
         "views": 0, "cover": "", "pinned": True, "images": False},
    ]}


def test_what_chrome_gathered_becomes_rows():
    rows = grab.browser_rows(_chrome_answer(), "douyin", "Douyin")
    assert [r["key"] for r in rows] == ["douyin:7400000000000000002", "douyin:7400000000000000000"]  # the photo post is left out
    first = rows[0]
    assert first["url"] == "https://www.douyin.com/video/7400000000000000002" and first["title"] == "Video mới"
    assert first["duration_s"] == 61.5 and first["likes"] == 1200 and first["views"] is None  # Douyin shows no view counts
    assert first["published_at"] == datetime.fromtimestamp(1_790_086_400, timezone.utc) and rows[1]["position"] == 1
    bili = grab.browser_rows({"items": [{"id": "BV1kZWX62ENY", "title": "T", "created": 1_790_000_000, "duration_s": 754, "views": 31000,
                                         "comments": 12, "likes": None, "cover": "//i0.hdslb.com/x.jpg"}]}, "bilibili", "Bilibili")[0]
    assert bili["url"] == "https://www.bilibili.com/video/BV1kZWX62ENY" and bili["thumb"] == "https://i0.hdslb.com/x.jpg" and bili["views"] == 31000
    # nothing through the list requests: the links the page shows, without dates
    dom = grab.browser_rows({"items": [], "dom": [{"id": "7400000000000000009", "title": "Từ trang", "cover": ""}]}, "douyin", "Douyin")
    assert dom[0]["title"] == "Từ trang" and dom[0]["published_at"] is None
    for answer, word in (({"items": [], "login": True}, "đăng nhập"), ({"items": [], "refused": 2}, "đăng nhập"),
                         ({"items": [], "captcha": True, "login": True}, "captcha"), ({"empty": True}, "không hiện video")):
        with pytest.raises(grab.GrabError, match=word):
            grab.browser_rows(answer, "douyin", "Douyin")


def test_a_douyin_channel_is_scanned_through_chrome(client, monkeypatch):
    asked = []

    def fake_chrome(url, limit, label, stop=None):
        asked.append((url, limit, label))
        return _chrome_answer()

    monkeypatch.setattr(grab, "_list_via_chrome", fake_chrome)
    monkeypatch.setattr(grab, "browser_meta", lambda data, platform, url: {"name": data["user"]["name"], "followers": 5000})
    monkeypatch.setattr(grab, "fetch_image", lambda url, dest: False)
    monkeypatch.setattr(grab, "_list", lambda *a, **k: (_ for _ in ()).throw(AssertionError("yt-dlp is not asked for Douyin")))
    grab.SCANS.clear()
    sec = "MS4wLjABAAAA8U_l6rBzmy7bcy6xOJel4v0RzoR_wfAubGPeJimN__4"
    r = client.post("/api/grab/channels", json={"url": f"https://www.douyin.com/user/{sec}", "limit": 30})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert _scan_done(cid).status == "done", grab.scan_of(cid).error
    assert asked == [(f"https://www.douyin.com/user/{sec}", 30, "Douyin")]
    ch = client.get("/api/grab/channels").json()[0]
    assert ch["platform"] == "douyin" and ch["platform_label"] == "Douyin" and ch["name"] == "Kênh Trung" and ch["videos"] == 2
    assert [v["url"] for v in client.get("/api/grab/videos").json()] == ["https://www.douyin.com/video/7400000000000000002",
                                                                        "https://www.douyin.com/video/7400000000000000000"]
    status = client.get("/api/grab/status").json()
    assert {p["key"]: p["via"] for p in status["platforms"]} == {"youtube": "ytdlp", "tiktok": "ytdlp", "douyin": "chrome", "bilibili": "chrome"}


def test_no_extension_says_what_to_do(client, monkeypatch):
    """Without the extension (or with an old one) a Douyin scan ends with what the seller has to do."""
    from flowboard.services import flow_client

    class Gone:
        connected = False
        extension_version = None

    monkeypatch.setattr(flow_client, "get_flow_client", lambda: Gone())
    with pytest.raises(grab.GrabError, match="extension DFlow chưa kết nối"):
        grab._list_via_chrome("https://www.douyin.com/user/x", 30, "Douyin")

    class Old:
        connected = True
        extension_version = "0.6.1"

    monkeypatch.setattr(flow_client, "get_flow_client", lambda: Old())
    monkeypatch.setattr(grab, "LOOP", object())
    with pytest.raises(grab.GrabError, match="0.7.1"):
        grab._list_via_chrome("https://www.douyin.com/user/x", 30, "Douyin")
    grab.SCANS.clear()
    cid = client.post("/api/grab/channels", json={"url": "https://space.bilibili.com/946974"}).json()["id"]
    assert _scan_done(cid).status == "error"
    assert "0.7.1" in client.get("/api/grab/channels").json()[0]["scan_error"]


def test_a_bilibili_space_link_may_carry_a_language():
    for link in ("https://space.bilibili.com/en/397490386", "https://space.bilibili.com/zh-CN/397490386/video",
                 "space.bilibili.com/397490386?spm_id_from=333", "https://www.bilibili.com/en/space/397490386"):
        got = grab.parse_channel(link)
        assert got["key"] == "bilibili:397490386" and got["url"] == "https://space.bilibili.com/397490386/upload/video", link


def test_video_labels_survive_a_rescan_and_the_channel_coming_back(client, listed):
    cid = client.post("/api/grab/channels", json={"url": "https://www.youtube.com/@KenhMau"}).json()["id"]
    assert _scan_done(cid).status == "done"
    vids = {v["title"]: v for v in client.get("/api/grab/videos").json()}
    first, second = vids["Video videos 0"]["id"], vids["Video videos 1"]["id"]
    assert all(v["marks"] == [] for v in vids.values())
    presets = client.get("/api/grab/status").json()["mark_presets"]
    assert presets[:2] == ["Đã xử lý", "Đã đăng"]

    r = client.post("/api/grab/marks", json={"ids": [first, second], "add": ["Đã xử lý", " #kênh A ", "đã xử lý"]})
    assert r.json() == {"marked": 2}
    client.post("/api/grab/marks", json={"ids": [second], "add": ["Đã đăng"], "remove": ["Đã xử lý"]})
    client.post("/api/grab/used", json={"ids": [first], "tool": "cut"})
    got = {v["id"]: v for v in client.get("/api/grab/videos").json()}
    assert got[first]["marks"] == ["Đã xử lý", "kênh A"] and got[second]["marks"] == ["kênh A", "Đã đăng"]
    tags = {t["tag"]: t for t in client.get("/api/grab/marks").json()}
    assert tags["Đã xử lý"]["videos"] == 1 and tags["kênh A"]["videos"] == 2 and tags["Để dành"] == {"tag": "Để dành", "videos": 0, "preset": True}
    assert client.get("/api/grab/channels").json()[0]["marked"] == 2

    # the channel removed and added again: new rows, the same videos — their labels and "đã cắt" come back
    client.delete(f"/api/grab/channels/{cid}")
    cid = client.post("/api/grab/channels", json={"url": "youtube.com/@kenhmau"}).json()["id"]
    assert _scan_done(cid).status == "done"
    again = {v["title"]: v for v in client.get("/api/grab/videos").json()}
    assert again["Video videos 0"]["marks"] == ["Đã xử lý", "kênh A"] and again["Video videos 0"]["used"].get("cut")
    assert again["Video videos 1"]["marks"] == ["kênh A", "Đã đăng"] and again["Video videos 2"]["marks"] == []
    assert client.post("/api/grab/marks", json={"ids": [], "add": ["x"]}).status_code == 400


def test_a_scan_may_read_every_video_of_a_channel(client, listed):
    assert grab.normalize_limit(3000) == 3000 and grab.normalize_limit(99999) == grab.MAX_LIMIT and grab.normalize_limit(2) == 5
    assert grab.list_timeout(3000) > grab.list_timeout(60) and grab.browser_timeout_ms(3000) <= 30 * 60 * 1000
    st = client.get("/api/grab/status").json()
    assert st["max_limit"] == 3000 and 1000 in st["limits"]
    assert [p for p in st["platforms"] if p["key"] == "bilibili"][0]["beta"]
    cid = client.post("/api/grab/channels", json={"url": "https://www.youtube.com/@KenhMau", "limit": 2500}).json()["id"]
    assert _scan_done(cid).status == "done"
    assert {limit for _, limit in listed} == {2500}
