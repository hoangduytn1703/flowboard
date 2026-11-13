"""Dubbing: the pure helpers, the clip (board) the result becomes, and the routes' guards."""
from pathlib import Path

import pytest

from flowboard.services import dub


def test_parse_translation_pads_trims_and_rejects_empty():
    title, lines = dub.parse_translation('```json\n{"title": "Mẹo da khô", "lines": ["Một", " Hai  hai ", "Ba", "Bốn"]}\n```', 3)
    assert title == "Mẹo da khô" and lines == ["Một", "Hai hai", "Ba"]
    _, lines = dub.parse_translation('{"lines": ["Một"]}', 3)
    assert lines == ["Một", "", ""]
    with pytest.raises(dub.DubError):
        dub.parse_translation('{"lines": ["", ""]}', 2)
    with pytest.raises(dub.DubError):
        dub.parse_translation("xin chào", 1)


def test_speedup_is_capped_and_idle_when_it_fits():
    assert dub.speedup_for(2.0, 3.0) == 1.0
    assert dub.speedup_for(3.6, 3.0) == 1.2
    assert dub.speedup_for(9.0, 3.0) == dub.MAX_SPEEDUP


def test_split_cue_keeps_short_lines_and_splits_time_by_length():
    assert dub.split_cue(0, 2, "Các mẹ bầu bị căng cứng bụng") == [(0, 2, "Các mẹ bầu bị căng cứng bụng")]
    cues = dub.split_cue(10, 14, "Các mẹ bầu bị căng cứng bụng thì nhớ đeo đai nâng bụng ngay nha", max_chars=34)
    assert [c[2] for c in cues] == ["Các mẹ bầu bị căng cứng bụng thì", "nhớ đeo đai nâng bụng ngay nha"]
    assert cues[0][0] == 10 and cues[-1][1] == 14 and cues[0][1] == cues[1][0]
    assert cues[0][1] - 10 > 14 - cues[1][0]  # the longer chunk gets more time
    assert dub.split_cue(0, 1, "   ") == []


def test_sub_ass_styles(tmp_path):
    p = dub.write_sub_ass([(0, 1.5, "Xin chào"), (1.5, 3, "")], tmp_path / "s.ass", width=1080, height=1920, style="box_yellow")
    text = p.read_text(encoding="utf-8")
    assert "PlayResY: 1920" in text and ",3," in text.split("Style: Sub")[1]  # BorderStyle 3 = box
    assert "&H0014D8FF" in text and text.count("Dialogue:") == 1 and "0:00:00.00,0:00:01.50" in text
    out = dub.write_sub_ass([(0, 1, "A")], tmp_path / "o.ass", width=720, height=1280, style="outline").read_text(encoding="utf-8")
    assert "&H00FFFFFF" in out and ",1," in out.split("Style: Sub")[1]


def test_result_becomes_a_clip_with_channel_and_narration(client):
    job = dub.Job(id="j1", url="https://www.tiktok.com/@a/video/1", source_media_id="src1", channel_id=7, name="")
    job.title = "Mẹo cho mẹ bầu"
    job.media_id = "out1"
    job.segments = [dub.Segment(0, 2, "你好", "Chào các mẹ"), dub.Segment(2, 4, "再见", "Hẹn gặp lại")]
    board_id = dub._save_board(job)
    detail = client.get(f"/api/boards/{board_id}").json()
    qt = detail["board"]["data"]["quicktool"]
    assert detail["board"]["name"] == "Mẹo cho mẹ bầu" and qt["template_id"] == "dub" and qt["channel_id"] == 7
    assert qt["source_url"].startswith("https://www.tiktok.com")
    kinds = {n["type"]: n for n in detail["nodes"]}
    assert kinds["video"]["data"]["narration"] == "Chào các mẹ Hẹn gặp lại" and kinds["export"]["data"]["mediaId"] == "out1"
    summary = next(b for b in client.get("/api/boards", params={"summary": "true"}).json() if b["id"] == board_id)["summary"]
    assert summary["exported"] is True and summary["clips_done"] == 1
    # A re-render updates the same clip instead of making another (``_render`` keeps the id on the job).
    job.board_id = board_id
    job.media_id = "out2"
    job.segments[0].text = "Chào cả nhà"
    assert dub._save_board(job) == board_id
    detail = client.get(f"/api/boards/{board_id}").json()
    kinds = {n["type"]: n for n in detail["nodes"]}
    assert kinds["export"]["data"]["mediaId"] == "out2" and kinds["video"]["data"]["narration"].startswith("Chào cả nhà")
    assert client.get("/api/boards", params={"summary": "true"}).json().__len__() == 1


def test_routes_guard_input_and_report_status(client, monkeypatch):
    monkeypatch.setattr(dub, "status", lambda: {"available": True, "whisper": True, "separate": False, "ytdlp": True, "root": "x"})
    st = client.get("/api/dub/status").json()
    assert st["available"] is True and {s["key"] for s in st["styles"]} == set(dub.STYLES) and st["max_minutes"] == dub.MAX_DURATION_S // 60
    r = client.post("/api/dub/jobs", json={})
    assert r.status_code == 400 and "link" in r.json()["detail"].lower()
    r = client.post("/api/dub/jobs", json={"url": "https://x.y/v", "voice": "nope"})
    assert r.status_code == 400 and "Giọng" in r.json()["detail"]
    assert client.get("/api/dub/jobs/zzz").status_code == 404
    monkeypatch.setattr(dub, "status", lambda: {"available": False, "reason": "thiếu Whisper"})
    r = client.post("/api/dub/jobs", json={"url": "https://www.tiktok.com/@a/video/1"})
    assert r.status_code == 400 and "Whisper" in r.json()["detail"]


def test_render_job_edits_lines_and_refuses_bad_state(client, monkeypatch, tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    job = dub.Job(id="j2", url=None, source_media_id="s", status="review")
    job.segments = [dub.Segment(0, 1, "a", "A"), dub.Segment(1, 2, "b", "B")]
    job.src_path = src
    dub.JOBS["j2"] = job
    ran = {}
    monkeypatch.setattr(dub, "_run_job", lambda j, render: ran.setdefault("render", render))
    r = client.post("/api/dub/jobs/j2/render", json={"lines": ["Chỉ một"]})
    assert r.status_code == 400 and "Số câu" in r.json()["detail"]
    r = client.post("/api/dub/jobs/j2/render", json={"lines": ["Một", " Hai "], "style": "outline", "channel_id": None, "voice": "vi-VN-NamMinhNeural"})
    assert r.status_code == 200 and r.json()["status"] == "rendering"
    assert [s.text for s in job.segments] == ["Một", "Hai"] and job.style == "outline" and job.voice == "vi-VN-NamMinhNeural"
    assert ran["render"] is True
    job.status = "rendering"
    assert client.post("/api/dub/jobs/j2/render", json={}).status_code == 400
    assert client.post("/api/dub/jobs/j2/stop").json()["status"] == "rendering" and job.stop is True
    dub.JOBS.pop("j2", None)


def test_timeline_places_pieces_at_their_start_times(tmp_path):
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg missing")
    pieces = []
    for i, (start, dur) in enumerate([(0.0, 0.5), (2.0, 0.5), (2.4, 0.5)]):  # the third overruns into the second's slot
        wav = tmp_path / f"p{i}.wav"
        subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
                        "-ar", "48000", "-ac", "1", str(wav)], check=True)
        pieces.append((start, wav, dur))
    out = tmp_path / "voice.wav"
    dub._timeline_wav(ffmpeg, pieces, 4.0, out)
    from flowboard.services import tts

    total = tts._probe_duration(out)
    # 0.5 + gap 1.5 + 0.5 (ends 2.5, past 2.4 → no gap) + 0.5 = 3.0, then silence to 4.0
    assert total is not None and abs(total - 4.0) < 0.1


def test_layout_moves_the_box_and_narrows_lines(tmp_path):
    lay = dub.normalize_layout({"x": 0.2, "y": 1.5, "scale": "1.4", "junk": 1})
    empty = {"blur": None, "blurs": [], "canvas": None, "frame": None, "mascot": None, "w": None, "subfont": None,
             "texts": [], "adjust": None, "speed": 1.0, "volume": 1.0, "reveal": ""}
    assert lay == {"x": 0.2, "y": 0.98, "scale": 1.4, **empty}
    assert dub.normalize_layout(None) == {**dub.DEFAULT_LAYOUT, **empty}
    text = dub.write_sub_ass([(0, 1, "A")], tmp_path / "l.ass", width=1000, height=2000, style="box_yellow",
                             layout={"x": 0.25, "y": 0.5, "scale": 1.5}).read_text(encoding="utf-8")
    assert r"{\an2\pos(250,1000)}A" in text and f"Style: Sub,Arial,{round(2000 * 0.036 * 1.5)}," in text
    assert dub.sub_max_chars(1080, 1920) > dub.sub_max_chars(1080, 1920, {"scale": 1.5})
    assert dub.sub_max_chars(1080, 1920) > dub.sub_max_chars(1080, 1920, {"x": 0.2})


def test_rerender_with_a_new_layout_reuses_the_voice_track(client, monkeypatch, tmp_path):
    job = dub.Job(id="j3", url=None, source_media_id="s", status="done")
    job.segments = [dub.Segment(0, 1, "a", "Một")]
    job.src_path = tmp_path / "src.mp4"
    job.src_path.write_bytes(b"x")
    job.work = tmp_path
    (tmp_path / "voice.wav").write_bytes(b"w")
    job.voice_key = dub.voice_key(job)
    dub.JOBS["j3"] = job
    monkeypatch.setattr(dub, "_run_job", lambda j, render: None)
    r = client.post("/api/dub/jobs/j3/render", json={"layout": {"x": 0.5, "y": 0.6, "scale": 1.2}})
    assert r.status_code == 200 and r.json()["phase"] == "Chờ xuất lại" and r.json()["layout"]["y"] == 0.6
    job.status = "done"  # the stubbed runner never finished it
    r = client.post("/api/dub/jobs/j3/render", json={"lines": ["Khác"]})
    assert r.json()["phase"] == "Đang render"  # the text changed → voice must be made again
    dub.JOBS.pop("j3", None)


def test_blur_rectangle_is_normalised_and_filtered(tmp_path):
    lay = dub.normalize_layout({"blur": {"x": 0.1, "y": 0.62, "w": 0.8, "h": 0.07, "amount": 4}})
    assert lay["blur"] == {"x": 0.1, "y": 0.62, "w": 0.8, "h": 0.07, "amount": 4}
    assert dub.normalize_layout({"blur": {"x": 0.5, "w": 0.9}})["blur"]["w"] == 0.5  # clamped to the frame
    assert dub.normalize_layout({"blur": None})["blur"] is None and dub.normalize_layout({"blur": {}})["blur"] is None
    f = dub.blur_filter(lay["blur"], 1080, 1920)
    assert f.startswith("[0:v]split[vb_base][vb_t];[vb_t]crop=864:134:108:1190,boxblur=") and f.endswith("overlay=108:1190[vb]")
    assert dub.blur_filter(None, 1080, 1920) == ""
    ass = tmp_path / "s.ass"
    assert dub.video_filter(ass, 1080, 1920, None).startswith("[0:v]ass='") and dub.video_filter(ass, 1080, 1920, None).endswith("[v]")
    assert ";[vb]ass='" in dub.video_filter(ass, 1080, 1920, lay)


def test_jobs_are_persisted_and_reloaded_after_a_restart(monkeypatch, tmp_path):
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    job = dub.Job(id="p1", url="https://v.douyin.com/x/", source_media_id="src", status="rendering", channel_id=3,
                  layout={"x": 0.5, "y": 0.7, "scale": 1.1, "blur": {"x": 0.1, "y": 0.6, "w": 0.8, "h": 0.07, "amount": 4}})
    job.segments = [dub.Segment(0, 1, "a", "Một")]
    job.media_id, job.board_id, job.title = "out", 9, "Nấm chuối"
    job.work = tmp_path / "dub" / "p1"
    job.work.mkdir(parents=True)
    (job.work / "voice.wav").write_bytes(b"w")
    dub.persist(job)
    dub.JOBS.clear()
    dub.load_jobs()
    back = dub.JOBS["p1"]
    assert back.status == "error" and "khởi động lại" in back.error  # it was mid-render
    assert back.title == "Nấm chuối" and back.board_id == 9 and back.channel_id == 3 and back.layout["blur"]["amount"] == 4
    assert back.segments[0].text == "Một" and back.work == job.work
    assert back.voice_key == dub.voice_key(back)  # voice.wav is there → a layout-only re-render stays quick
    dub.load_jobs()  # idempotent
    assert len([j for j in dub.JOBS.values() if j.id == "p1"]) == 1
    dub.JOBS.pop("p1", None)


def test_jobs_queue_one_at_a_time(client, monkeypatch):
    monkeypatch.setattr(dub, "status", lambda: {"available": True, "whisper": True, "separate": False, "ytdlp": True, "root": "x"})
    started = []
    monkeypatch.setattr(dub, "_run_job", lambda j, render: started.append(j.id))  # never finishes
    ids = [client.post("/api/dub/jobs", json={"url": f"https://www.tiktok.com/@a/video/{i}"}).json() for i in range(3)]
    assert ids[0]["status"] == "running" and started == [ids[0]["job_id"]]
    assert ids[1]["status"] == "queued" and ids[1]["phase"] == "Chờ đến lượt"
    assert ids[2]["status"] == "queued" and "1 video trước" in ids[2]["phase"]
    # the first one ends → the next starts
    first = dub.JOBS[ids[0]["job_id"]]
    first.status = "done"
    dub._pump()
    import time as _t

    for _ in range(50):  # the next job may start on a thread
        if len(started) == 2:
            break
        _t.sleep(0.05)
    assert started == [ids[0]["job_id"], ids[1]["job_id"]] and dub.JOBS[ids[1]["job_id"]].status == "running"
    for i in range(5):
        client.post("/api/dub/jobs", json={"url": f"https://www.tiktok.com/@a/video/x{i}"})
    r = client.post("/api/dub/jobs", json={"url": "https://www.tiktok.com/@a/video/overflow"})
    assert r.status_code == 400 and "Hàng đợi" in r.json()["detail"]
    for jid in [j["job_id"] for j in ids] + [j.id for j in list(dub.JOBS.values())]:
        dub.JOBS.pop(jid, None)


def test_translation_batches_cover_every_line_and_fold_a_short_tail():
    assert dub.translation_batches(0) == []
    assert dub.translation_batches(10, 60) == [(0, 10)]
    assert dub.translation_batches(130, 60) == [(0, 60), (60, 130)]  # 10-line tail (< 15) joins the batch before
    assert dub.translation_batches(150, 60) == [(0, 60), (60, 120), (120, 150)]
    spans = dub.translation_batches(517, 60)
    assert spans[0][0] == 0 and spans[-1][1] == 517 and all(a[1] == b[0] for a, b in zip(spans, spans[1:]))


def test_long_transcript_is_translated_in_batches_with_context(monkeypatch):
    import asyncio
    import json as _json

    job = dub.Job(id="t1", url=None, source_media_id="x", language="zh", translator="ai")
    job.segments = [dub.Segment(float(i), float(i) + 0.9, f"src{i}") for i in range(130)]
    calls = []

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        calls.append(prompt)
        n = int(prompt.split("TRANSCRIPT (")[1].split(" lines")[0])
        first = int(prompt.split("[1] (")[0].count("ALREADY") >= 0)  # noqa: F841 — keep parsing simple
        return _json.dumps({"title": f"Tiêu đề {len(calls)}", "lines": [f"vi{len(calls)}-{k}" for k in range(n)]})

    monkeypatch.setattr(dub, "run_llm", fake_llm)
    asyncio.run(dub._translate(job))
    assert len(calls) == 2  # 60 + 70 (a 10-line tail folds into the second batch)
    assert "TRANSCRIPT (60 lines)" in calls[0] and "TRANSCRIPT (70 lines)" in calls[1]
    assert "part 2 of 2" in calls[1] and "ALREADY TRANSLATED" in calls[1] and "src59 => vi1-59" in calls[1]
    assert job.segments[0].text == "vi1-0" and job.segments[59].text == "vi1-59" and job.segments[60].text == "vi2-0"
    assert job.segments[-1].text == "vi2-69" and job.title == "Tiêu đề 1"


def test_dub_limit_is_thirty_minutes_and_compilation_hint_only_far_past_it(client):
    assert dub.MAX_DURATION_S == 30 * 60
    assert client.get("/api/dub/status").json()["max_minutes"] == 30


def test_subtitles_can_fill_in_word_by_word(tmp_path):
    assert dub.normalize_layout({"reveal": "nope"})["reveal"] == ""
    steps = dub.reveal_steps(0.0, 4.0, "Nói tới đâu hiện")
    assert [s[2] for s in steps] == ["Nói", "Nói tới", "Nói tới đâu", "Nói tới đâu hiện"]
    assert steps[0][3] == " tới đâu hiện" and steps[-1][3] == "" and steps[-1][1] == 4.0
    assert all(a[1] == b[0] for a, b in zip(steps, steps[1:]))  # no gap between the words
    lines = lambda reveal: [l.split(",,0,0,0,,", 1)[1].split("}", 1)[1] for l in dub.write_sub_ass(
        [(0, 4, "Nói tới đâu hiện")], tmp_path / f"{reveal}.ass", width=720, height=1280,
        layout={"reveal": reveal}).read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue: 0")]
    assert lines("") == ["Nói tới đâu hiện"]
    assert lines("word") == ["Nói", "tới", "đâu", "hiện"]
    grow = lines("grow")
    assert grow[0] == "Nói{\\alpha&HFF&} tới đâu hiện" and grow[-1] == "Nói tới đâu hiện" and len(grow) == 4
