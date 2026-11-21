"""Low-disk warning (cheap check) and per-clip storage scan (stats only files
already on this machine, never downloads from the cloud)."""
from pathlib import Path

from flowboard import config
from flowboard.db import get_session
from flowboard.db.models import Asset


def test_disk_status_reports_free_space_on_the_data_drive(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    row = client.get("/api/boards/disk-status").json()
    assert row["total"] > 0 and row["free"] >= 0
    assert isinstance(row["low"], bool)


def test_disk_status_warns_below_the_threshold(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    import flowboard.routes.boards as boards_route

    monkeypatch.setattr(boards_route, "LOW_DISK_BYTES", 10 ** 15)  # bigger than any real free space
    assert client.get("/api/boards/disk-status").json()["low"] is True


def test_storage_scan_sums_each_clips_own_files_and_ignores_missing_ones(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    # Clip 1: one image on this machine (500 bytes).
    bid1 = client.post("/api/boards", json={"name": "clip 1"}).json()["id"]
    client.post("/api/nodes", json={"board_id": bid1, "type": "image", "data": {"mediaId": "m1"}})
    f1 = tmp_path / "a.jpg"
    f1.write_bytes(b"x" * 500)
    # Clip 2: one video on this machine (1200 bytes) + one export row whose file is NOT on this
    # machine (lives only in the cloud) — that one must count as 0, not error out.
    bid2 = client.post("/api/boards", json={"name": "clip 2"}).json()["id"]
    client.post("/api/nodes", json={"board_id": bid2, "type": "video", "data": {"mediaId": "m2"}})
    client.post("/api/nodes", json={"board_id": bid2, "type": "export", "data": {"mediaId": "m3"}})
    f2 = tmp_path / "b.mp4"
    f2.write_bytes(b"y" * 1200)
    missing = tmp_path / "gone.mp4"  # registered in the DB, but the file itself was never written
    with get_session() as s:
        s.add(Asset(kind="image", uuid_media_id="m1", local_path=str(f1)))
        s.add(Asset(kind="video", uuid_media_id="m2", local_path=str(f2)))
        s.add(Asset(kind="video", uuid_media_id="m3", local_path=str(missing)))
        s.commit()

    row = client.post("/api/boards/storage-scan").json()
    assert row["by_board"][str(bid1)] == 500
    assert row["by_board"][str(bid2)] == 1200  # the missing file added 0, not an error
    assert row["total_clips_bytes"] == 1700
    assert row["total"] > 0
