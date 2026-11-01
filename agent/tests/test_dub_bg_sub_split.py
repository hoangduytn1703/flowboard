"""31/10: the output format's own backgrounds (colour / grid / picture / video, the whole video placed at ``pos`` and
``scale``), subtitles-only dubbing (the video keeps its sound, no voice read), and "✂️ Cắt thành nhiều video"."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from flowboard.db import get_session
from flowboard.db.models import Asset, Board, Node
from flowboard.services import dub, dub_split
from flowboard.services.llm.base import LLMError
from flowboard.services.video_export import probe_clip

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or shutil.which("ffprobe") is None, reason="needs ffmpeg")


def _clip(path: Path, size: str = "320x180", seconds: float = 1.0, audio: bool = False, colour: str = "") -> Path:
    src = f"color=c={colour}:size={size}:rate=10:duration={seconds}" if colour else f"testsrc=size={size}:rate=10:duration={seconds}"
    cmd = [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", src]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}", "-shortest", "-c:a", "aac"]
    subprocess.run(cmd + ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _frame_pixels(video: Path, at: float, out: Path) -> "object":
    from PIL import Image

    subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", f"{at}", "-i", str(video), "-frames:v", "1", str(out)], check=True)
    return Image.open(out).convert("RGB")


def _near(px: tuple[int, int, int], hexc: str, tol: int = 40) -> bool:
    want = tuple(int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return all(abs(a - b) <= tol for a, b in zip(px, want))


# ── backgrounds ─────────────────────────────────────────────────────────────

def test_a_format_keeps_its_background_settings():
    c = dub.normalize_canvas({"aspect": "9:16", "fit": "grid", "color": "#112233", "line": "nope", "cell": 9, "scale": 0.1,
                              "media_id": "  abc  "})
    assert c["fit"] == "grid" and c["color"] == "#112233" and c["line"] == dub.CANVAS_DEFAULT["line"]
    assert c["cell"] == 0.3 and c["scale"] == 0.5 and c["media_id"] == "abc"
    assert dub.normalize_canvas({"aspect": "9:16", "fit": "rainbow"})["fit"] == "blur"
    # an old saved format reads with the defaults
    old = dub.normalize_canvas({"aspect": "9:16", "fit": "black", "pos": 0.5})
    assert old["scale"] == 1.0 and old["color"] == dub.CANVAS_DEFAULT["color"] and old["media_id"] == ""


def test_the_whole_video_sits_at_pos_and_scale():
    top = dub.canvas_rect(1280, 720, 720, 1280, {"scale": 1.0, "pos": 0.0})
    mid = dub.canvas_rect(1280, 720, 720, 1280, {"scale": 1.0, "pos": 0.5})
    low = dub.canvas_rect(1280, 720, 720, 1280, {"scale": 1.0, "pos": 1.0})
    assert top[0] == 0 and top[1] == 0 and top[2] == 720
    assert mid[1] == (1280 - mid[3]) // 2 // 2 * 2 and low[1] == 1280 - low[3]
    # smaller than the format: background all round, centred across, at pos along the longer free side
    x, y, w, h = dub.canvas_rect(720, 1280, 720, 1280, {"scale": 0.8, "pos": 0.5})
    assert (w, h) == (576, 1024) and (x, y) == (72, 128)


def test_each_background_has_its_graph():
    g = lambda c, i=None: dub.canvas_filter({"pos": 0.5, "scale": 1.0, **c}, 1280, 720, 720, 1280, bg_index=i)  # noqa: E731
    assert "pad=720:1280:0:" in g({"fit": "color", "color": "#112233"}) and "color=0x112233" in g({"fit": "color", "color": "#112233"})
    grid = g({"fit": "grid", "color": "#211915", "line": "#4a3a2e", "cell": 0.11})
    assert "drawbox=" in grid and "drawgrid=" in grid and "c=0x4a3a2e@1" in grid and "[cv_bg][cv_fg]overlay" in grid
    img = g({"fit": "image", "media_id": "x"}, 3)
    assert "[3:v]scale=720:1280:force_original_aspect_ratio=increase" in img and "overlay=0:0:shortest=1" in img
    # the uploaded file is missing on this machine: the colour stands in
    assert "pad=720:1280" in g({"fit": "video", "media_id": "x", "color": "#010203"}) and "0x010203" in g({"fit": "video", "color": "#010203"})
    # same shape: nothing to do at full size, a background all round when the video is made smaller
    assert dub.canvas_filter({"fit": "grid", "scale": 1.0}, 720, 1280, 720, 1280) == ""
    assert "pad=720:1280:72:128" in dub.canvas_filter({"fit": "color", "scale": 0.8, "pos": 0.5, "color": "#000000"}, 720, 1280, 720, 1280)


@needs_ffmpeg
@pytest.mark.parametrize("fit", ["color", "grid", "image", "video"])
def test_each_background_really_renders(tmp_path, monkeypatch, fit):
    """A landscape clip into 9:16 over each background: the band above the video shows it, the clip keeps its length."""
    src = _clip(tmp_path / "src.mp4", seconds=2.0)
    bg_file = None
    if fit == "image":
        bg_file = tmp_path / "bg.png"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:size=64x64", "-frames:v", "1", str(bg_file)], check=True)
    if fit == "video":
        bg_file = _clip(tmp_path / "bg.mp4", "64x64", seconds=0.5, colour="green")  # shorter than the clip: it loops
    lay = {"canvas": {"aspect": "9:16", "fit": fit, "pos": 0.5, "color": "#123456", "line": "#ffffff", "cell": 0.2,
                      "media_id": "bg" if bg_file else ""}}
    monkeypatch.setattr(dub.dub_decor, "local_media", lambda mid: bg_file)
    w, h = dub.canvas_size(320, 180, lay)
    ass = dub.write_sub_ass([], tmp_path / "s.ass", width=w, height=h, layout=lay)
    cmd = [FFMPEG, "-y", "-v", "error", "-i", str(src)]
    bg = dub.canvas_bg_file(lay)
    idx = None
    if bg is not None:
        idx = 1
        cmd += dub.canvas_bg_args(bg)
    graph = dub.video_filter(ass, w, h, lay, source=(320, 180), canvas_bg_index=idx)
    out = tmp_path / "out.mp4"
    subprocess.run(cmd + ["-filter_complex", graph, "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    info = probe_clip(out)
    assert (info.width, info.height) == (w, h) and abs(info.duration - 2.0) < 0.35
    img = _frame_pixels(out, 1.5, tmp_path / "f.png")
    band = [img.getpixel((x, y)) for x in range(0, w, 3) for y in range(0, 20, 3)]  # top band: background only
    if fit == "color":
        assert all(_near(p, "#123456") for p in band)
    elif fit == "grid":
        assert sum(_near(p, "#123456") for p in band) > len(band) * 0.6 and any(_near(p, "#ffffff", 60) for p in band)
    elif fit == "image":
        assert all(_near(p, "#ff0000", 60) for p in band)
    else:  # the green video, still there at 1.5 s although it is 0.5 s long
        assert all(_near(p, "#008000", 60) for p in band)


# ── subtitles only ──────────────────────────────────────────────────────────

@needs_ffmpeg
def test_subtitles_only_keeps_the_videos_sound_and_reads_no_voice(client, tmp_path, monkeypatch):
    from flowboard import config
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    src = _clip(tmp_path / "src.mp4", "160x284", seconds=3.0, audio=True)
    monkeypatch.setattr(dub, "_voice_pieces", lambda job: (_ for _ in ()).throw(AssertionError("no voice in subtitles-only")))
    monkeypatch.setattr(dub, "status", lambda: {"separate": True, "available": True})
    ran: list[list[str]] = []
    real_run = dub._run
    monkeypatch.setattr(dub, "_run", lambda cmd, timeout: ran.append(list(cmd)) or real_run(cmd, timeout))
    job = dub.Job(id="5ab000000001", url=None, source_media_id="src", mode="sub", keep_bgm=True)
    job.segments = [dub.Segment(0.2, 1.4, "你好", "Xin chào"), dub.Segment(1.6, 2.8, "再见", "Tạm biệt")]
    job.duration_s = 3.0
    job.work = tmp_path / "dub" / job.id
    job.work.mkdir(parents=True)
    job.src_path = src
    dub._render(job)
    assert job.status == "done", job.error
    assert not (job.work / "voice.wav").exists() and not (job.work / "bgm.wav").exists()
    final = [c for c in ran if any(str(a).endswith(f"{job.media_id}.mp4") for a in c)][-1]
    assert final.count("-i") == 1 and "0:a:0" in final  # only the source; its own sound mapped
    out = tmp_path / f"{job.media_id}.mp4"
    info = probe_clip(out)
    assert info.has_audio and abs(info.duration - 3.0) < 0.3
    # the lines keep Whisper's timing (no voice to follow)
    assert (job.segments[0].start, job.segments[1].end) == (0.2, 2.8)
    # a stale voice.wav from a voice-over is not offered to the editor
    (job.work / "voice.wav").write_bytes(b"x")
    assert "voice_url" not in job.public() and job.public()["mode"] == "sub"
    # the key-moment sounds mix with the source's sound
    agraph, amap = dub.audio_mix_sub(True, 1)
    assert "[0:a][fx]amix" in agraph and amap == "[a]"
    assert dub.audio_mix_sub(False, None) == ("", None)


def test_a_vietnamese_video_is_not_translated(monkeypatch):
    from flowboard.services import free_translate

    monkeypatch.setattr(free_translate, "translate_lines", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no translation")))
    job = dub.Job(id="v", url=None, source_media_id="x", language="vi", mode="sub")
    job.segments = [dub.Segment(0, 1, "Chào cả nhà", "")]
    asyncio.run(dub._translate(job))
    assert job.segments[0].text == "Chào cả nhà" and job.translated_by == "none"


def test_the_mode_travels_with_the_project(client, monkeypatch):
    monkeypatch.setattr(dub, "status", lambda: {"available": True, "separate": False, "remotion": False})
    monkeypatch.setattr(dub, "_pump", lambda: None)
    r = client.post("/api/dub/jobs", json={"url": "https://v.douyin.com/abc", "voice": dub.tts.DEFAULT_VOICE,
                                           "keep_bgm": False, "style": "box_yellow", "auto_render": True, "mode": "sub"})
    jid = r.json().get("job_id")
    try:
        assert r.status_code == 201 and r.json()["mode"] == "sub"
        job = dub.JOBS[jid]
        restored = dub._job_from_dict(dub.snapshot(job), Path("."), 0)
        assert restored.mode == "sub"
        assert client.post("/api/dub/jobs", json={"url": "https://v.douyin.com/abc", "voice": dub.tts.DEFAULT_VOICE,
                                                  "keep_bgm": False, "style": "box_yellow", "auto_render": True,
                                                  "mode": "karaoke"}).status_code == 422
    finally:
        dub.JOBS.pop(jid, None)


# ── cutting into several videos ─────────────────────────────────────────────

def _talk_job(duration: float = 100.0) -> dub.Job:
    """Lines every 10 s (8 s long), so the pauses are at 9, 19, 29…"""
    job = dub.Job(id="c0ffee0000c1", url=None, source_media_id="x", name="Hệ Mặt Trời", status="done")
    job.duration_s = duration
    job.segments = [dub.Segment(i * 10.0, i * 10.0 + 8.0, f"src{i}", f"Câu {i}") for i in range(int(duration // 10))]
    return job


def test_even_parts_end_in_a_pause():
    job = _talk_job()
    rows = dub_split.suggest_even(job, 30)
    pts = set(dub_split.cut_points(job))
    assert rows[0]["start"] == 0 and rows[-1]["end"] == 100.0
    assert all(r["end"] in pts for r in rows[:-1])
    assert all(a["end"] == b["start"] for a, b in zip(rows, rows[1:]))
    assert all(18 <= r["end"] - r["start"] <= 42 for r in rows[:-1])
    assert rows[0]["title"].startswith("Hệ Mặt Trời — Phần 1/")
    assert dub_split.snap(30.5, sorted(pts)) == 29.0 and dub_split.snap(25.0, sorted(pts), 1.0) == 25.0


def test_the_ais_line_ranges_become_times_in_the_pauses():
    job = _talk_job()
    rows = dub_split.parts_from_ai(job, {"parts": [{"from": 1, "to": 3, "title": "Mở đầu"}, {"from": 2, "to": 5, "title": "chồng"},
                                                   {"from": 4, "to": 10, "title": "Phần sau"}]})
    assert [(r["start"], r["end"], r["title"]) for r in rows] == [(0.0, 29.0, "Mở đầu"), (29.0, 100.0, "Phần sau")]
    with pytest.raises(dub_split.SplitError):
        dub_split.parts_from_ai(job, {"parts": [{"from": "x"}]})


def test_an_ai_that_fails_falls_back_to_the_pauses(monkeypatch):
    async def broken(*a, **k):
        raise LLMError("claude CLI exited 1: Claude AI usage limit reached")

    monkeypatch.setattr(dub_split, "run_llm", broken)
    out = asyncio.run(dub_split.suggest(_talk_job(), 30, True))
    assert out["by"] == "even" and "usage limit" in out["note"] and out["rows"]

    async def fine(feature, prompt, *, system_prompt=None, timeout=0):
        assert "TRANSCRIPT (10 lines)" in prompt and "[1] (0.0s-8.0s) Câu 0" in prompt
        return json.dumps({"parts": [{"from": 1, "to": 5, "title": "A"}, {"from": 6, "to": 10, "title": "B"}]})

    monkeypatch.setattr(dub_split, "run_llm", fine)
    out = asyncio.run(dub_split.suggest(_talk_job(), 50, True))
    assert out["by"] == "ai" and [r["title"] for r in out["rows"]] == ["A", "B"]


def test_rows_are_checked_before_cutting(monkeypatch):
    job = _talk_job(20)
    with pytest.raises(dub_split.SplitError, match="Xuất lại video"):
        dub_split.start(job, [{"start": 0, "end": 10}])
    job.media_id = "m"
    monkeypatch.setattr(dub_split, "_source", lambda job: Path("x.mp4"))
    monkeypatch.setattr(dub, "persist", lambda job: None)
    with pytest.raises(dub_split.SplitError, match="ngắn hơn"):
        dub_split.start(job, [{"start": 0, "end": 2}])
    assert dub_split.normalize_rows([{"start": 5, "end": 99, "title": "  a   b "}, {"start": "x"}], 20) == [{"start": 5.0, "end": 20.0, "title": "a b"}]


@needs_ffmpeg
def test_a_video_is_cut_into_clips_and_a_new_cut_reuses_them(client, tmp_path, monkeypatch):
    from flowboard import config
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    exported = _clip(tmp_path / "exported.mp4", "160x284", seconds=8.0, audio=True)
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id="exp1", local_path=str(exported), mime="video/mp4"))
        s.commit()
    job = _talk_job(8.0)
    job.segments = [dub.Segment(0.2, 3.4, "a", "Phần đầu"), dub.Segment(4.2, 7.8, "b", "Phần sau")]
    job.media_id, job.channel_id = "exp1", None
    job.work = tmp_path / "dub" / job.id
    job.work.mkdir(parents=True)
    dub.JOBS[job.id] = job
    try:
        st = dub_split.start(job, [{"start": 0, "end": 3.8, "title": "Đầu"}, {"start": 3.8, "end": 8.0, "title": ""}])
        assert st["status"] == "running" and st["total"] == 2
        for _ in range(240):
            if dub_split.state(job.id)["status"] != "running":
                break
            time.sleep(0.25)
        st = dub_split.state(job.id)
        assert st["status"] == "done", st
        parts = job.parts
        assert [p["index"] for p in parts] == [1, 2] and parts[1]["title"] == "Hệ Mặt Trời — Phần 2/2"
        for p in parts:
            out = media_service.cached_path(p["media_id"])
            info = probe_clip(Path(out))
            assert abs(info.duration - (p["end"] - p["start"])) < 0.35 and info.has_audio
            assert dub.read_tag(Path(out)) == job.id  # dropping a part on the page reopens this project
            with get_session() as s:
                b = s.get(Board, p["board_id"])
                qt = b.data["quicktool"]
                assert qt["template_id"] == "dub_part" and qt["dub_part"]["job_id"] == job.id and b.name in ("Đầu", "Hệ Mặt Trời — Phần 2/2")
                nodes = {n.type: n for n in s.exec(dub.select(Node).where(Node.board_id == b.id)).all()}
                assert nodes["export"].data["mediaId"] == p["media_id"]
        # a new cut: same clips, new videos
        first_boards = [p["board_id"] for p in parts]
        dub_split.start(job, [{"start": 0, "end": 4.0, "title": "Đầu mới"}, {"start": 4.0, "end": 8.0, "title": "Sau"}])
        for _ in range(240):
            if dub_split.state(job.id)["status"] != "running":
                break
            time.sleep(0.25)
        assert dub_split.state(job.id)["status"] == "done"
        assert [p["board_id"] for p in job.parts] == first_boards and job.parts[0]["media_id"] != parts[0]["media_id"]
        with get_session() as s:
            assert s.get(Board, first_boards[0]).name == "Đầu mới"
        # the rows stay with the project
        assert job.public()["cuts"][0]["title"] == "Đầu mới"
    finally:
        dub.JOBS.pop(job.id, None)
        dub_split.SPLITS.pop(job.id, None)


def test_split_routes(client, monkeypatch):
    job = _talk_job()
    dub.JOBS[job.id] = job
    monkeypatch.setattr(dub, "persist", lambda job: None)
    try:
        r = client.post(f"/api/dub/jobs/{job.id}/split/suggest", json={"target_s": 30, "ai": False})
        assert r.status_code == 200 and r.json()["by"] == "even" and r.json()["rows"]
        r = client.put(f"/api/dub/jobs/{job.id}/cuts", json={"rows": [{"start": 0, "end": 40, "title": "x"}]})
        assert r.json()["cuts"] == [{"start": 0.0, "end": 40.0, "title": "x"}] and job.cuts[0]["end"] == 40.0
        assert client.get(f"/api/dub/jobs/{job.id}/split").json() == {"status": "idle"}
        r = client.post(f"/api/dub/jobs/{job.id}/split", json={"rows": [{"start": 0, "end": 40}]})
        assert r.status_code == 400 and "Xuất lại video" in r.json()["detail"]
    finally:
        dub.JOBS.pop(job.id, None)


def test_background_upload(client, tmp_path, monkeypatch):
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    r = client.post("/api/dub/background", files={"file": ("nen.png", b"\x89PNG fake", "image/png")})
    assert r.status_code == 201 and r.json()["kind"] == "image"
    r = client.post("/api/dub/background", files={"file": ("nen.mp4", b"fake mp4", "application/octet-stream")})
    assert r.status_code == 201 and r.json()["kind"] == "video" and (tmp_path / f"{r.json()['media_id']}.mp4").is_file()
    assert client.post("/api/dub/background", files={"file": ("x.txt", b"hi", "text/plain")}).status_code == 415
    assert client.post("/api/dub/background", files={"file": ("e.png", b"", "image/png")}).status_code == 400


@needs_ffmpeg
def test_a_moving_gif_background_becomes_an_mp4(client, tmp_path, monkeypatch):
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    gif = tmp_path / "in.gif"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=63x47:rate=5:duration=1", str(gif)], check=True)
    r = client.post("/api/dub/background", files={"file": ("nen.gif", gif.read_bytes(), "image/gif")})
    assert r.status_code == 201 and r.json()["kind"] == "video"
    mp4 = tmp_path / f"{r.json()['media_id']}.mp4"
    info = probe_clip(mp4)
    assert info is not None and info.duration > 0.5 and (info.width, info.height) == (62, 46)
    assert not list(tmp_path.glob(f"{r.json()['media_id']}.gif"))


# ── the video cut to another shape on a background ("Cắt 4:3" on 9:16) ─────────

def test_an_inner_shape_is_kept_only_beside_a_background():
    c = dub.normalize_canvas({"aspect": "9:16", "fit": "grid", "inner": "4:3", "cut": 0.25})
    assert c["inner"] == "4:3" and c["cut"] == 0.25
    assert dub.normalize_canvas({"aspect": "9:16", "fit": "crop", "inner": "4:3"})["inner"] == ""
    assert dub.normalize_canvas({"aspect": "9:16", "fit": "grid", "inner": "2:1"})["inner"] == ""
    # a "crop" fit saved before 31/10 kept its cut in pos
    assert dub.normalize_canvas({"aspect": "4:3", "fit": "crop", "pos": 0.2})["cut"] == 0.2
    assert dub.normalize_canvas({"aspect": "9:16", "fit": "grid", "pos": 0.2})["cut"] == 0.5


def test_the_video_cut_to_4_3_sits_on_the_9_16_screen():
    c = {"fit": "grid", "inner": "4:3", "cut": 0.5, "scale": 1.0, "pos": 0.5}
    assert dub.inner_crop(1280, 720, c) == (160, 0, 960, 720)
    assert dub.inner_crop(1280, 720, {**c, "cut": 0.0})[0] == 0 and dub.inner_crop(1280, 720, {**c, "cut": 1.0})[0] == 320
    assert dub.inner_crop(1280, 720, {**c, "inner": "16:9"}) is None  # already that shape
    assert dub.inner_crop(1280, 720, {**c, "fit": "crop"}) is None
    x, y, w, h = dub.canvas_rect(1280, 720, 720, 1280, c)
    assert (x, y, w, h) == (0, 370, 720, 540)
    assert "crop=960:720:160:0,scale=720:540" in dub.canvas_filter(c, 1280, 720, 720, 1280)
    # a portrait video cut to 1:1: top and bottom trimmed
    assert dub.inner_crop(720, 1280, {**c, "inner": "1:1"}) == (0, 280, 720, 720)
    # same frame as the source but cut to another shape: still work to do
    assert dub.canvas_filter({**c, "inner": "1:1"}, 720, 1280, 720, 1280) != ""


@needs_ffmpeg
@pytest.mark.parametrize("cut,left_red", [(0.5, False), (0.0, True)])
def test_a_cut_video_really_renders_on_its_background(tmp_path, cut, left_red):
    """A 16:9 clip with a red left edge, cut to 4:3 onto a 9:16 background: the background above, the red edge gone
    when cut in the middle, kept when cut from the left."""
    src = tmp_path / "src.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=blue:size=320x180:rate=10:duration=1,drawbox=x=0:y=0:w=30:h=180:color=red:t=fill",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    lay = {"canvas": {"aspect": "9:16", "fit": "color", "color": "#123456", "inner": "4:3", "cut": cut}}
    w, h = dub.canvas_size(320, 180, lay)
    assert (w, h) == (180, 320)
    ass = dub.write_sub_ass([], tmp_path / "s.ass", width=w, height=h, layout=lay)
    out = tmp_path / "out.mp4"
    graph = dub.video_filter(ass, w, h, lay, source=(320, 180))
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-filter_complex", graph, "-map", "[v]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    img = _frame_pixels(out, 0.5, tmp_path / "f.png")
    x, y, rw, rh = dub.canvas_rect(320, 180, w, h, dub.normalize_canvas(lay["canvas"]))
    assert (rw, rh) == (180, 136) and _near(img.getpixel((90, 10)), "#123456")  # above the video: the background
    assert _near(img.getpixel((90, y + rh // 2)), "#0000ff", 60)  # the middle of the video
    assert _near(img.getpixel((3, y + rh // 2)), "#ff0000", 70) == left_red


# ── subtitles in CJK, subtitle languages ────────────────────────────────────

def test_chinese_lines_are_cut_by_width_not_spaces():
    text = "你好世界这是一个很长的测试字幕句子没有空格"  # 21 characters, 42 width units
    parts = dub.split_cue(0, 4, text, 20)
    assert len(parts) == 3 and all(dub.text_units(p[2]) <= 20 for p in parts)
    assert "".join(p[2] for p in parts) == text and parts[-1][1] == 4
    assert all(not p[2].startswith("，") for p in dub.split_cue(0, 2, "你好世界你好世界你好，世界你好", 8))
    # spaced languages split as before
    assert [c[2] for c in dub.split_cue(0, 2, "one two three four", 9)] == ["one two", "three", "four"]
    assert [c[2] for c in dub.split_cue(0, 2, "안녕하세요 여러분 반갑습니다", 12)] == ["안녕하세요", "여러분", "반갑습니다"]


def test_subtitles_in_the_videos_own_language_or_another(monkeypatch):
    from flowboard.services import free_translate

    calls: list[tuple] = []

    def fake(lines, source=None, target="vi", **k):
        calls.append((source, target))
        return [f"[{target}] {x}" for x in lines], "google"

    monkeypatch.setattr(free_translate, "translate_lines", fake)
    job = dub.Job(id="l", url=None, source_media_id="x", language="en", mode="sub", sub_lang="orig", title="A great phone")
    job.segments = [dub.Segment(0, 1, "Hello there", ""), dub.Segment(1, 2, "Buy it now", "")]
    asyncio.run(dub._translate(job))
    assert [s.text for s in job.segments] == ["Hello there", "Buy it now"] and job.translated_by == "none"
    assert calls == [("en", "vi")] and job.title == "[vi] A great phone"  # only the clip name goes Vietnamese
    calls.clear()
    job.sub_lang = "ja"
    asyncio.run(dub._translate(job))
    assert job.segments[0].text == "[ja] Hello there" and ("en", "ja") in calls
    calls.clear()
    job.sub_lang = "en"  # an English video asked for English subtitles: not translated
    asyncio.run(dub._translate(job))
    assert job.segments[0].text == "Hello there" and all(t == "vi" for _, t in calls)
    job.mode, job.sub_lang = "dub", "ja"  # a voice-over always reads Vietnamese
    asyncio.run(dub._translate(job))
    assert job.segments[0].text == "[vi] Hello there"


def test_the_editor_switches_the_subtitle_language(client, monkeypatch):
    from flowboard.services import free_translate

    monkeypatch.setattr(free_translate, "translate_lines",
                        lambda lines, source=None, target="vi", **k: ([f"<{target}> {x}" for x in lines], "google"))
    job = dub.Job(id="beef00000001", url=None, source_media_id="x", language="en", mode="sub", status="done")
    job.segments = [dub.Segment(0, 1, "Hello", "Xin chào")]
    dub.JOBS[job.id] = job
    try:
        r = client.post(f"/api/dub/jobs/{job.id}/subtitles", json={"lang": "orig"})
        assert r.status_code == 200 and r.json()["lines"] == ["Hello"] and r.json()["translated_by"] == "none"
        assert client.post(f"/api/dub/jobs/{job.id}/subtitles", json={"lang": "ko"}).json()["lines"] == ["<ko> Hello"]
        assert client.post(f"/api/dub/jobs/{job.id}/subtitles", json={"lang": "xx"}).status_code == 422
        assert job.segments[0].text == "Xin chào"  # nothing saved until the export
        restored = dub._job_from_dict(dub.snapshot(dub.Job(id="s", url=None, source_media_id="x", sub_lang="en")), Path("."), 0)
        assert restored.sub_lang == "en"
    finally:
        dub.JOBS.pop(job.id, None)


def test_a_voice_over_needs_vietnamese_lines(tmp_path):
    src = tmp_path / "s.mp4"
    src.write_bytes(b"x")
    job = dub.Job(id="beef00000002", url=None, source_media_id="x", language="en", mode="sub", sub_lang="en",
                  status="done", src_path=src)
    job.segments = [dub.Segment(0, 1, "Hello", "Hello")]
    with pytest.raises(dub.DubError, match="tiếng Việt"):
        dub.render_job(job, lines=None, voice=None, style=None, keep_bgm=None, name=None, mode="dub")
    assert job.mode == "sub" and job.status == "done"  # refused before anything changed
