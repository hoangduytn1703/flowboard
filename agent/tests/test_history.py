"""/api/history — projection, filters, pagination, summary, credit estimate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flowboard.db import get_session
from flowboard.db.models import Board, Node, Request
from flowboard.routes import history as history_route


def _mount():
    from flowboard.main import app
    if not any(getattr(r, "path", "").startswith("/api/history") for r in app.routes):
        app.include_router(history_route.router)


def _seed() -> dict:
    """One board, two nodes, six requests of assorted types / statuses."""
    with get_session() as s:
        board = Board(name="Son môi — clip 1")
        s.add(board)
        s.commit()
        s.refresh(board)
        img = Node(board_id=board.id, short_id="c1", type="image",
                   data={"title": "Cảnh 1", "prompt": "A model holding a red lipstick, studio light"})
        vid = Node(board_id=board.id, short_id="v1", type="video", data={"title": "Video 1"})
        s.add(img)
        s.add(vid)
        s.commit()
        s.refresh(img)
        s.refresh(vid)
        now = datetime.now(timezone.utc)
        rows = [
            Request(node_id=img.id, type="gen_image", status="done",
                    params={"prompt": "A model holding a red lipstick, studio light " + "x" * 120,
                            "variant_count": 2},
                    result={"media_ids": ["m-img-1", "m-img-2"]},
                    created_at=now - timedelta(seconds=30), finished_at=now - timedelta(seconds=20)),
            Request(node_id=vid.id, type="gen_video", status="done",
                    params={"prompt": "camera pans slowly", "video_quality": "fast"},
                    result={"media_entries": [{"media_id": "m-vid-1"}]},
                    created_at=now - timedelta(seconds=15), finished_at=now - timedelta(seconds=5)),
            Request(node_id=vid.id, type="gen_video_omni", status="failed",
                    params={"prompt": "omni shot", "duration_s": 8},
                    result={}, error="PUBLIC_ERROR_UNSAFE_GENERATION",
                    created_at=now - timedelta(seconds=10), finished_at=now - timedelta(seconds=8)),
            Request(node_id=None, type="export_video", status="done",
                    params={"items": [{"media_id": "m-vid-1", "narration": "Son lì mịn môi cả ngày"}]},
                    result={"media_ids": ["m-export-1"]},
                    created_at=now - timedelta(seconds=6), finished_at=now - timedelta(seconds=1)),
            Request(node_id=None, type="vision", status="running", params={"media_id": "m-img-1"},
                    created_at=now - timedelta(seconds=2)),
            # Eight days old: outside both the "today" and "week" buckets.
            Request(node_id=img.id, type="gen_video", status="timeout",
                    params={"video_quality": "quality"},
                    created_at=now - timedelta(days=8), finished_at=now - timedelta(days=8, seconds=-300)),
        ]
        for r in rows:
            s.add(r)
        s.commit()
        for r in rows:
            s.refresh(r)
        return {"board_id": board.id, "img": img.id, "vid": vid.id, "ids": [r.id for r in rows]}


def test_list_projection(client):
    _mount()
    seed = _seed()
    r = client.get("/api/history")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["next_before_id"] is None
    items = body["items"]
    assert [it["id"] for it in items] == sorted(seed["ids"], reverse=True)
    by_type = {it["type"]: it for it in items if it["id"] != seed["ids"][-1]}

    img = by_type["gen_image"]
    assert img["type_label_vi"] == "Tạo ảnh"
    assert img["board"] == {"id": seed["board_id"], "name": "Son môi — clip 1"}
    assert img["node"] == {"id": seed["img"], "short_id": "c1", "title": "Cảnh 1", "type": "image"}
    assert img["media_ids"] == ["m-img-1", "m-img-2"] and img["thumbnail"] == "m-img-1"
    assert img["summary"].endswith("…") and len(img["summary"]) <= history_route.SUMMARY_CHARS
    assert img["credits_estimate"] == 0 and img["can_retry"] is True
    assert img["duration_ms"] == 10_000 and img["created_at"].endswith("Z")
    assert "params" not in img and "result" not in img

    vid = by_type["gen_video"]
    assert vid["media_ids"] == ["m-vid-1"] and vid["credits_estimate"] == history_route.VEO_CREDITS["fast"]

    omni = by_type["gen_video_omni"]
    assert omni["status"] == "failed" and omni["error"] == "PUBLIC_ERROR_UNSAFE_GENERATION"
    assert omni["credits_estimate"] == 12 and omni["thumbnail"] is None and omni["can_retry"] is True

    exp = by_type["export_video"]
    assert exp["board"] is None and exp["node"] is None and exp["can_retry"] is False
    assert exp["summary"] == "Son lì mịn môi cả ngày" and exp["credits_estimate"] == 0

    vision = by_type["vision"]
    assert vision["type_label_vi"] == "Đọc ảnh (AI)" and vision["duration_ms"] is None


def test_filters(client):
    _mount()
    seed = _seed()
    types = {it["type"] for it in client.get("/api/history", params={"type": "gen_video,gen_image"}).json()["items"]}
    assert types == {"gen_video", "gen_image"}

    err = client.get("/api/history", params={"status": "error"}).json()["items"]
    assert sorted(it["status"] for it in err) == ["failed", "timeout"]
    assert {it["status"] for it in client.get("/api/history", params={"status": "done"}).json()["items"]} == {"done"}

    on_board = client.get("/api/history", params={"board_id": seed["board_id"]}).json()["items"]
    assert len(on_board) == 4 and all(it["board"]["id"] == seed["board_id"] for it in on_board)
    assert client.get("/api/history", params={"board_id": 999}).status_code == 404

    with get_session() as s:
        empty = Board(name="Trống")
        s.add(empty)
        s.commit()
        s.refresh(empty)
        empty_id = empty.id
    assert client.get("/api/history", params={"board_id": empty_id}).json() == {"items": [], "next_before_id": None}


def test_pagination_cursor(client):
    _mount()
    seed = _seed()
    ids_desc = sorted(seed["ids"], reverse=True)
    page1 = client.get("/api/history", params={"limit": 4}).json()
    assert [it["id"] for it in page1["items"]] == ids_desc[:4]
    assert page1["next_before_id"] == ids_desc[3]
    page2 = client.get("/api/history", params={"limit": 4, "before_id": page1["next_before_id"]}).json()
    assert [it["id"] for it in page2["items"]] == ids_desc[4:]
    assert page2["next_before_id"] is None
    # Exactly `limit` rows left must not promise another page.
    exact = client.get("/api/history", params={"limit": 2, "before_id": ids_desc[3]}).json()
    assert len(exact["items"]) == 2 and exact["next_before_id"] is None


def test_summary_counts(client):
    _mount()
    _seed()
    body = client.get("/api/history/summary").json()
    today = body["today"]
    assert today["jobs"] == 5 and today["done"] == 3 and today["error"] == 1
    # Veo fast + omni 8 s (failed jobs still spent credits); images/export/vision are free.
    assert today["credits_estimate"] == history_route.VEO_CREDITS["fast"] + 12
    assert body["week"] == today
    assert body["total_media"] == 4  # 2 images + 1 video + 1 export


def test_detail_and_404(client):
    _mount()
    seed = _seed()
    rid = seed["ids"][0]
    r = client.get(f"/api/history/{rid}")
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == rid and d["params"]["variant_count"] == 2
    assert d["result"]["media_ids"] == ["m-img-1", "m-img-2"]
    assert client.get("/api/history/999999").status_code == 404


def test_credits_estimate_table():
    ce = history_route.credits_estimate
    assert ce("gen_video", {}) == history_route.VEO_CREDITS["fast"]
    assert ce("gen_video", {"video_quality": "quality", "variant_count": 2}) == 200
    assert ce("gen_video", {"video_quality": "fast_relaxed"}) == 0
    assert ce("gen_video", {"video_quality": "weird"}) is None
    assert ce("gen_video_omni", {"duration_s": 4}) == 6
    assert ce("gen_video_omni", {}) == 12
    assert ce("gen_video_omni", {"duration_s": 99}) is None
    assert ce("gen_image", {}) == 0 and ce("mystery_type", {}) is None


def test_media_ids_shapes():
    m = history_route.media_ids_of
    assert m({"media_ids": ["a", "b"], "media_entries": [{"media_id": "b"}, {"media_id": "c"}]}) == ["a", "b", "c"]
    assert m({"media_id": "solo"}) == ["solo"]
    assert m({"media_ids": "not-a-list"}) == [] and m(None) == []
