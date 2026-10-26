"""GET /api/running: the floating "đang chạy" badge's feed."""
from datetime import datetime, timedelta, timezone

from flowboard.db import get_session
from flowboard.db.models import Request
from flowboard.services import dub, video_clean


def _node_on_new_board(client, name="Clip A"):
    board = client.post("/api/boards", json={"name": name}).json()
    node = client.post("/api/nodes", json={"board_id": board["id"], "type": "video", "x": 0, "y": 0, "data": {}}).json()
    return board["id"], node["id"]


def _req(node_id, typ, status, age_min=1):
    with get_session() as s:
        r = Request(node_id=node_id, type=typ, status=status, params={},
                    created_at=datetime.now(timezone.utc) - timedelta(minutes=age_min))
        s.add(r)
        s.commit()


def test_flow_work_is_grouped_per_clip_and_links_to_the_right_step(client, monkeypatch):
    monkeypatch.setattr(dub, "load_jobs", lambda: None)
    bid, nid = _node_on_new_board(client)
    _req(nid, "gen_video_omni", "running")
    _req(nid, "gen_video_omni", "queued")
    _req(nid, "gen_image", "done")              # finished: not shown
    _req(None, "gen_image", "running")          # a post's image: no clip
    _req(nid, "auto_prompt", "running")         # LLM call: not badge-worthy
    _req(nid, "gen_image", "running", age_min=300)  # stale orphan: ignored
    items = client.get("/api/running").json()["items"]
    clip = next(i for i in items if i["kind"] == "clip")
    assert clip["title"] == "Clip A" and clip["link"] == f"/clips/{bid}/videos"
    assert "2 video" in clip["detail"] and "ảnh" not in clip["detail"]
    other = next(i for i in items if i["kind"] == "flow")
    assert other["link"] == "/history" and "1 ảnh" in other["detail"]
    assert len(items) == 2


def test_dub_and_clean_jobs_link_back_to_their_tool(client, monkeypatch):
    monkeypatch.setattr(dub, "load_jobs", lambda: None)
    job = dub.Job(id="dubjob1", url="https://v.douyin.com/x/", source_media_id=None, name="Mẹ bầu tập thể dục",
                  status="running", phase="Đang tạo giọng đọc (3/40)", progress=66)
    done = dub.Job(id="dubjob2", url=None, source_media_id="m", status="done")
    dub.JOBS.update({job.id: job, done.id: done})
    cj = video_clean.Job(id="cleanjob1", source_media_id="m2")
    cj.status, cj.progress = "running", 40
    video_clean.JOBS[cj.id] = cj
    try:
        items = {i["key"]: i for i in client.get("/api/running").json()["items"]}
        assert items["dub:dubjob1"]["link"] == "/tools/dub?job=dubjob1" and items["dub:dubjob1"]["progress"] == 66
        assert items["dub:dubjob1"]["detail"].startswith("Đang tạo giọng đọc")
        assert "dub:dubjob2" not in items
        assert items["clean:cleanjob1"]["link"] == "/tools/clean?job=cleanjob1" and items["clean:cleanjob1"]["progress"] == 40
    finally:
        for k in ("dubjob1", "dubjob2"):
            dub.JOBS.pop(k, None)
        video_clean.JOBS.pop("cleanjob1", None)


def test_nothing_running_is_an_empty_list(client, monkeypatch):
    monkeypatch.setattr(dub, "load_jobs", lambda: None)
    assert client.get("/api/running").json() == {"items": []}


def test_outcome_tells_done_from_failed(client, monkeypatch):
    monkeypatch.setattr(dub, "load_jobs", lambda: None)
    bad = dub.Job(id="dubbad", url=None, source_media_id="m", status="error", error="edge-tts failed: No audio")
    good = dub.Job(id="dubgood", url=None, source_media_id="m", status="done")
    dub.JOBS.update({bad.id: bad, good.id: good})
    try:
        assert client.get("/api/running/outcome", params={"key": "dub:dubbad"}).json() == {"ok": False, "message": "edge-tts failed: No audio"}
        assert client.get("/api/running/outcome", params={"key": "dub:dubgood"}).json()["ok"] is True
    finally:
        dub.JOBS.pop("dubbad", None); dub.JOBS.pop("dubgood", None)
    bid, nid = _node_on_new_board(client, "Clip B")
    assert client.get("/api/running/outcome", params={"key": f"clip:{bid}"}).json()["ok"] is True
    _req(nid, "gen_video_omni", "failed")
    out = client.get("/api/running/outcome", params={"key": f"clip:{bid}"}).json()
    assert out["ok"] is False and "1 việc Flow bị lỗi" in out["message"]


# ── in-page operations (services/op_tracker + the _track_long_ops middleware) ──

def test_tracker_matches_long_requests_and_links_back_to_the_page():
    from flowboard.services import op_tracker

    rule, groups = op_tracker.match("POST", "/api/channels/7/review")
    assert rule.kind == "channel" and groups == ("7",)
    assert op_tracker.match("GET", "/api/channels/7/review") is None
    assert op_tracker.match("POST", "/api/posts") is None  # a plain save is not long
    assert op_tracker.link_from("http://localhost:5174/clips/21/script?x=1", "/clips") == "/clips/21/script?x=1"
    assert op_tracker.link_from(None, "/channels?id=7") == "/channels?id=7"
    assert op_tracker.link_from("http://localhost:5174/", "/posts") == "/posts"


def test_a_running_op_shows_on_the_badge_and_keeps_its_outcome(client, monkeypatch):
    from flowboard.services import op_tracker

    monkeypatch.setattr(dub, "load_jobs", lambda: None)
    op_tracker.reset()
    rule, groups = op_tracker.match("POST", "/api/products/from-link")
    op = op_tracker.start(rule, groups, "http://localhost:5174/products")
    items = client.get("/api/running").json()["items"]
    assert [i["title"] for i in items] == ["Đang đọc sản phẩm từ link"] and items[0]["link"] == "/products"
    op_tracker.finish(op, False, "Trang chặn đọc")
    assert client.get("/api/running").json()["items"] == []
    assert client.get("/api/running/outcome", params={"key": f"op:{op.id}"}).json() == {"ok": False, "message": "Trang chặn đọc"}


def test_middleware_tracks_a_post_write_and_keeps_the_result_for_the_page(client, monkeypatch):
    import json as _json

    from flowboard.services import op_tracker, post_writer

    op_tracker.reset()

    async def fake_llm(*a, **k):
        return _json.dumps({"reply": "ok", "body": "Bài AI viết", "hashtags": ["#a"], "image_prompts": []})

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    ch = client.post("/api/channels", json={"name": "Page", "platforms": ["facebook"]}).json()["id"]
    r = client.post("/api/posts/write", json={"brief": {"kind": "review"}, "channel_id": ch},
                    headers={"Referer": "http://localhost:5174/posts"})
    assert r.status_code == 200 and r.json()["post"]["body"] == "Bài AI viết"  # the answer still reaches the page
    got = client.get("/api/running/latest", params={"kind": "post_write", "claim": "true"}).json()
    assert got["status"] == "done" and got["result"]["post"]["body"] == "Bài AI viết"
    assert client.get("/api/running/latest", params={"kind": "post_write"}).json() == {}  # claimed: shown once
    # a refused write is recorded as an error with its message
    bad = client.post("/api/posts/write", json={"brief": {"kind": "review"}})
    assert bad.status_code == 400
    err = client.get("/api/running/latest", params={"kind": "post_write"}).json()
    assert err["status"] == "error" and "kênh" in err["message"].lower()
