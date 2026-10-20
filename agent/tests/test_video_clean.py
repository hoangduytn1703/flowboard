"""Clean tool: real ffmpeg on a lavfi testsrc clip for the box modes and
the frame endpoint; the pyvideotrans runner is parsed with a fake
``vi_dub_erase`` module and launched with ``subprocess`` mocked."""
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.main import app
from flowboard.services import media as media_service
from flowboard.services import video_clean
from flowboard.services import video_clean_runner as runner
from flowboard.services.video_export import probe_clip

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not on PATH")

if not any(getattr(r, "path", "") == "/api/clean/ai-status" for r in app.routes):
    from flowboard.routes import video_clean as video_clean_route
    app.include_router(video_clean_route.router)

client = TestClient(app)


def _testsrc(path: Path, seconds: float = 2.0) -> Path:
    cmd = [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=s=320x240:r=24:d={seconds}",
           "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={seconds}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)]
    subprocess.run(cmd, check=True, timeout=120)
    return path


@pytest.fixture
def clip(tmp_path):
    media_service.MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    media_id = "11111111222233334444555555555555"
    path = _testsrc(media_service.MEDIA_CACHE_DIR / f"{media_id}.mp4")
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(path), mime="video/mp4"))
        s.commit()
    yield media_id, path
    path.unlink(missing_ok=True)


def _assert_video(out: dict) -> None:
    assert out["media_id"] and out["url"] == f"/media/{out['media_id']}"
    with get_session() as s:
        row = s.exec(select(Asset).where(Asset.uuid_media_id == out["media_id"])).first()
    assert row is not None and row.kind == "video"
    info = probe_clip(Path(row.local_path))
    assert info is not None and info.width == 320 and info.height == 240
    assert abs(info.duration - 2.0) < 0.3
    assert info.has_audio


# ── box mode (ffmpeg) ──────────────────────────────────────────────────────

@needs_ffmpeg
def test_erase_box_delogo(clip):
    media_id, _ = clip
    r = client.post(f"/api/clean/{media_id}/erase", json={
        "mode": "box", "method": "delogo",
        "boxes": [{"x": 0.05, "y": 0.05, "w": 0.3, "h": 0.2}, {"x": 0.6, "y": 0.7, "w": 0.3, "h": 0.2}],
    })
    assert r.status_code == 200, r.text
    _assert_video(r.json())


@needs_ffmpeg
def test_erase_box_blur(clip):
    media_id, _ = clip
    r = client.post(f"/api/clean/{media_id}/erase", json={
        "mode": "box", "method": "blur",
        "boxes": [{"x": 0.1, "y": 0.1, "w": 0.25, "h": 0.15}, {"x": 0.5, "y": 0.5, "w": 0.4, "h": 0.4}],
    })
    assert r.status_code == 200, r.text
    _assert_video(r.json())


@needs_ffmpeg
def test_erase_ai_blur_uses_bands(clip):
    media_id, _ = clip
    r = client.post(f"/api/clean/{media_id}/erase", json={"mode": "ai-blur", "bands": [{"y0": 0.8, "y1": 0.95}]})
    assert r.status_code == 200, r.text
    _assert_video(r.json())


def test_erase_box_rejects_empty(clip):
    media_id, _ = clip
    r = client.post(f"/api/clean/{media_id}/erase", json={"mode": "box", "boxes": []})
    assert r.status_code == 422


def test_erase_unknown_video():
    r = client.post("/api/clean/deadbeefdeadbeefdeadbeefdeadbeef/erase",
                    json={"mode": "box", "boxes": [{"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}]})
    assert r.status_code == 404


def test_box_pixels_even_and_inside():
    assert video_clean.Box(0.0, 0.0, 1.0, 1.0).to_pixels(321, 241) == (0, 0, 320, 240)
    x, y, w, h = video_clean.Box(0.99, 0.99, 0.5, 0.5).to_pixels(320, 240)
    assert x + w <= 320 and y + h <= 240 and w >= 2 and h >= 2
    with pytest.raises(video_clean.CleanError):
        video_clean.Box.from_dict({"x": 1.2, "y": 0, "w": 0.1, "h": 0.1})


# ── frame + info ───────────────────────────────────────────────────────────

@needs_ffmpeg
def test_frame_endpoint_returns_jpeg(clip):
    media_id, _ = clip
    r = client.get(f"/api/clean/{media_id}/frame", params={"t": 1.0})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content[:3] == b"\xff\xd8\xff"
    assert r.headers["x-frame-width"] == "320" and r.headers["x-frame-height"] == "240"
    # Past the end is clamped, not an error.
    assert client.get(f"/api/clean/{media_id}/frame", params={"t": 99}).status_code == 200
    info = client.get(f"/api/clean/{media_id}/info").json()
    assert info["width"] == 320 and info["height"] == 240 and abs(info["duration_s"] - 2.0) < 0.3


# ── AI runner ──────────────────────────────────────────────────────────────

def test_ai_status_when_python_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("FLOWBOARD_ERASE_PYTHON", str(tmp_path / "nope.exe"))
    r = client.get("/api/clean/ai-status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False and "pyvideotrans" in body["reason"]


def test_detect_without_python_is_503(monkeypatch, clip):
    media_id, _ = clip
    monkeypatch.setenv("FLOWBOARD_ERASE_PYTHON", "C:/does/not/exist/python.exe")
    r = client.post(f"/api/clean/{media_id}/detect")
    assert r.status_code == 503
    r = client.post(f"/api/clean/{media_id}/erase", json={"mode": "ai", "bands": [{"y0": 0.8, "y1": 0.9}]})
    assert r.status_code == 503


def test_runner_cli_parsing(monkeypatch, capsys):
    calls = {}
    fake = types.ModuleType("vi_dub_erase")

    def find_sub_bands(src):
        calls["detect"] = src
        return [{"top": 82.0, "size": 8.0, "hits": 31}], "Tìm thấy"

    def erase_video(src, dst, bands, root, stop=None):
        calls["erase"] = (src, dst, bands, root)
        yield 0.5
        yield 1.0

    fake.find_sub_bands = find_sub_bands
    fake.erase_video = erase_video
    monkeypatch.setitem(sys.modules, "vi_dub_erase", fake)
    monkeypatch.setenv("FLOWBOARD_ERASE_ROOT", "D:/fake/root")

    assert runner.main(["detect", "in.mp4"]) == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line.startswith("BANDS ")
    assert json.loads(line[6:]) == {"bands": [{"y0": 0.82, "y1": 0.9, "hits": 31}], "info": "Tìm thấy"}
    assert calls["detect"] == "in.mp4"

    assert runner.main(["erase", "in.mp4", "out.mp4", json.dumps([{"y0": 0.82, "y1": 0.9}])]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["PROGRESS 50", "PROGRESS 100", "DONE"]
    src, dst, bands, root = calls["erase"]
    assert (src, dst, root) == ("in.mp4", "out.mp4", "D:/fake/root")
    assert bands[0]["top"] == pytest.approx(82.0) and bands[0]["size"] == pytest.approx(8.0)

    assert runner.main([]) == 2
    assert runner.main(["detect"]) == 2
    assert runner.main(["erase", "a", "b", "not json"]) == 2
    assert runner.main(["erase", "a", "b", "[]"]) == 2
    assert runner.main(["bogus"]) == 2


def test_detect_parses_runner_stdout(monkeypatch, tmp_path):
    py = tmp_path / "python.exe"
    py.write_bytes(b"")
    monkeypatch.setenv("FLOWBOARD_ERASE_PYTHON", str(py))
    monkeypatch.setenv("FLOWBOARD_ERASE_ROOT", str(tmp_path))
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["cwd"], seen["env"] = cmd, kw.get("cwd"), kw.get("env")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"warning noise\nBANDS {\"bands\": [{\"y0\": 0.8, \"y1\": 0.9, \"hits\": 5}], \"info\": \"ok\"}\n", stderr=b"")

    with patch.object(video_clean.subprocess, "run", fake_run):
        out = video_clean.detect_bands(Path("D:/x/in.mp4"))
    assert out["bands"] == [{"y0": 0.8, "y1": 0.9, "hits": 5}]
    assert seen["cmd"][:2] == [str(py), str(video_clean.RUNNER_PATH)]
    assert seen["cmd"][2:] == ["detect", str(Path("D:/x/in.mp4"))]
    assert seen["cwd"] == str(tmp_path) and seen["env"]["FLOWBOARD_ERASE_ROOT"] == str(tmp_path)

    def fail_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"Traceback\nRuntimeError: boom\n")

    with patch.object(video_clean.subprocess, "run", fail_run), pytest.raises(video_clean.CleanError, match="boom"):
        video_clean.detect_bands(Path("D:/x/in.mp4"))


def test_second_ai_job_is_409(monkeypatch, clip):
    media_id, _ = clip
    video_clean.JOBS.clear()
    video_clean.JOBS["busy"] = video_clean.Job(id="busy", source_media_id=media_id, status="running")
    py = Path(video_clean.ERASE_ROOT_DEFAULT) / "x.exe"
    monkeypatch.setenv("FLOWBOARD_ERASE_PYTHON", str(py))
    try:
        r = client.post(f"/api/clean/{media_id}/erase", json={"mode": "ai", "bands": [{"y0": 0.8, "y1": 0.9}]})
        assert r.status_code == 409
        assert client.get("/api/clean/jobs/busy").json()["status"] == "running"
        assert client.get("/api/clean/jobs/nope").status_code == 404
    finally:
        video_clean.JOBS.clear()
