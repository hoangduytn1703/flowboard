"""Step 5 "Cắt cảnh" and "Chữ trên video": trims cut each clip before the
join, overlays are burned on the joined clip. Real ffmpeg (skipped without)."""
import asyncio
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.services import video_export, video_overlays
from flowboard.worker import processor

FFMPEG = shutil.which("ffmpeg")


def test_clip_window_clamps():
    assert video_export.clip_window(8.0, None) == (0.0, 8.0)
    assert video_export.clip_window(8.0, (1.0, 5.0)) == (1.0, 4.0)
    assert video_export.clip_window(8.0, (2.0, None)) == (2.0, 6.0)
    assert video_export.clip_window(8.0, (7.9, 3.0)) == (7.5, 0.5)   # start kept inside, min length
    assert video_export.clip_window(8.0, (-3, 99)) == (0.0, 8.0)


def test_parse_overlays_drops_bad_entries():
    got = video_overlays.parse_overlays([
        {"text": "  Cơm cháy   siêu chà bông ", "preset": "title", "position": "top", "start": 0, "end": 3},
        {"text": "129.000đ", "preset": "price", "position": "bottom", "start": "5", "end": None},
        {"text": "", "preset": "badge"},                       # empty
        {"text": "x", "start": 4, "end": 2},                   # ends before it starts
        {"text": "y", "preset": "weird", "position": "left"},  # unknown → defaults
        "nope",
    ])
    assert [o.text for o in got] == ["Cơm cháy siêu chà bông", "129.000đ", "y"]
    assert got[1].preset == "price" and got[1].start == 5.0 and got[1].end is None
    assert got[2].preset == "title" and got[2].position == "top"


def test_handler_passes_trims_and_overlays(tmp_path):
    ids = []
    for n in ("ffffffff", "99999999"):
        f = tmp_path / f"{n}.mp4"
        f.write_bytes(b"\x00")
        with get_session() as s:
            a = Asset(kind="video", uuid_media_id=f"{n}-0000-4000-8000-000000000000", local_path=str(f), mime="video/mp4")
            s.add(a); s.commit(); s.refresh(a); ids.append(a.uuid_media_id)
    seen = {}

    def fake_export(asset_ids, *, smooth60, narration=None, items=None, trims=None, overlays=None, **_):
        seen.update(trims=trims, overlays=overlays)
        return "out", None, {}

    with patch("flowboard.services.video_export.export_video", fake_export):
        asyncio.run(processor._handle_export_video({
            "source_media_ids": ids, "trims": [[1, 6.5], "bad"],
            "overlays": [{"text": "Freeship", "preset": "badge", "position": "top", "start": 0, "end": 2}]}))
    assert seen["trims"] == [(1.0, 6.5), None]
    assert [o.text for o in seen["overlays"]] == ["Freeship"]


def _duration(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True)
    return float(out.stdout.strip())


@pytest.mark.skipif(FFMPEG is None or shutil.which("ffprobe") is None, reason="ffmpeg not installed")
def test_real_export_trims_and_burns_text(tmp_path, monkeypatch):
    monkeypatch.setattr(video_export.config, "STORAGE_DIR", tmp_path)
    ids = []
    for i in range(2):
        f = tmp_path / f"src{i}.mp4"
        subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc=size=360x640:rate=24:duration=2",
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "2", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", str(f)], check=True, capture_output=True)
        with get_session() as s:
            a = Asset(kind="video", uuid_media_id=f"{i}" * 8 + "-1111-4111-8111-111111111111", local_path=str(f))
            s.add(a); s.commit(); s.refresh(a); ids.append(a.id)
    overlays = video_overlays.parse_overlays([{"text": "Cơm cháy 129.000đ", "preset": "price", "position": "bottom"}])
    media, err, report = video_export.export_video(ids, smooth60=False, trims=[(0.5, 1.5), None], overlays=overlays)
    assert err is None and media and report["overlays"] == 1 and not report["overlays_error"]
    with get_session() as s:
        out = Path(s.exec(__import__("sqlmodel").select(Asset).where(Asset.uuid_media_id == media)).first().local_path)
    assert abs(_duration(out) - 3.0) < 0.35   # 1 s (trimmed) + 2 s
    b = out.read_bytes()
    assert 0 <= b.find(b"moov") < b.find(b"mdat")  # faststart


def test_negative_start_counts_from_the_end(tmp_path):
    ovs = video_overlays.parse_overlays([
        {"text": "Chỉ 129.000đ", "preset": "price", "position": "bottom", "start": -4},
        {"text": "x", "start": -2, "end": -1},   # a negative end is not allowed
    ])
    assert [o.text for o in ovs] == ["Chỉ 129.000đ"] and ovs[0].start == -4
    ass = video_overlays.write_overlay_ass(ovs, tmp_path / "o.ass", width=720, height=1280, total_s=13.0)
    line = [l for l in ass.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue:")][0]
    assert ",0:00:09.00,0:00:13.00,price," in line
