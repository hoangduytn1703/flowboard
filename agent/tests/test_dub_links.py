"""📚 Link library for dubbing: links out of .txt / .md files, the same video however it is written,
what each link has become, and the library queue that feeds the dub queue one video at a time."""
from __future__ import annotations

import pytest

from flowboard.db import get_session
from flowboard.db.models import Board, DubLink
from flowboard.services import dub, dub_links
from flowboard.services import media as media_service


@pytest.fixture
def lib(monkeypatch, tmp_path):
    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)  # no job.json of the real machine
    monkeypatch.setattr(dub_links, "resolve_final", lambda url: {
        "https://v.douyin.com/AbC123/": "https://www.iesdouyin.com/share/video/7570966119428452793/?region=CN&mid=1",
    }.get(url))
    dub_links._RESOLVED.clear()
    dub.JOBS.clear()
    monkeypatch.setattr(dub_links, "_maybe_queued", True)
    yield
    dub.JOBS.clear()
    dub_links._RESOLVED.clear()


NOTES = """# Video hay tuần này
- [Mẹ bầu nên ăn gì](https://www.douyin.com/video/7570966119428452793)
7.43 复制打开抖音，看看【小美的作品】孕妇必看 https://v.douyin.com/AbC123/ dGv:/ 02/12
Xem thêm (https://youtu.be/dQw4w9WgXcQ?si=abc).
https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30
**https://shopee.vn/sp-i.1.2**, và trang web https://example.com/blog/post_(1)
lặp lại: https://www.douyin.com/video/7570966119428452793
"""


def test_links_come_out_of_any_text_with_their_labels():
    found = dub_links.extract_links(NOTES)
    urls = [x["url"] for x in found]
    assert urls == [
        "https://www.douyin.com/video/7570966119428452793",
        "https://v.douyin.com/AbC123/",
        "https://youtu.be/dQw4w9WgXcQ?si=abc",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30",
        "https://shopee.vn/sp-i.1.2",
        "https://example.com/blog/post_(1)",
    ]
    assert found[0]["label"] == "Mẹ bầu nên ăn gì"
    assert "孕妇必看" in found[1]["label"] and "http" not in found[1]["label"]
    # [https://x](https://x): the brackets do not glue onto the link
    assert [x["url"] for x in dub_links.extract_links("[https://x.com/a/status/1](https://x.com/a/status/1)")] == ["https://x.com/a/status/1"]
    assert dub_links.extract_links("không có link nào") == []


def test_the_same_video_has_one_key_however_it_is_written(lib):
    k = dub_links.link_key
    assert k("https://www.douyin.com/video/7570966119428452793?previous_page=app") == "douyin:7570966119428452793"
    assert k("https://www.douyin.com/jingxuan?modal_id=7570966119428452793") == "douyin:7570966119428452793"
    assert k("https://youtu.be/dQw4w9WgXcQ?si=abc") == k("https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=30") == "youtube:dQw4w9WgXcQ"
    assert k("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "youtube:dQw4w9WgXcQ"
    assert k("https://www.tiktok.com/@ban/video/7300000000000000001?is_from_webapp=1") == "tiktok:7300000000000000001"
    assert k("https://example.com/a/b/?utm_source=x&id=7") == "example.com/a/b?id=7"
    # a short share link follows its redirect to the video id; an unknown one keeps its plain key
    assert dub_links.key_for("https://v.douyin.com/AbC123/") == "douyin:7570966119428452793"
    assert dub_links.key_for("https://v.douyin.com/Zzz/") == "v.douyin.com/Zzz"
    assert dub_links.is_video_link("https://v.douyin.com/AbC123/") and not dub_links.is_video_link("https://shopee.vn/x")


def test_import_keeps_file_order_and_skips_links_already_in_the_library(lib):
    r = dub_links.import_texts([{"name": "ghi-chu.md", "text": NOTES}])
    # the short Douyin link is the same video as the first line; the two YouTube links are one video too
    assert r["found"] == 6 and len(r["added"]) == 4 and r["files"] == [{"name": "ghi-chu.md", "links": 6}]
    again = dub_links.import_texts([{"name": "khac.txt", "text": "https://youtu.be/dQw4w9WgXcQ\nhttps://www.tiktok.com/@a/video/7300000000000000001"}])
    assert len(again["added"]) == 1 and len(again["existing"]) == 1
    rows = dub_links.library()["links"]
    assert [r["url"] for r in rows] == [
        "https://www.tiktok.com/@a/video/7300000000000000001",  # newest import first
        "https://www.douyin.com/video/7570966119428452793",
        "https://youtu.be/dQw4w9WgXcQ?si=abc",
        "https://shopee.vn/sp-i.1.2",
        "https://example.com/blog/post_(1)",
    ]
    assert [r["video"] for r in rows] == [True, True, True, False, False]
    with pytest.raises(dub_links.LinkError):
        dub_links.import_texts([])


def test_each_link_says_whether_its_video_was_dubbed(lib):
    dub_links.import_texts([{"name": "a.txt", "text": "\n".join([
        "https://www.douyin.com/video/7570966119428452793",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.tiktok.com/@a/video/7300000000000000001",
        "https://www.tiktok.com/@a/video/7300000000000000002",
        "https://www.bilibili.com/video/BV1xx411c7mD",
    ])}])
    # done from its short share link, a job still running, one that failed, and a clip whose job left the list
    dub.JOBS["j1"] = dub.Job(id="j1", url="https://v.douyin.com/AbC123/", source_media_id="s", status="done", name="Mẹ bầu", board_id=7)
    dub.JOBS["j2"] = dub.Job(id="j2", url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", source_media_id=None, status="running", progress=40)
    dub.JOBS["j3"] = dub.Job(id="j3", url="https://www.tiktok.com/@a/video/7300000000000000001", source_media_id=None, status="error", error="Không tải được")
    with get_session() as s:
        s.add(Board(name="Clip bilibili", data={"quicktool": {"template_id": "dub", "dub": {
            "job_id": "gone", "snapshot": {"url": "https://www.bilibili.com/video/BV1xx411c7mD/?spm=1"}}}}))
        s.commit()
    lib_ = dub_links.library()
    by_url = {r["url"]: r for r in lib_["links"]}
    douyin = by_url["https://www.douyin.com/video/7570966119428452793"]
    assert douyin["status"] == "done" and douyin["job"]["job_id"] == "j1" and douyin["job"]["board_id"] == 7 and douyin["done_count"] == 1
    assert by_url["https://youtu.be/dQw4w9WgXcQ"]["status"] == "running"
    assert by_url["https://youtu.be/dQw4w9WgXcQ"]["job"]["progress"] == 40
    assert by_url["https://www.tiktok.com/@a/video/7300000000000000001"]["status"] == "error"
    assert by_url["https://www.tiktok.com/@a/video/7300000000000000001"]["error"] == "Không tải được"
    assert by_url["https://www.tiktok.com/@a/video/7300000000000000002"]["status"] == "new"
    assert by_url["https://www.bilibili.com/video/BV1xx411c7mD"]["status"] == "done"
    assert lib_["counts"] == {"done": 2, "running": 1, "error": 1, "new": 1}


def test_queued_links_feed_the_dub_queue_one_at_a_time(lib, monkeypatch):
    monkeypatch.setattr(dub, "status", lambda: {"available": True})
    started: list[dict] = []

    def fake_start(**kw):
        job = dub.Job(id=f"job{len(started)}", url=kw["url"], source_media_id=None, status="queued", voice=kw["voice"])
        dub.JOBS[job.id] = job
        started.append(kw)
        return job

    monkeypatch.setattr(dub, "start_job", fake_start)
    r = dub_links.import_texts([{"name": "a.txt", "text": "https://youtu.be/aaaaaaa\nhttps://youtu.be/bbbbbbb\nhttps://youtu.be/ccccccc"}])
    ids = r["added"]
    opts = {"voice": dub.tts.DEFAULT_VOICE, "keep_bgm": True, "style": "outline", "engine": "ass", "channel_id": 3, "auto_render": False}
    out = dub_links.queue([ids[2], ids[0], ids[1]], opts)  # picked in this order
    assert out["queued"] == 3 and out["started"] == "job0"
    assert started[0]["url"] == "https://youtu.be/ccccccc" and started[0]["keep_bgm"] is True
    assert started[0]["style"] == "outline" and started[0]["channel_id"] == 3 and started[0]["auto_render"] is False
    # one waits in the dub queue → the library holds the rest
    assert dub_links.feed() is None
    rows = {r["url"]: r for r in dub_links.library()["links"]}
    assert rows["https://youtu.be/ccccccc"]["status"] == "running" and rows["https://youtu.be/aaaaaaa"]["status"] == "waiting"
    assert dub_links.waiting_count() == 2
    # it starts running (nobody waits) → the next one goes in
    dub.JOBS["job0"].status = "running"
    assert dub_links.feed() == "job1" and started[1]["url"] == "https://youtu.be/aaaaaaa"
    # taken out of the queue before its turn → never starts
    assert dub_links.unqueue([ids[1]]) == 1
    dub.JOBS["job1"].status = "running"
    assert dub_links.feed() is None and len(started) == 2
    assert dub_links.waiting_count() == 0
    with get_session() as s:
        assert s.get(DubLink, ids[2]).job_id == "job0"
    # a link already running is not queued twice
    again = dub_links.queue([ids[2]], opts)
    assert again["queued"] == 0 and again["skipped"][0]["reason"] == "đang lồng tiếng"
    with pytest.raises(dub_links.LinkError):
        dub_links.queue([ids[1]], dict(opts, voice="nope"))
    # a link the dub download cannot take is listed, never queued
    shop = dub_links.import_texts([{"name": "b.txt", "text": "https://shopee.vn/sp-i.1.2"}])["added"]
    out = dub_links.queue(shop, opts)
    assert out["queued"] == 0 and out["skipped"][0]["reason"] == dub_links.NOT_VIDEO


def test_the_dub_queue_asks_the_library_when_nobody_waits(lib, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(dub, "FEEDER", lambda: calls.append(1))
    monkeypatch.setattr(dub, "_run_job", lambda job, render: None)
    dub._pump()
    assert calls == [1]
    dub.JOBS["w"] = dub.Job(id="w", url="https://youtu.be/x", source_media_id=None, status="queued")
    dub.JOBS["r"] = dub.Job(id="r", url="https://youtu.be/y", source_media_id=None, status="running")
    dub._pump()  # someone waits: the library is not asked
    assert calls == [1]


def test_routes_import_list_queue_and_delete(lib, client, monkeypatch):
    monkeypatch.setattr(dub, "status", lambda: {"available": True})
    monkeypatch.setattr(dub, "_pump", lambda: None)
    r = client.post("/api/dub/links/import", json={"files": [{"name": "list.txt", "text": NOTES}]})
    assert r.status_code == 200, r.text
    assert len(r.json()["added"]) == 4
    lib_ = client.get("/api/dub/links").json()
    assert lib_["total"] == 4 and lib_["counts"] == {"new": 2, "other": 2}  # shopee + example.com: not video links
    first = lib_["links"][0]["id"]
    q = client.post("/api/dub/links/queue", json={"ids": [first], "voice": dub.tts.DEFAULT_VOICE, "keep_bgm": False,
                                                  "style": "box_yellow", "engine": "ass", "auto_render": True})
    assert q.status_code == 200, q.text
    assert q.json()["queued"] == 1 and q.json()["started"]
    jid = q.json()["started"]
    try:
        assert dub.JOBS[jid].url == lib_["links"][0]["url"]
        assert client.get("/api/dub/links").json()["links"][0]["status"] == "running"
        assert client.post("/api/dub/links/queue", json={"ids": [first], "voice": "x"}).status_code == 400
        assert client.post("/api/dub/links/delete", json={"ids": [first]}).json() == {"deleted": 1}
        assert client.get("/api/dub/links").json()["total"] == 3
        assert jid in dub.JOBS  # the job made from it stays
    finally:
        dub.JOBS.pop(jid, None)
    assert client.post("/api/dub/links/import", json={"files": []}).status_code == 422
    # links waiting for their turn show on the "đang chạy" badge (the dub tool is busy / unavailable here)
    monkeypatch.setattr(dub, "status", lambda: {"available": False})
    second = client.get("/api/dub/links").json()["links"][0]["id"]
    client.post("/api/dub/links/queue", json={"ids": [second], "voice": dub.tts.DEFAULT_VOICE})
    items = client.get("/api/running").json()["items"]
    assert [i["detail"] for i in items if i["key"] == "dublinks:queue"] == ["1 link chờ đến lượt"]
    assert client.get("/api/running/outcome?key=dublinks:queue").json()["ok"] is True
