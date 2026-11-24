""""Clip của tôi" lists only finished clips whose video plays on this machine: the summary says where each finished
video is (here / in the bucket / nowhere here — made in the desktop app's own data folder and never uploaded)."""
from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.services import file_store
from flowboard.services import media as media_service


def _clip(client, name, media_id, *, file_here):
    media_service.MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    b = client.post("/api/boards", json={"name": name}).json()
    path = media_service.MEDIA_CACHE_DIR / f"{media_id}.mp4"
    if file_here:
        path.write_bytes(b"mp4")
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(path), mime="video/mp4"))
        s.commit()
    client.post("/api/nodes", json={"board_id": b["id"], "type": "export", "data": {"mediaId": media_id}})
    return b["id"]


def _states(client):
    return {b["id"]: b["summary"]["video"] for b in client.get("/api/boards", params={"summary": True}).json()}


def test_the_library_knows_which_finished_videos_play_here(client, monkeypatch):
    here = _clip(client, "Có trên máy", "a" * 32, file_here=True)
    away = _clip(client, "Làm ở app cài", "b" * 32, file_here=False)
    draft = client.post("/api/boards", json={"name": "Đang làm"}).json()["id"]

    # no bucket: a video not on this machine cannot be fetched from anywhere
    states = _states(client)
    assert states[here] == "here" and states[away] == "missing" and states[draft] is None

    # a bucket not listed yet: unknown, so the clip stays (the page may still fetch it)
    monkeypatch.setattr(file_store, "enabled", lambda: True)
    monkeypatch.setattr(file_store, "prefix", lambda: "akira/")
    monkeypatch.setattr(file_store, "_listed", False)
    assert _states(client)[away] == "cloud"

    # listed: in it → cloud; not in it (every upload refused, a full bucket) → missing
    monkeypatch.setattr(file_store, "_listed", True)
    monkeypatch.setattr(file_store, "_remote_keys", {f"akira/media/{'b' * 32}.mp4"})
    assert _states(client)[away] == "cloud"
    monkeypatch.setattr(file_store, "_remote_keys", set())
    assert _states(client)[away] == "missing"

    # a fetch that just failed counts as missing too (the media route remembers it a few minutes)
    monkeypatch.setattr(file_store, "_remote_keys", {f"akira/media/{'b' * 32}.mp4"})
    media_service.remember_miss("b" * 32)
    try:
        assert _states(client)[away] == "missing"
    finally:
        media_service.forget_miss("b" * 32)
