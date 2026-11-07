"""Clip export speed (7/11 — a jacket clip took 10 min to join, then joined again):
60 fps smoothing per source clip side by side and cached, the voices read ahead in one go, a voice that ignores the
rate not read twice, and the same export not queued twice for one node. Real ffmpeg where it matters."""
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.services import tts, video_export, video_watermark

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or shutil.which("ffprobe") is None, reason="ffmpeg not installed")


def _clip(path: Path, seconds: float = 0.5) -> Path:
    """A small moving 24 fps clip (minterpolate has motion to work on) with sound."""
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=160x284:rate=24:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}", "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    return path


def _rate(path: Path) -> str:
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                           "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True).stdout.strip()


def _count_smoothing(monkeypatch) -> dict:
    """Wrap smooth_to_60fps: how many runs, on what, and how many at once at most."""
    seen = {"calls": [], "now": 0, "most": 0}
    lock = threading.Lock()
    real = video_export.smooth_to_60fps

    def counted(src, dst):
        with lock:
            seen["calls"].append(Path(src).name)
            seen["now"] += 1
            seen["most"] = max(seen["most"], seen["now"])
        try:
            time.sleep(0.3)  # long enough for the other clips to start alongside
            return real(src, dst)
        finally:
            with lock:
                seen["now"] -= 1

    monkeypatch.setattr(video_export, "smooth_to_60fps", counted)
    return seen


@needs_ffmpeg
def test_sources_are_smoothed_side_by_side_and_only_once(tmp_path, monkeypatch):
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path / "media")
    monkeypatch.setattr(video_export, "SMOOTH_PARALLEL", 3)
    seen = _count_smoothing(monkeypatch)
    srcs = [_clip(tmp_path / f"c{i}.mp4") for i in range(3)]
    out, err = video_export.smooth_sources(srcs)
    assert err is None and len(out) == 3 and all(o != s for o, s in zip(out, srcs))
    assert all(_rate(o) == "60/1" for o in out)
    assert seen["most"] >= 2  # not one after another
    assert len(seen["calls"]) == 3
    again, err = video_export.smooth_sources(srcs)  # "Ghép lại": the copies are reused
    assert again == out and err is None and len(seen["calls"]) == 3


@needs_ffmpeg
def test_a_clip_that_fails_to_smooth_keeps_its_frames(tmp_path, monkeypatch):
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path / "media")
    good = _clip(tmp_path / "good.mp4")
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    out, err = video_export.smooth_sources([good, bad])
    assert out[1] == bad and out[0] != good and err
    assert not list((tmp_path / "media" / "smooth60").glob("*.part.mp4"))


@needs_ffmpeg
def test_a_60fps_export_smooths_the_clips_not_the_join(tmp_path, monkeypatch):
    monkeypatch.setattr(video_export.config, "STORAGE_DIR", tmp_path)
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path / "media")
    monkeypatch.setattr(video_watermark, "turned_on", lambda: False)
    wav = tmp_path / "line.wav"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.4", str(wav)], check=True)
    narration = tts.Narration(path=wav, duration=0.4, words=[])
    monkeypatch.setattr(video_export, "_synth_to_fit", lambda text, opts, dur, voice=None: (narration, 0))
    monkeypatch.setattr(video_export, "_prefetch_voices", lambda lines, opts: None)
    ids = []
    for i in range(2):
        f = _clip(tmp_path / f"s{i}.mp4")
        with get_session() as s:
            a = Asset(kind="video", uuid_media_id=f"{i + 1}" * 8 + "-5555-4555-8555-555555555555", local_path=str(f))
            s.add(a); s.commit(); s.refresh(a); ids.append(a.id)
    seen = _count_smoothing(monkeypatch)
    opts = video_export.NarrationOptions(lines=["Một", "Hai"], subtitles=True)
    media, err, report = video_export.export_video(ids, smooth60=True, narration=opts)
    assert err is None and media and report["smooth60"] is True and report["smooth60_error"] is None
    assert sorted(seen["calls"]) == ["s0.mp4", "s1.mp4"]  # the sources; the joined clip is not smoothed again
    with get_session() as s:
        out = Path(s.exec(__import__("sqlmodel").select(Asset).where(Asset.uuid_media_id == media)).first().local_path)
    assert _rate(out) == "60/1"


def test_voices_are_read_ahead_in_one_go(monkeypatch):
    many, single = [], []

    async def fake_many(lines, voice, rate=0, style=None):
        many.append((voice, list(lines)))
        return []

    async def fake_one(text, voice, rate=0, style=None):
        single.append((voice, text))

    monkeypatch.setattr(tts, "synthesize_many", fake_many)
    monkeypatch.setattr(tts, "synthesize", fake_one)
    opts = video_export.NarrationOptions(
        lines=["Câu một", "", "[A] chào [B] chào", "Câu bốn", "Câu năm"],
        voice="vieneu:Hải Đăng", line_voices=[None, None, None, None, "vi-VN-NamMinhNeural"])
    video_export._prefetch_voices(opts.lines, opts)
    assert many == [("vieneu:Hải Đăng", ["Câu một", "Câu bốn"])]  # one model load; dialogue left to the loop
    assert single == [("vi-VN-NamMinhNeural", "Câu năm")]


def test_a_voice_that_ignores_the_rate_is_not_read_twice(monkeypatch):
    calls = []

    def long_line(text, opts, rate, voice=None):
        calls.append(rate)
        return tts.Narration(path=Path("x.wav"), duration=12.0, words=[])

    monkeypatch.setattr(video_export, "_synth_line", long_line)
    video_export._synth_to_fit("dài", video_export.NarrationOptions(lines=[], voice="vieneu:Hải Đăng"), 8.0)
    assert calls == [0]
    calls.clear()
    video_export._synth_to_fit("dài", video_export.NarrationOptions(lines=[]), 8.0)  # Edge: faster on the second go
    assert len(calls) == 2 and calls[1] > 0


def test_the_same_export_is_not_queued_twice(client):
    b = client.post("/api/boards", json={"name": "T"}).json()
    n = client.post("/api/nodes", json={"board_id": b["id"], "type": "export"}).json()
    body = {"node_id": n["id"], "type": "export_video", "params": {"source_media_ids": ["a", "b"], "smooth60": True}}
    first = client.post("/api/requests", json=body).json()
    second = client.post("/api/requests", json=body).json()
    assert second["id"] == first["id"]
    changed = client.post("/api/requests", json={**body, "params": {"source_media_ids": ["a", "b"], "smooth60": False}}).json()
    assert changed["id"] != first["id"]
    other = {"node_id": n["id"], "type": "proxy", "params": {}}
    assert client.post("/api/requests", json=other).json()["id"] != client.post("/api/requests", json=other).json()["id"]
