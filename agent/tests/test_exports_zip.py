"""Download several finished clips as one zip (and mark them downloaded)."""
import io
import zipfile

from flowboard.db import get_session
from flowboard.db.models import Asset, Board
from flowboard.routes.exports import slug
from flowboard.services import media as media_service


def test_slug_is_ascii_and_readable():
    assert slug("Cơm cháy siêu chà bông Bếp Chè Thái!") == "com-chay-sieu-cha-bong-bep-che-thai"
    assert slug("Đầm xoè 2 dây") == "dam-xoe-2-day"
    assert slug("  ") == "clip"


def test_zip_holds_each_finished_clip_and_marks_it_downloaded(client):
    media_service.MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ids = []
    for i, name in enumerate(("Cơm cháy — Quảng cáo thức ăn nhanh", "Áo thun — Quảng cáo quần áo")):
        b = client.post("/api/boards", json={"name": name}).json()
        mid = f"{i}" * 8 + "-2222-4222-8222-222222222222"
        (media_service.MEDIA_CACHE_DIR / f"{mid}.mp4").write_bytes(b"mp4-" + bytes([i]))
        client.post("/api/nodes", json={"board_id": b["id"], "type": "export", "data": {"mediaId": mid}})
        ids.append(b["id"])
    unfinished = client.post("/api/boards", json={"name": "Chưa ghép"}).json()["id"]

    r = client.get("/api/exports/zip", params={"ids": ",".join(map(str, ids + [unfinished]))})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["x-skipped-clips"] == str(unfinished)
    names = sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert len(names) == 2 and names[0].startswith("ao-thun_") and names[1].startswith("com-chay_")
    with get_session() as s:
        assert all((s.get(Board, i).data or {}).get("quicktool", {}).get("downloaded_at") for i in ids)
        assert not (s.get(Board, unfinished).data or {}).get("quicktool")
    assert client.get("/api/exports/zip", params={"ids": str(unfinished)}).status_code == 404
    assert client.get("/api/exports/zip", params={"ids": "x"}).status_code == 400
