"""Remotion subtitle engine for the dubbing tool: spec building, the render
script protocol (mocked with a tiny Node script) and the routes' engine
handling. The real render is exercised by hand (needs Chrome + the bundle)."""
import json
import shutil
import sys
from pathlib import Path

import pytest

from flowboard.services import dub, dub_remotion


def test_build_spec_normalises_style_and_cues(tmp_path):
    spec = dub_remotion.build_spec(src=tmp_path / "nosub.mp4", out=tmp_path / "out.mp4",
                                   cues=[(0.0, 1.5, "Xin chào"), (1.5, 2.0, "   ")],
                                   layout={"x": 0.5, "y": 0.8, "scale": 1.2, "blur": {"x": 0.1, "y": 0.6, "w": 0.8, "h": 0.07, "amount": 5}},
                                   style="nope", width=720, height=1280, duration_s=12.6)
    assert spec["composition"] == "DubSubtitles" and spec["props"]["style"] == dub_remotion.DEFAULT_STYLE
    assert spec["props"]["cues"] == [{"start": 0.0, "end": 1.5, "text": "Xin chào"}]  # blank cue dropped
    assert spec["props"]["layout"]["blur"]["amount"] == 5 and spec["props"]["fps"] == dub_remotion.FPS


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_render_reads_progress_and_errors_from_the_script(tmp_path, monkeypatch):
    # a stand-in for render.mjs that speaks the same protocol
    script = tmp_path / "render.cjs"  # CommonJS: the stand-in uses require()
    script.write_text(
        "const fs=require('node:fs');const spec=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
        "console.log('PHASE bundle');console.log('PROGRESS 0.5');"
        "if(spec.props.style==='boom'){console.log('ERROR kaboom');process.exit(1);}"
        "fs.writeFileSync(spec.out,'x');console.log('PROGRESS 1');console.log('DONE');",
        encoding="utf-8")
    monkeypatch.setattr(dub_remotion, "SCRIPT", script)
    monkeypatch.setattr(dub_remotion, "available", lambda: (True, ""))
    src = tmp_path / "in.mp4"
    src.write_bytes(b"0")
    seen = []
    spec = dub_remotion.build_spec(src=src, out=tmp_path / "o.mp4", cues=[(0, 1, "a")], layout={}, style="rm_box",
                                   width=10, height=10, duration_s=1)
    out = dub_remotion.render(spec, progress=lambda f, ph: seen.append((f, ph)))
    assert out.is_file() and (0.5, "render") in seen and (0.0, "bundle") in seen
    spec["props"]["style"] = "boom"
    spec["out"] = str(tmp_path / "o2.mp4")
    with pytest.raises(dub_remotion.RemotionError, match="kaboom"):
        dub_remotion.render(spec)


def test_engine_and_style_validation(monkeypatch):
    monkeypatch.setattr(dub_remotion, "available", lambda: (True, ""))
    assert dub._check_engine("remotion") == "remotion" and dub._check_engine("anything") == "ass"
    assert dub._style_for("remotion", "box_yellow") == "rm_box"  # an ASS style on the remotion engine → its default
    assert dub._style_for("ass", "rm_box") == "box_yellow"
    assert dub._style_for("remotion", "rm_karaoke") == "rm_karaoke"
    monkeypatch.setattr(dub_remotion, "available", lambda: (False, "no node"))
    with pytest.raises(dub.DubError, match="no node"):
        dub._check_engine("remotion")


def test_status_and_start_report_the_engine(client, monkeypatch):
    monkeypatch.setattr(dub_remotion, "available", lambda: (True, ""))
    st = client.get("/api/dub/status").json()
    assert st["remotion"] is True and {s["key"] for s in st["remotion_styles"]} == set(dub_remotion.STYLES)
    monkeypatch.setattr(dub, "status", lambda: {"available": True, "separate": False, "remotion": True})
    monkeypatch.setattr(dub, "_pump", lambda: None)
    job = client.post("/api/dub/jobs", json={"url": "https://v.douyin.com/x/", "engine": "remotion", "style": "box_yellow",
                                            "voice": "vi-VN-HoaiMyNeural"}).json()
    assert job["engine"] == "remotion" and job["style"] == "rm_box" and "nosub_url" not in job
    # the nosub stream 404s until the job has made one
    assert client.get(f"/api/dub/jobs/{job['job_id']}/nosub").status_code == 404
    dub.JOBS.pop(job["job_id"], None)


def test_load_jobs_keeps_the_engine(tmp_path, monkeypatch):
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    work = tmp_path / "dub" / "abc123"
    work.mkdir(parents=True)
    (work / "job.json").write_text(json.dumps({"job_id": "abc123", "status": "done", "engine": "remotion", "style": "rm_karaoke",
                                                "width": 720, "height": 1280, "segments": []}), encoding="utf-8")
    (work / "nosub.mp4").write_bytes(b"0")
    dub.JOBS.pop("abc123", None)
    dub.load_jobs()
    job = dub.JOBS.pop("abc123")
    assert job.engine == "remotion" and job.width == 720
    assert job.public()["nosub_url"] == "/api/dub/jobs/abc123/nosub"
