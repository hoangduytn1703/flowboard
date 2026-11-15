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


def _wait(client, job_id, timeout=10):
    import time
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/exports/zip/jobs/{job_id}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("the save never ended")


def test_the_app_saves_the_zip_into_downloads_and_follows_it(client, monkeypatch):
    """The buttons do not build the whole zip before the first byte any more (ten clips ≈ 800 MB looked like a dead
    button, people clicked four times): the agent writes it into Downloads and the page follows the job."""
    import os
    from pathlib import Path

    from flowboard.services import zip_save

    media_service.MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    downloads = Path(os.environ["FLOWBOARD_DOWNLOADS_DIR"])
    ids = []
    for i, name in enumerate(("Cơm cháy — clip", "Áo thun — clip")):
        b = client.post("/api/boards", json={"name": name}).json()
        mid = f"{i + 5}" * 8 + "-2222-4222-8222-222222222222"
        (media_service.MEDIA_CACHE_DIR / f"{mid}.mp4").write_bytes(b"mp4-" + bytes([i]) * (3 * 1024 * 1024))
        client.post("/api/nodes", json={"board_id": b["id"], "type": "export", "data": {"mediaId": mid}})
        ids.append(b["id"])
    unfinished = client.post("/api/boards", json={"name": "Chưa ghép"}).json()["id"]

    monkeypatch.setattr(zip_save, "CHUNK", 1024 * 1024)
    first = client.post("/api/exports/zip/save", json={"ids": ids + [unfinished], "page": "/clips"}).json()
    again = client.post("/api/exports/zip/save", json={"ids": ids + [unfinished, ids[0]]}).json()
    assert again["id"] == first["id"] or again["status"] != "running"   # a second click joins the save under way
    done = _wait(client, first["id"])
    assert done["status"] == "done" and done["progress"] == 100 and done["clips"] == 2 and done["skipped"] == [unfinished]
    assert done["done_bytes"] == done["total_bytes"] > 6 * 1024 * 1024
    saved = downloads / done["name"]
    assert done["name"].startswith("DFlow_") and done["name"].endswith("_2clip.zip") and saved.is_file()
    assert not list(downloads.glob("*.part"))
    names = sorted(zipfile.ZipFile(saved).namelist())
    assert len(names) == 2 and names[0].startswith("ao-thun_") and names[1].startswith("com-chay_")
    with get_session() as s:
        assert all((s.get(Board, i).data or {}).get("quicktool", {}).get("downloaded_at") for i in ids)

    # the same clips once more: a new file next to the first, never over it
    second = _wait(client, client.post("/api/exports/zip/save", json={"ids": ids}).json()["id"])
    assert second["name"] != done["name"] and second["name"].endswith(" (2).zip") and saved.is_file()

    # nothing joined among them: an error the page can show
    nothing = _wait(client, client.post("/api/exports/zip/save", json={"ids": [unfinished]}).json()["id"])
    assert nothing["status"] == "error" and "Chưa có clip nào" in nothing["error"]
    assert client.post("/api/exports/zip/save", json={"ids": [0]}).status_code == 400
    assert client.get("/api/exports/zip/jobs/nope").status_code == 404

    # stopped halfway: no half file left behind
    monkeypatch.setattr(zip_save, "CHUNK", 64)
    before = set(downloads.iterdir())
    job = client.post("/api/exports/zip/save", json={"ids": ids[::-1]}).json()
    client.post(f"/api/exports/zip/jobs/{job['id']}/stop")
    stopped = _wait(client, job["id"], timeout=60)
    assert stopped["status"] == "stopped" and set(downloads.iterdir()) == before

    # the badge lists a running save and says how it ended
    assert client.get("/api/running/outcome", params={"key": f"zip:{done['id']}"}).json()["ok"] is True
    assert client.get("/api/running/outcome", params={"key": f"zip:{nothing['id']}"}).json()["ok"] is False
