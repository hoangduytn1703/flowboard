"""11/11: text on the picture ("🔤 Chữ": the title / second title of a cut part, free text), brightness / contrast /
saturation of the video, a look carried to another clip keeping that clip's own title, the encoder's real progress,
and "✂️ Cắt video" hearing the words in the background instead of making the seller wait."""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from flowboard.services import dub, video_cut

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or shutil.which("ffprobe") is None, reason="needs ffmpeg")


def _clip(path: Path, colour: str = "0x404040", size: str = "320x180", seconds: float = 2.0) -> Path:
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={colour}:size={size}:rate=10:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}", "-shortest", "-c:a", "aac",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _pixel(video: Path, at: float, out: Path, x: float, y: float) -> tuple[int, int, int]:
    from PIL import Image

    subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", f"{at}", "-i", str(video), "-frames:v", "1", str(out)], check=True)
    im = Image.open(out).convert("RGB")
    return im.getpixel((int(im.width * x), int(im.height * y)))


def _cut_job(title: str = "Mẹo số 1", subtitle: str = "Ai cũng làm sai") -> dub.Job:
    job = dub.Job(id="7e57000000a1", url=None, source_media_id="src", mode="sub", sub_lang="none")
    job.kind, job.name, job.title = "cut", title, title
    job.cut = {"session_id": "s", "run_id": "r", "index": 1, "total": 2, "start": 0, "end": 10, "subtitle": subtitle}
    return job


def test_text_layers_are_kept_in_shape():
    lay = dub.normalize_layout({"texts": [
        {"role": "title", "text": "  Xin   chào \n\n bạn ", "x": 5, "y": -1, "size": 99, "color": "#FFF", "bg": "#E5322D"},
        {"role": "title", "text": "tiêu đề thứ hai", "on": False},
        {"role": "subtitle", "text": ""},
        {"role": "lạ", "text": "chữ tự do", "bg": "không phải màu", "secs": 3},
        "rác",
    ]})
    a, b, c, d = lay["texts"]
    assert a == {"role": "title", "on": True, "text": "Xin chào\nbạn", "x": 0.98, "y": 0.03, "size": 4.0, "color": "#ffffff",
                 "bg": "#e5322d", "w": 0.86, "bold": True, "weight": 1.0, "italic": False, "underline": False, "secs": 0.0}
    assert b["role"] == "text" and b["on"] is False          # only one title
    assert c["role"] == "subtitle" and c["text"] == ""        # an empty slot stays in the editor…
    assert d["role"] == "text" and d["bg"] == "" and d["secs"] == 3.0
    assert [t["text"] for t in dub.shown_texts(lay)] == ["Xin chào\nbạn", "chữ tự do"]  # …and is not drawn
    assert len(dub.normalize_layout({"texts": [{"text": str(i)} for i in range(20)]})["texts"]) == dub.MAX_TEXTS
    assert dub.normalize_layout(None)["texts"] == [] and dub.normalize_layout(None)["adjust"] is None


def test_text_layers_become_ass_styles_and_events():
    texts = dub.normalize_texts([
        {"role": "title", "text": "Tiêu đề rất dài cần xuống dòng vì khung hẹp {x}", "y": 0.1, "w": 0.5, "color": "#ffffff", "bg": "#e5322d"},
        {"role": "text", "text": "chữ viền", "x": 0.25, "y": 0.5, "color": "#141414", "bg": "", "bold": False, "secs": 3},
    ])
    styles, events = dub.text_ass(texts, 720, 1280, 10.0)
    assert len(styles) == 2 and len(events) == 2
    box, outline = styles
    # a filled box: BorderStyle 3 in the box colour (ASS is BGR), bold
    assert box.startswith("Style: T0,Arial,") and ",&H00FFFFFF," in box and "&H002D32E5,&H002D32E5,-1," in box and ",3," in box
    # no box: outlined text — a light edge round dark text, not bold
    assert ",&H00141414," in outline and ",&H00FFFFFF,&H80000000,0," in outline and ",1," in outline
    assert "{\\an5\\pos(360,128)}" in events[0] and "\\N" in events[0] and "{x}" not in events[0] and "(x)" in events[0]
    assert events[0].startswith("Dialogue: 2,0:00:00.00,0:00:10.00,T0,")
    assert events[1].startswith("Dialogue: 2,0:00:00.00,0:00:03.00,T1,") and "{\\an5\\pos(180,640)}chữ viền" in events[1]
    assert dub.wrap_text("một hai ba bốn\nnăm", 8) == ["một hai", "ba bốn", "năm"]


def test_brightness_contrast_and_saturation_become_filters():
    assert dub.normalize_adjust({"brightness": 1, "contrast": 1.002, "saturation": 1}) is None
    assert dub.normalize_adjust({"brightness": 9, "contrast": 0, "saturation": -1}) == {"brightness": 1.8, "contrast": 0.5, "saturation": 0.0}
    assert dub.adjust_filter(None) == "" and dub.adjust_filter({"brightness": 1}) == ""
    only_bright = dub.adjust_filter({"brightness": 1.3})
    assert only_bright.startswith("lutyuv=y='clip((val-minval)*1.300+minval") and "eq=" not in only_bright
    assert dub.adjust_filter({"contrast": 1.2, "saturation": 0.5}) == "eq=contrast=1.200:saturation=0.500"
    graph = dub.video_filter(Path("subs.ass"), 320, 180, {"adjust": {"brightness": 1.3}})
    assert graph.startswith("[0:v]lutyuv=") and "[va];[va]ass=" in graph  # the video itself, before everything else
    job = dub.Job(id="7e57000000a0", url=None, source_media_id="src")
    assert not dub.has_picture_layers(job)
    job.layout = {"adjust": {"brightness": 0.8}}
    assert dub.has_picture_layers(job)
    job.layout = {"texts": [{"role": "title", "text": "A", "on": False}]}
    assert not dub.has_picture_layers(job)  # a slot that is off puts nothing on the picture


def test_a_look_from_another_clip_keeps_this_clips_own_title():
    theirs = {"y": 0.7, "texts": [
        {"role": "title", "text": "Tiêu đề của clip KHÁC", "y": 0.2, "size": 2, "bg": "#000000"},
        {"role": "subtitle", "text": "phụ của clip khác"},
        {"role": "text", "text": "@kenhcuatoi", "y": 0.95},
    ]}
    job = _cut_job()
    lay = dub.carry_texts(job, theirs)
    assert [t["text"] for t in lay["texts"]] == ["Mẹo số 1", "Ai cũng làm sai", "@kenhcuatoi"]
    assert lay["texts"][0]["y"] == 0.2 and lay["texts"][0]["size"] == 2.0 and lay["y"] == 0.7   # their place and size
    # words this clip already typed win over the title it was cut with
    job.layout = {"texts": [{"role": "title", "text": "Tự gõ lại", "on": False}]}
    assert dub.carry_texts(job, theirs)["texts"][0]["text"] == "Tự gõ lại"
    # a dubbed video has no cut title: the layer comes over empty (and is not drawn)
    plain = dub.Job(id="7e57000000a2", url=None, source_media_id="src")
    assert [t["text"] for t in dub.carry_texts(plain, theirs)["texts"]] == ["", "", "@kenhcuatoi"]
    # a saved look never keeps one clip's title; free text stays
    preset = dub.normalize_look_preset({"layout": theirs})
    assert [t["text"] for t in preset["layout"]["texts"]] == ["", "", "@kenhcuatoi"]
    dub.apply_look(job, preset)
    assert [t["text"] for t in job.layout["texts"]] == ["Tự gõ lại", "Ai cũng làm sai", "@kenhcuatoi"]


@needs_ffmpeg
def test_a_render_burns_the_text_brightens_the_video_and_reports_progress(tmp_path, monkeypatch):
    from flowboard import config
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(dub, "status", lambda: {"separate": False, "available": True})
    src = _clip(tmp_path / "src.mp4")
    job = _cut_job()
    job.duration_s = 2.0
    job.work = tmp_path / "dub" / job.id
    job.work.mkdir(parents=True)
    job.src_path = src
    job.layout = {"adjust": {"brightness": 1.6},
                  "texts": [{"role": "title", "text": "MMMMMMMM", "y": 0.25, "size": 3, "color": "#ffffff", "bg": "#e5322d"},
                            {"role": "text", "text": "ẩn", "on": False}]}
    seen: list[int] = []
    real_set = dub._set

    def spy(j, phase, progress):
        seen.append(progress)
        real_set(j, phase, progress)

    monkeypatch.setattr(dub, "_set", spy)
    dub._render(job)
    assert job.status == "done", job.error
    out = media_service.MEDIA_CACHE_DIR / f"{job.media_id}.mp4"
    grey = _pixel(out, 1.0, tmp_path / "f.png", 0.5, 0.85)
    assert 85 <= grey[0] <= 120, grey                          # 0x40 (64) × 1.6 ≈ 102: brighter than the source
    from PIL import Image

    row = Image.open(tmp_path / "f.png").convert("RGB")      # the row through the title: its red box, white letters
    line = [row.getpixel((x, int(row.height * 0.25))) for x in range(row.width)]
    assert any(r > 170 and g < 110 and b < 110 for r, g, b in line), line[::16]
    assert any(r > 200 and g > 200 and b > 200 for r, g, b in line)
    assert line[2][0] < 130                                    # …and outside the box it is still the (brightened) video
    ass = (job.work / "subs.ass").read_text(encoding="utf-8")
    assert "Style: T0," in ass and "T1" not in ass and "}MMMMMMMM" in ass
    # a render with nothing to read again shows the encoder's own progress from the start, not "91 %" all along
    assert seen[0] <= 5 and job.progress == 100


def test_the_encoder_is_stopped_when_asked(tmp_path):
    if FFMPEG is None:
        pytest.skip("needs ffmpeg")
    out = tmp_path / "long.mp4"
    cmd = [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=600", "-c:v", "libx264", str(out)]
    fractions: list[float] = []
    t0 = time.time()
    err = dub._run_encode(cmd, 120, 600.0, fractions.append, stop=lambda: len(fractions) >= 2)
    assert err == "Đã dừng theo yêu cầu" and time.time() - t0 < 60
    assert fractions and all(0 <= f <= 1 for f in fractions)


def test_an_analysed_video_is_ready_before_it_is_heard(monkeypatch):
    """"🔍 Phân tích": downloaded = the card opens; Whisper runs behind it and fills in the lines when done."""
    monkeypatch.setattr(video_cut, "_pump", lambda: None)
    monkeypatch.setattr(video_cut.dub, "status", lambda: {"available": True})
    _, made = video_cut.start(links=["https://youtu.be/a"], media=[], analyze=True, how="manual")
    s = made[0]
    go = {"now": False}
    heard: list[str] = []

    def fetched(x):  # the download + probe only (analysed videos are not heard here)
        x.duration_s, x.prepared = 95.0, True

    def fake_hear(x, *, progress, stop):
        progress(27)
        while not go["now"] and not stop():
            time.sleep(0.02)
        if stop():
            raise video_cut.dub.DubError("Đã dừng theo yêu cầu")
        x.segments, x.heard, x.language = [{"start": 1.0, "end": 4.0, "text": "xin chào"}, {"start": 40.0, "end": 44.0, "text": "tạm biệt"}], True, "vi"
        heard.append(x.id)

    monkeypatch.setattr(video_cut, "_prepare", fetched)
    monkeypatch.setattr(video_cut, "_hear", fake_hear)
    try:
        video_cut._run(s)
        # ready at once: the parts can be typed and cut while the words are still being heard
        assert s.status == "review" and "Đã tải xong" in s.phase and not s.heard
        for _ in range(100):
            if s.hear == "run":
                break
            time.sleep(0.02)
        assert s.hear == "run" and s.hear_progress == 27
        view = video_cut.public(s, brief=True)
        assert view["hear"] == "run" and view["hear_progress"] == 27
        assert any(it["key"] == f"cuthear:{s.id}" for it in video_cut.running_items())
        # the AI needs the words: it says so instead of quietly splitting evenly; an even split works at once
        import asyncio

        with pytest.raises(video_cut.CutError, match="đang nghe lời"):
            asyncio.run(video_cut.suggest_again(s, how="ai", prompt="", min_s=30, max_s=60, max_parts=0))
        res = asyncio.run(video_cut.suggest_again(s, how="even", prompt="", min_s=30, max_s=60, max_parts=0))
        assert res["by"] == "even" and res["rows"]
        go["now"] = True
        for _ in range(200):
            if s.hear == "done":
                break
            time.sleep(0.02)
        assert s.hear == "done" and s.heard and len(s.segments) == 2 and heard == [s.id]
        assert video_cut.hear_outcome(s.id)["ok"] is True
    finally:
        s.hear_stop = True
        video_cut.SESSIONS.pop(s.id, None)


def test_hearing_can_be_skipped_and_started_again(monkeypatch):
    monkeypatch.setattr(video_cut, "_pump", lambda: None)
    monkeypatch.setattr(video_cut.dub, "status", lambda: {"available": True})
    _, made = video_cut.start(links=["https://youtu.be/b"], media=[], analyze=True, how="manual")
    s = made[0]
    s.prepared, s.duration_s, s.status = True, 60.0, "review"
    calls: list[int] = []

    def fake_hear(x, *, progress, stop):
        calls.append(1)
        progress(10)
        while not stop():
            time.sleep(0.02)
        raise video_cut.dub.DubError("Đã dừng theo yêu cầu")

    monkeypatch.setattr(video_cut, "_hear", fake_hear)
    try:
        video_cut.hear_later(s)
        for _ in range(100):
            if s.hear == "run":
                break
            time.sleep(0.02)
        video_cut.hear_skip(s)
        for _ in range(100):
            if s.hear == "skip":
                break
            time.sleep(0.02)
        assert s.hear == "skip" and not s.heard and s.hear_error == ""
        video_cut.hear_later(s)  # "🎧 Nghe lời" again
        for _ in range(100):
            if len(calls) == 2:
                break
            time.sleep(0.02)
        assert len(calls) == 2
        # a restart in the middle: the session comes back "not heard", never stuck on "đang nghe"
        back = video_cut._from_dict({**s.to_dict(), "hear": "run"}, s.work)
        assert back.hear == "" and back.hear_progress == 0
    finally:
        s.hear_stop = True
        video_cut.SESSIONS.pop(s.id, None)


def test_a_part_cut_again_follows_its_new_title_and_the_pages_brightness():
    s = video_cut.Session(id="c0ffee0000b1", run_id="run0000000b1", title="Video", duration_s=100.0, prepared=True, status="review")
    job = _cut_job("Tên cũ", "Phụ cũ")
    job.layout = {"texts": [{"role": "title", "text": "Tên cũ", "on": True}, {"role": "subtitle", "text": "tự gõ", "on": True}]}
    # needs_render: a visible title is something to put on the raw cut; slots that are off are not
    assert video_cut.needs_render(job)
    job.layout = {"texts": [{"role": "title", "text": "Tên cũ", "on": False}]}
    assert not video_cut.needs_render(job)
    assert dub.default_text(job, "title") == "Tên cũ" and dub.default_text(job, "subtitle") == "Phụ cũ"
    assert s.adjust is None and "adjust" in video_cut.Session.SAVED and "hear" in video_cut.Session.SAVED


def test_speed_is_kept_in_range_and_goes_on_last():
    assert dub.normalize_layout(None)["speed"] == 1.0 and dub.normalize_layout({"speed": 1.003})["speed"] == 1.0
    assert dub.normalize_layout({"speed": 9})["speed"] == 3.0 and dub.normalize_layout({"speed": 0.1})["speed"] == 0.8
    assert dub.normalize_layout({"speed": "nhanh"})["speed"] == 1.0
    assert dub.atempo_chain(1.5) == "atempo=1.500" and dub.atempo_chain(3.0) == "atempo=2.0,atempo=1.500"
    graph, v, a = dub.speed_graph(2.0, "30", "[v]", "0:a:0")
    assert graph == "[v]setpts=PTS/2.000,fps=30[vsp];[0:a:0]atempo=2.000[asp]" and (v, a) == ("[vsp]", "[asp]")
    assert dub.speed_graph(0.8, "25", "[v]", None) == ("[v]setpts=PTS/0.800,fps=25[vsp]", "[vsp]", None)
    job = _cut_job()
    job.layout = {"speed": 1.5}
    assert video_cut.needs_render(job)  # a speed is something to export


@needs_ffmpeg
def test_the_export_plays_at_the_speed_set(tmp_path, monkeypatch):
    from flowboard import config
    from flowboard.services import media as media_service
    from flowboard.services.video_export import probe_clip

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(dub, "status", lambda: {"separate": False, "available": True})
    src = _clip(tmp_path / "src.mp4", seconds=6.0)
    job = _cut_job()
    job.duration_s = 6.0
    job.work = tmp_path / "dub" / job.id
    job.work.mkdir(parents=True)
    job.src_path = src
    job.layout = {"speed": 2.0, "texts": [{"role": "title", "text": "Nhanh gấp đôi"}]}
    dub._render(job)
    assert job.status == "done", job.error
    out = probe_clip(media_service.MEDIA_CACHE_DIR / f"{job.media_id}.mp4")
    assert out is not None and out.has_audio and 2.7 <= out.duration <= 3.4, out   # 6 s at 2× = 3 s, sound included
    # the same file re-timed afterwards (what the Remotion engine does)
    copy = tmp_path / "again.mp4"
    shutil.copy(src, copy)
    dub.retime_file(FFMPEG, copy, 3.0)
    again = probe_clip(copy)
    assert again is not None and 1.7 <= again.duration <= 2.4


def test_volume_and_text_styles():
    assert dub.normalize_layout(None)["volume"] == 1.0 and dub.normalize_layout({"volume": 5})["volume"] == 3.0
    assert dub.normalize_layout({"volume": 0})["volume"] == 0.0 and dub.normalize_layout({"volume": "to"})["volume"] == 1.0
    assert dub.volume_graph(1.0, "0:a:0") == ("", "0:a:0") and dub.volume_graph(2.0, None) == ("", None)
    assert dub.volume_graph(0.5, "[a]") == ("[a]volume=0.50[avol]", "[avol]")
    assert dub.volume_graph(2.0, "0:a:0") == ("[0:a:0]volume=2.00,alimiter=limit=0.97[avol]", "[avol]")
    job = dub.Job(id="vol", url=None, source_media_id="m", sub_lang="none")
    job.layout = {"volume": 1.5}
    assert video_cut.needs_render(job)  # a louder clip is something to export
    t = dub.normalize_texts([{"role": "title", "text": "Xin chào", "italic": True, "underline": True, "bold": False}])[0]
    assert (t["bold"], t["italic"], t["underline"]) == (False, True, True)
    assert dub.normalize_texts([{"role": "title", "text": "a"}])[0]["italic"] is False
    styles, _ = dub.text_ass([t], 720, 1280, 10.0)
    assert ",0,-1,-1,0,100,100," in styles[0]  # Bold, Italic, Underline, StrikeOut


def test_bold_can_be_lighter_or_heavier():
    mk = lambda **kw: dub.normalize_texts([{"role": "title", "text": "Đậm", **kw}])[0]
    assert mk()["weight"] == 1.0 and mk(weight=9)["weight"] == 2.5 and mk(weight=0)["weight"] == 0.3
    assert dub.text_weight(mk(), 40) == (True, 0.0) and dub.text_weight(mk(bold=False, weight=2), 40) == (False, 0.0)
    assert dub.text_weight(mk(weight=0.5), 40) == (False, 0.44) and dub.text_weight(mk(weight=2), 40) == (True, 1.2)
    styles, events = dub.text_ass([mk(weight=2)], 720, 1280, 5.0)
    assert len(styles) == 2 and styles[1].startswith("Style: T0s,") and len(events) == 2 and ",T0s," in events[1]
    styles, events = dub.text_ass([mk()], 720, 1280, 5.0)
    assert len(styles) == 1 and len(events) == 1
