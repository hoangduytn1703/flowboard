"""60 fps made in the background as each scene clip lands (services/smooth_prewarm, 7/11): who wants it (the export
node, else the account's last choice), the warm-up itself (real ffmpeg), the status for the checkbox, and the join
using the copies made ahead instead of smoothing again."""
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from flowboard.db import get_session
from flowboard.db.models import AppSetting, Asset
from flowboard.services import smooth_prewarm, video_export, video_watermark

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or shutil.which("ffprobe") is None, reason="ffmpeg not installed")


def _board(client) -> int:
    return client.post("/api/boards", json={"name": "Clip 60fps"}).json()["id"]


def _node(client, board_id: int, type_: str, data: dict) -> int:
    nid = client.post("/api/nodes", json={"board_id": board_id, "type": type_}).json()["id"]
    client.patch(f"/api/nodes/{nid}", json={"data": data})
    return nid


def _prefs(**kv) -> None:
    with get_session() as s:
        row = s.get(AppSetting, "ui_prefs")
        value = json.dumps(kv)
        if row is None:
            s.add(AppSetting(key="ui_prefs", value=value))
        else:
            row.value = value
            s.add(row)
        s.commit()


def _wait_jobs(timeout: float = 120.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if all(j.done() for j in smooth_prewarm._jobs.values()):
            return
        time.sleep(0.2)
    raise AssertionError("warm-up did not finish")


def test_who_wants_60fps(client):
    b = _board(client)
    _prefs(smooth60=False)
    assert smooth_prewarm.board_wants(b) is False
    _prefs(smooth60=True)
    assert smooth_prewarm.board_wants(b) is True  # no export node yet: the account's last choice
    exp = _node(client, b, "export", {"smooth60": False})
    assert smooth_prewarm.board_wants(b) is False  # the clip's own choice wins
    client.patch(f"/api/nodes/{exp}", json={"data": {"smooth60": True}})
    assert smooth_prewarm.board_wants(b) is True


def test_a_finished_clip_is_warmed_only_when_its_board_wants_it(client, monkeypatch):
    b = _board(client)
    v = _node(client, b, "video", {"mediaId": "m-1"})
    warmed = []
    monkeypatch.setattr(smooth_prewarm, "warm", lambda mid: warmed.append(mid))
    _node(client, b, "export", {"smooth60": False})
    smooth_prewarm.after_clip(v, "m-1")
    assert warmed == []
    other = _board(client)
    v2 = _node(client, other, "video", {"mediaId": "m-2"})
    _node(client, other, "export", {"smooth60": True})
    smooth_prewarm.after_clip(v2, "m-2")
    smooth_prewarm.after_clip(None, "m-3")  # a picture without a node: nothing
    assert warmed == ["m-2"]


@needs_ffmpeg
def test_warm_up_then_the_join_uses_the_copy(client, tmp_path, monkeypatch):
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path / "media")
    monkeypatch.setattr(video_export.config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(video_watermark, "turned_on", lambda: False)  # a plain clip: no stamp step
    (tmp_path / "media").mkdir()
    mids, aids = [], []
    for i in range(2):
        mid = str(uuid.uuid4())
        f = tmp_path / "media" / f"{mid}.mp4"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x284:rate=24:duration=0.5",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(f)], check=True)
        with get_session() as s:
            a = Asset(kind="video", uuid_media_id=mid, local_path=str(f))
            s.add(a)
            s.commit()
            s.refresh(a)
            aids.append(a.id)
        mids.append(mid)
    b = _board(client)
    for mid in mids:
        _node(client, b, "video", {"mediaId": mid})
    _node(client, b, "export", {"smooth60": True})
    smooth_prewarm._jobs.clear()
    assert client.get(f"/api/boards/{b}/smooth60").json() == {"total": 2, "ready": 0, "running": 0}
    started = client.post(f"/api/boards/{b}/smooth60").json()
    assert started["total"] == 2
    _wait_jobs()
    assert client.get(f"/api/boards/{b}/smooth60").json() == {"total": 2, "ready": 2, "running": 0}
    assert len(list((tmp_path / "media" / "smooth60").glob("*.60.mp4"))) == 2
    calls = []
    monkeypatch.setattr(video_export, "smooth_to_60fps", lambda *a, **k: calls.append(a) or "should not run")
    wav = tmp_path / "line.wav"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3", str(wav)], check=True)
    from flowboard.services import tts

    monkeypatch.setattr(video_export, "_synth_to_fit", lambda text, opts, dur, voice=None: (tts.Narration(path=wav, duration=0.3, words=[]), 0))
    monkeypatch.setattr(video_export, "_prefetch_voices", lambda lines, opts: None)
    media, err, report = video_export.export_video(aids, smooth60=True, narration=video_export.NarrationOptions(lines=["a", "b"]))
    assert err is None and media and report["smooth60"] is True and calls == []  # the copies made ahead


def test_status_404_for_a_missing_board(client):
    assert client.get("/api/boards/999999/smooth60").status_code == 404


@pytest.mark.asyncio
async def test_the_worker_hands_a_finished_scene_clip_to_the_warm_up(client, monkeypatch):
    import asyncio

    from flowboard.worker.processor import WorkerController

    b = _board(client)
    v = _node(client, b, "video", {})
    seen = []
    monkeypatch.setattr(smooth_prewarm, "after_clip", lambda node_id, media_id: seen.append((node_id, media_id)))

    async def rendered(params):
        return ({"media_ids": ["11111111-2222-4333-8444-555555555555"]}, None)

    row = client.post("/api/requests", json={"type": "gen_video_omni", "node_id": v, "params": {"prompt": "x"}}).json()
    w = WorkerController(handlers={"gen_video_omni": rendered})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        for _ in range(60):
            await asyncio.sleep(0.05)
            if client.get(f"/api/requests/{row['id']}").json()["status"] != "queued" and seen:
                break
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=3.0)
    assert seen == [(v, "11111111-2222-4333-8444-555555555555")]
