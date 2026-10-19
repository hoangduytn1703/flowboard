"""Storyboard composite → scene nodes: the cropper trims margins and
captions, and the route uploads every tile and wires image + video
nodes behind the storyboard."""
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageStat
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import BoardFlowProject, Edge, Node
from flowboard.routes import storyboard as storyboard_route
from flowboard.routes import upload as upload_route
from flowboard.services import media as media_service
from flowboard.services.storyboard_split import split_composite

PID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
COLOURS = [(200, 40, 40), (40, 160, 60), (40, 60, 200), (120, 40, 160)]


def _composite(tmp_path: Path, size=(800, 800), rows=2, cols=2) -> tuple[Path, list[tuple]]:
    """White canvas, rows×cols coloured rectangles with white gutters, a
    number label inside each and a few thin dark "text" lines below.
    Returns the file and each rectangle's (left, top, right, bottom)."""
    W, H = size
    cw, ch = W // cols, H // rows
    im = Image.new("RGB", size, (255, 255, 255))
    d = ImageDraw.Draw(im)
    boxes = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * cw, r * ch
            # picture: 6 % side gutters, 6 % top gutter, 22 % bottom margin for text
            l, t = x0 + round(cw * 0.06), y0 + round(ch * 0.06)
            rt, b = x0 + round(cw * 0.94), y0 + round(ch * 0.72)
            d.rectangle((l, t, rt - 1, b - 1), fill=COLOURS[(r * cols + c) % len(COLOURS)])
            d.text((l + 6, t + 4), str(r * cols + c + 1), fill=(255, 255, 255))
            # caption: 3 thin dark lines in the margin, sparse like text
            for k in range(3):
                y = b + round(ch * 0.06) + k * 6
                for x in range(l + 10, rt - 10, 7):
                    d.line((x, y, x + 3, y), fill=(20, 20, 20))
            boxes.append((l, t, rt, b))
    path = tmp_path / "composite.png"
    im.save(path)
    return path, boxes


def test_split_trims_gutters_and_captions(tmp_path):
    path, boxes = _composite(tmp_path)
    panels = split_composite(path, 2, 2)
    assert len(panels) == 4
    for raw, (l, t, rt, b), colour in zip(panels, boxes, COLOURS):
        with Image.open(io.BytesIO(raw)) as p:
            assert p.format == "PNG"
            w, h = p.size
            # within 3 % of the coloured rectangle on both axes
            assert abs(w - (rt - l)) <= 0.03 * (rt - l), (w, rt - l)
            assert abs(h - (b - t)) <= 0.03 * (b - t), (h, b - t)
            mean = ImageStat.Stat(p.convert("RGB")).mean
        # a slice of gutter or caption would pull the mean toward white
        assert all(abs(m - c) < 12 for m, c in zip(mean, colour)), (mean, colour)


def test_split_falls_back_to_inset_cell_on_blank_tile(tmp_path):
    im = Image.new("RGB", (400, 200), (255, 255, 255))
    path = tmp_path / "blank.png"
    im.save(path)
    panels = split_composite(path, 1, 2)
    assert len(panels) == 2
    with Image.open(io.BytesIO(panels[0])) as p:
        assert p.size == (188, 188)  # 200 px cell minus a 3 % inset each side


def test_split_reading_order_for_portrait_layout(tmp_path):
    path, boxes = _composite(tmp_path, size=(600, 900), rows=3, cols=2)
    panels = split_composite(path, 3, 2)
    assert len(panels) == 6
    for raw, (l, t, rt, b) in zip(panels, boxes):
        with Image.open(io.BytesIO(raw)) as p:
            assert abs(p.size[0] - (rt - l)) <= 0.03 * (rt - l)
            assert abs(p.size[1] - (b - t)) <= 0.03 * (b - t)


def test_resolve_layout_matches_frontend():
    assert storyboard_route.resolve_layout("2x2", "IMAGE_ASPECT_RATIO_PORTRAIT") == (2, 2)
    assert storyboard_route.resolve_layout("2x3", "IMAGE_ASPECT_RATIO_LANDSCAPE") == (2, 3)
    assert storyboard_route.resolve_layout("2x3", "IMAGE_ASPECT_RATIO_PORTRAIT") == (3, 2)
    assert storyboard_route.resolve_layout("2x4", None) == (2, 4)
    assert storyboard_route.resolve_layout("3x3", None) == (2, 2)  # legacy → 2x2


# ── route ──────────────────────────────────────────────────────────────────

def _board_with_storyboard(client, tmp_path, grid="2x2", aspect="IMAGE_ASPECT_RATIO_LANDSCAPE"):
    board = client.post("/api/boards", json={"name": "SB"}).json()
    mid = "11111111-2222-4333-8444-555555555555"
    path, _ = _composite(tmp_path)
    (media_service.MEDIA_CACHE_DIR / f"{mid}.png").write_bytes(path.read_bytes())
    model = client.post("/api/nodes", json={"board_id": board["id"], "type": "character"}).json()
    product = client.post("/api/nodes", json={"board_id": board["id"], "type": "visual_asset"}).json()
    sb = client.post("/api/nodes", json={
        "board_id": board["id"], "type": "Storyboard", "status": "done",
        "data": {"mediaId": mid, "storyboardGrid": grid, "aspectRatio": aspect},
    }).json()
    for src in (model, product):
        client.post("/api/edges", json={"board_id": board["id"], "source_id": src["id"], "target_id": sb["id"]})
    with get_session() as s:
        s.add(BoardFlowProject(board_id=board["id"], flow_project_id=PID))
        s.commit()
    return board, sb, model, product


def test_split_route_creates_scene_and_video_nodes(client, tmp_path, monkeypatch):
    board, sb, model, product = _board_with_storyboard(client, tmp_path)
    uploads: list[tuple] = []

    async def fake_ingest(raw, mime, project_id, file_name, node_id):
        uploads.append((mime, project_id, file_name, node_id))
        assert raw.startswith(b"\x89PNG")
        return {"media_id": f"mid{len(uploads)}"}

    monkeypatch.setattr(upload_route, "_ingest_image_bytes", fake_ingest)

    r = client.post(f"/api/nodes/{sb['id']}/storyboard/split")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["storyboard"] == sb["short_id"]
    assert (body["panels"], body["rows"], body["cols"]) == (4, 2, 2)
    assert set(body["nodes"]) == {f"s{i}" for i in range(1, 5)} | {f"v{i}" for i in range(1, 5)}
    assert [u[2] for u in uploads] == [f"scene{i}.png" for i in range(1, 5)]
    assert all(u[1] == PID and u[0] == "image/png" for u in uploads)

    with get_session() as s:
        nodes = {n.short_id: n for n in s.exec(select(Node).where(Node.board_id == board["id"])).all()}
        edges = s.exec(select(Edge).where(Edge.board_id == board["id"])).all()
    by_id = {n.id: n for n in nodes.values()}
    pairs = {(by_id[e.source_id].short_id, by_id[e.target_id].short_id) for e in edges}
    for i in range(1, 5):
        img, vid = nodes[body["nodes"][f"s{i}"]], nodes[body["nodes"][f"v{i}"]]
        assert img.type == "image" and img.status == "done"
        assert img.data["mediaId"] == f"mid{i}" and img.data["mediaIds"] == [f"mid{i}"]
        assert img.data["title"] == f"Cảnh {i}" and img.data["panelIndex"] == i
        assert img.data["fromStoryboard"] == sb["short_id"]
        assert img.data["aspectRatio"] == "IMAGE_ASPECT_RATIO_LANDSCAPE"
        assert vid.type == "video" and vid.status == "idle" and vid.data["title"] == f"Video {i}"
        assert (sb["short_id"], img.short_id) in pairs
        assert (img.short_id, vid.short_id) in pairs
        # the model and the product feed every video, not the scene images
        assert (model["short_id"], vid.short_id) in pairs
        assert (product["short_id"], vid.short_id) in pairs
        assert (model["short_id"], img.short_id) not in pairs
    # 2 originals + storyboard + 4 images + 4 videos
    assert len(nodes) == 11


def test_split_route_rejects_non_storyboard_and_missing(client, tmp_path):
    board = client.post("/api/boards", json={"name": "SB"}).json()
    img = client.post("/api/nodes", json={"board_id": board["id"], "type": "image",
                                          "data": {"mediaId": "11111111-2222-4333-8444-555555555555"}}).json()
    assert client.post(f"/api/nodes/{img['id']}/storyboard/split").status_code == 400
    empty = client.post("/api/nodes", json={"board_id": board["id"], "type": "Storyboard"}).json()
    assert client.post(f"/api/nodes/{empty['id']}/storyboard/split").status_code == 400
    assert client.post("/api/nodes/99999/storyboard/split").status_code == 404


def test_split_route_upload_failure_is_502_and_creates_nothing(client, tmp_path, monkeypatch):
    board, sb, _m, _p = _board_with_storyboard(client, tmp_path)

    async def boom(raw, mime, project_id, file_name, node_id):
        raise RuntimeError("extension offline")

    monkeypatch.setattr(upload_route, "_ingest_image_bytes", boom)
    r = client.post(f"/api/nodes/{sb['id']}/storyboard/split")
    assert r.status_code == 502 and "extension offline" in r.json()["detail"]
    with get_session() as s:
        assert len(s.exec(select(Node).where(Node.board_id == board["id"])).all()) == 3
