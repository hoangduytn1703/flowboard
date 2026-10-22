"""Asset paths are stored relative to the data folder and resolved per machine."""
from pathlib import Path

from sqlmodel import select

from flowboard import config
from flowboard.db import engine, get_session
from flowboard.db import paths
from flowboard.db.models import Asset


def test_round_trip_is_relative_in_the_db_and_absolute_in_python():
    p = Path(config.STORAGE_DIR) / "media" / "abc.mp4"
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id="a" * 32, local_path=str(p)))
        s.commit()
    with engine.connect() as conn:
        raw = conn.exec_driver_sql("SELECT local_path FROM asset").scalar()
    assert raw == "media/abc.mp4"
    with get_session() as s:
        row = s.exec(select(Asset)).first()
    assert Path(row.local_path) == p


def test_old_absolute_paths_from_another_machine_resolve_here():
    here = Path(config.STORAGE_DIR)
    assert Path(paths.from_stored(r"D:\codes\flow-AI\flowboard\storage\media\x.png")) == here / "media" / "x.png"
    assert Path(paths.from_stored("/home/duy/flowboard/storage/media/tts/a.wav")) == here / "media" / "tts" / "a.wav"
    assert paths.to_stored(str(here / "chat_uploads" / "1" / "a.png")) == "chat_uploads/1/a.png"
    # Outside the data folder a written path stays absolute (only reads use the marker fallback).
    assert paths.to_stored(r"C:\Users\Admin\x\chat_uploads\1\a.png") == r"C:\Users\Admin\x\chat_uploads\1\a.png"
    assert paths.to_stored(None) is None and paths.from_stored("") == ""
    assert paths.to_stored(r"E:\elsewhere\clip.mp4") == r"E:\elsewhere\clip.mp4"


def test_normalize_rewrites_rows_whose_file_exists_here():
    media = Path(config.STORAGE_DIR) / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / "keep.png").write_bytes(b"x")
    with engine.connect() as conn:
        conn.exec_driver_sql("INSERT INTO asset (kind, uuid_media_id, local_path, created_at) VALUES ('image', 'k1', ?, '2026-10-21 00:00:00')",
                             (r"D:\old\storage\media\keep.png",))
        conn.exec_driver_sql("INSERT INTO asset (kind, uuid_media_id, local_path, created_at) VALUES ('image', 'k2', ?, '2026-10-21 00:00:00')",
                             (r"D:\old\storage\media\gone.png",))
        conn.commit()
    assert paths.normalize_asset_paths(engine) == 1
    with engine.connect() as conn:
        got = dict(conn.exec_driver_sql("SELECT uuid_media_id, local_path FROM asset").fetchall())
    assert got["k1"] == "media/keep.png" and got["k2"] == r"D:\old\storage\media\gone.png"
