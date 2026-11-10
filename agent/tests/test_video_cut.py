"""✂️ Cắt video (services/video_cut): links / files → many short videos, each a clip + an editing project of kind "cut"."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from flowboard.db import get_session
from flowboard.db.models import Asset, Board, Node
from flowboard.services import dub, video_cut
from flowboard.services.llm.base import LLMError
from flowboard.services.video_export import probe_clip

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or shutil.which("ffprobe") is None, reason="needs ffmpeg")


def _clip(path: Path, seconds: float) -> Path:
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=160x284:rate=10:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}", "-shortest", "-c:a", "aac",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _session(seconds: float = 120.0, lines: int = 12) -> video_cut.Session:
    s = video_cut.Session(id="c0ffee000001", run_id="run000000001", title="Mẹo vặt nhà bếp", duration_s=seconds,
                          prepared=True, heard=True, status="review")
    step = seconds / lines
    s.segments = [{"start": round(i * step + 0.3, 2), "end": round((i + 1) * step - 0.4, 2), "text": f"câu {i + 1}"} for i in range(lines)]
    return s


def _wait(pred, seconds: float = 60.0) -> None:
    for _ in range(int(seconds * 4)):
        if pred():
            return
        time.sleep(0.25)
    raise AssertionError("timed out")


def test_options_are_kept_in_range():
    assert video_cut.normalize_lengths(1, 2) == (5.0, 10.0)
    assert video_cut.normalize_lengths("30", "20") == (30.0, 35.0)
    assert video_cut.normalize_lengths(None, None) == (video_cut.DEFAULT_MIN_S, video_cut.DEFAULT_MAX_S)
    assert video_cut.normalize_how("oops") == "ai" and video_cut.normalize_max_parts(999) == 30
    assert len(video_cut.clean_prompt("x  " * 3000)) == video_cut.PROMPT_MAX
    # a long structured prompt keeps its lines
    assert video_cut.clean_prompt("Tiêu  đề:\r\n- 3 đến 8 từ\n\n\n\n2. Thời lượng  ") == "Tiêu đề:\n- 3 đến 8 từ\n\n2. Thời lượng"
    assert video_cut.normalize_title_lang(" Tây Ban Nha\n(x) ") == "Tây Ban Nha x"


def test_an_even_cut_ends_in_pauses_and_keeps_to_the_count_asked():
    s = _session(120.0)
    s.min_s, s.max_s = 20, 40
    rows = video_cut.even_rows(s)
    assert 3 <= len(rows) <= 5 and rows[0]["start"] == 0 and rows[-1]["end"] == 120.0
    pauses = {round((a["end"] + b["start"]) / 2, 2) for a, b in zip(s.segments, s.segments[1:])}
    assert all(r["end"] in pauses for r in rows[:-1])
    s.max_parts = 2
    assert len(video_cut.even_rows(s)) == 2


def test_the_ai_follows_the_request_and_says_when_it_cannot(monkeypatch):
    s = _session()
    s.how, s.prompt, s.min_s, s.max_s, s.max_parts = "prompt", "chỉ giữ đoạn có mẹo", 15, 45, 2
    seen = {}

    async def fake_llm(feature, prompt, **kw):
        seen["prompt"], seen["system"] = prompt, kw["system_prompt"]
        return ('{"parts": [{"from": 2, "to": 3, "title": "Mẹo một"}, {"from": 6, "to": 7, "title": "Mẹo hai"},'
                ' {"from": 9, "to": 10, "title": "Mẹo ba"}], "note": "Video chỉ có hai mẹo rõ"}')

    monkeypatch.setattr(video_cut, "run_llm", fake_llm)
    res = asyncio.run(video_cut.suggest(s))
    assert res["by"] == "ai" and [r["title"] for r in res["rows"]] == ["Mẹo một", "Mẹo hai"]  # at most 2
    assert res["note"] == "Video chỉ có hai mẹo rõ"
    assert "THE SELLER'S REQUEST (follow it): chỉ giữ đoạn có mẹo" in seen["prompt"] and "15-45 seconds" not in seen["prompt"]
    assert "as the request below says" in seen["prompt"] and "never more than 2" in seen["prompt"]
    # a part starts in the pause before its first line (not at 0: the AI skipped the opening)
    assert 0 < res["rows"][0]["start"] < s.segments[1]["start"]


def test_no_speech_or_no_whisper_or_a_failing_ai_cuts_evenly(monkeypatch):
    s = _session()
    s.segments, s.heard = [], False
    res = asyncio.run(video_cut.suggest(s))
    assert res["by"] == "even" and "Whisper" in res["note"] and res["rows"]
    s.heard = True
    assert "không có lời nói" in asyncio.run(video_cut.suggest(s))["note"]

    async def broken(*a, **kw):
        raise LLMError("hết lượt")

    s2 = _session()
    monkeypatch.setattr(video_cut, "run_llm", broken)
    res = asyncio.run(video_cut.suggest(s2))
    assert res["by"] == "even" and "hết lượt" in res["note"]


def test_a_part_gets_the_lines_inside_it_moved_to_zero():
    s = _session(20.0, 4)  # lines 0.3-4.6, 5.3-9.6, 10.3-14.6, 15.3-19.6
    segs = video_cut.part_lines(s, 4.0, 15.0)
    assert [(g.start, g.end, g.text) for g in segs] == [(0.0, 0.6, "câu 1"), (1.3, 5.6, "câu 2"), (6.3, 10.6, "câu 3")]


@needs_ffmpeg
def test_a_video_is_cut_into_clips_and_projects_then_edited(client, tmp_path, monkeypatch):
    from flowboard import config
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    src = _clip(tmp_path / "src.mp4", 10.0)
    with get_session() as db:
        db.add(Asset(kind="video", uuid_media_id="srcvid", local_path=str(src), mime="video/mp4"))
        db.commit()
    s = _session(10.0, 4)
    s.source_media_id, s.work = "srcvid", tmp_path / "cut" / s.id
    # the cut's "★ Mẫu chỉnh sửa": every part comes out square on a grid, rendered right after it is cut
    s.look = dub.normalize_look_preset({"layout": {"canvas": {"aspect": "1:1", "fit": "grid"}}, "style": "box_white"})
    video_cut.SESSIONS[s.id] = s
    jobs: list[str] = []
    try:
        video_cut.cut(s, [{"start": 0, "end": 5.0, "title": "Đầu"}, {"start": 5.0, "end": 10.0, "title": ""}])
        _wait(lambda: s.status != "cutting")
        assert s.status == "done", s.error
        parts = s.parts
        assert [p["index"] for p in parts] == [1, 2] and parts[1]["title"] == "Mẹo vặt nhà bếp — Phần 2/2"
        for p in parts:
            job = dub.JOBS[p["job_id"]]
            jobs.append(job.id)
            _wait(lambda: job.status in ("done", "error"))
            assert job.status == "done", job.error
            assert job.kind == "cut" and job.mode == "sub" and job.sub_lang == "none" and job.batch_id == s.run_id
            assert job.url is None and job.cut["index"] == p["index"]
            # the raw piece, and the part's video rendered in the look (square), the clip pointing at the latter
            info = probe_clip(Path(media_service.cached_path(p["media_id"])))
            assert abs(info.duration - 5.0) < 0.4 and info.has_audio
            assert job.layout["canvas"]["aspect"] == "1:1" and job.style == "box_white"
            assert job.media_id != p["media_id"] and job.outputs
            out = probe_clip(Path(media_service.cached_path(job.media_id)))
            assert out.width == out.height and out.has_audio and abs(out.duration - 5.0) < 0.4
            assert all(0 <= g.start < g.end <= 5.05 for g in job.segments) and job.segments
            with get_session() as db:
                b = db.get(Board, p["board_id"])
                qt = b.data["quicktool"]
                assert qt["template_id"] == "cut_part" and qt["cut"]["session_id"] == s.id and qt["dub"]["job_id"] == job.id
                nodes = {n.type: n for n in db.exec(dub.select(Node).where(Node.board_id == b.id)).all()}
                assert nodes["export"].data["mediaId"] == job.media_id
        assert [j.id for j in video_cut.part_jobs(run_id=s.run_id)] == jobs
        assert [p["edited"] for p in video_cut.public(s)["parts"]] == [True, True]
        # the dubbing list does not show the parts; the cut page's list does
        listed = [j["job_id"] for j in client.get("/api/dub/jobs?all=true&brief=true").json()]
        assert not set(jobs) & set(listed)
        assert [j["job_id"] for j in client.get(f"/api/cut/parts?run={s.run_id}").json()] == jobs

        # edit part 1: a 16:9 frame on a grid instead, no subtitles burned → a new video, the clip follows it
        first = dub.JOBS[jobs[0]]
        old_media = first.media_id
        r = client.post(f"/api/dub/jobs/{first.id}/render", json={
            "layout": {**first.layout, "canvas": {"aspect": "16:9", "fit": "grid"}}, "sub_lang": "none"})
        assert r.status_code == 200, r.text
        _wait(lambda: first.status in ("done", "error"))
        assert first.status == "done", first.error
        assert first.media_id != old_media and first.outputs
        info = probe_clip(Path(media_service.cached_path(first.media_id)))
        assert info.width > info.height and info.has_audio
        with get_session() as db:
            b = db.get(Board, first.board_id)
            assert b.data["quicktool"]["template_id"] == "cut_part"
            assert {n.type: n for n in db.exec(dub.select(Node).where(Node.board_id == b.id)).all()}["export"].data["mediaId"] == first.media_id
        # no subtitles burned when "none": the subtitle file is empty of dialogue
        assert "Dialogue" not in (first.work / "subs.ass").read_text(encoding="utf-8")

        # cut again: same projects and clips, new pieces rendered again in each part's own look (part 1 wide, part 2 square)
        boards = [p["board_id"] for p in parts]
        video_cut.cut(s, [{"start": 0, "end": 4.0, "title": "Đầu mới"}, {"start": 4.0, "end": 10.0, "title": "Sau"}])
        _wait(lambda: s.status != "cutting")
        assert s.status == "done", s.error
        assert [p["job_id"] for p in s.parts] == jobs and [p["board_id"] for p in s.parts] == boards
        for jid, wide in zip(jobs, (True, False)):
            j = dub.JOBS[jid]
            _wait(lambda: j.status in ("done", "error"))
            assert j.status == "done", j.error
            assert j.layout["canvas"]["aspect"] == ("16:9" if wide else "1:1") and j.outputs
            out = probe_clip(Path(media_service.cached_path(j.media_id)))
            assert (out.width > out.height) is wide and abs(out.duration - (4.0 if wide else 6.0)) < 0.4
        with get_session() as db:
            assert db.get(Board, boards[0]).name == "Đầu mới"
    finally:
        video_cut.SESSIONS.pop(s.id, None)
        for j in jobs:
            dub.JOBS.pop(j, None)


def test_a_saved_prompt_writes_the_titles_and_a_name_for_the_whole_video(monkeypatch):
    s = _session()
    s.how, s.prompt, s.title_lang = "prompt", video_cut.DEFAULT_PROMPT, "Tây Ban Nha"
    assert video_cut.clean_prompt(video_cut.DEFAULT_PROMPT) == video_cut.DEFAULT_PROMPT  # fits, lines kept
    seen = {}

    async def fake_llm(feature, prompt, **kw):
        seen["prompt"], seen["system"] = prompt, kw["system_prompt"]
        return ('{"name": "La  chica que nadie esperaba", "parts": [{"from": 2, "to": 5, "title": "Ella lo sabía todo"},'
                ' {"from": 7, "to": 10, "title": "El secreto del hombre"}], "note": ""}')

    monkeypatch.setattr(video_cut, "run_llm", fake_llm)
    res = asyncio.run(video_cut.suggest(s))
    assert res["name"] == "La chica que nadie esperaba"
    assert [r["title"] for r in res["rows"]] == ["Ella lo sabía todo", "El secreto del hombre"]
    assert "TITLE LANGUAGE: tiếng Tây Ban Nha" in seen["prompt"] and "70s < thời lượng < 150s" in seen["prompt"]
    assert "as the request below says" in seen["prompt"] and "END OF THE REQUEST" in seen["prompt"]
    assert "title_bottom_N" in seen["system"] and '"name"' in seen["system"]
    # the even split has no name
    s.how = "even"
    assert asyncio.run(video_cut.suggest(s))["name"] == ""


def test_cut_prompts_are_saved_with_the_account(client):
    first = client.get("/api/cut/prompts").json()
    assert len(first) == 1 and first[0]["id"] == "default" and "title_bottom_N" in first[0]["text"]  # the built-in one
    saved = client.put("/api/cut/prompts", json={"prompts": [
        {"id": "default", "name": "  Hook  TikTok ", "text": "Dòng 1\n\n\n\nDòng 2"},
        {"id": "default", "name": "", "text": "Chỉ giữ đoạn hài"}, {"name": "rỗng", "text": "   "}]}).json()
    assert [p["name"] for p in saved] == ["Hook TikTok", "Prompt 2"] and saved[0]["text"] == "Dòng 1\n\nDòng 2"
    assert saved[0]["id"] == "default" and saved[1]["id"] not in ("", "default")
    assert client.get("/api/cut/prompts").json() == saved
    assert client.put("/api/cut/prompts", json={"prompts": []}).json() == []
    assert client.get("/api/cut/prompts").json() == []  # deleting the built-in one sticks


def test_routes_check_what_they_get(client, monkeypatch):
    monkeypatch.setattr(video_cut, "_pump", lambda: None)
    r = client.post("/api/cut/sessions", json={"links": [], "media": []})
    assert r.status_code == 400 and "link" in r.json()["detail"]
    r = client.post("/api/cut/sessions", json={"links": ["https://youtu.be/abc"], "how": "prompt", "prompt": "  "})
    assert r.status_code == 400 and "yêu cầu" in r.json()["detail"]
    # a look preset that is gone is an error, not a silent raw cut
    r = client.post("/api/cut/sessions", json={"links": ["https://youtu.be/abc"], "look_preset_id": 9999})
    assert r.status_code == 404 and "mẫu" in r.json()["detail"].lower()
    look = client.post("/api/dub/decor/presets", json={"kind": "look", "name": "Dọc 9:16", "data": {
        "layout": {"canvas": {"aspect": "9:16", "fit": "grid"}}, "style": "box_yellow"}}).json()
    r = client.post("/api/cut/sessions", json={"links": ["xem nè https://youtu.be/abc nha", "https://youtu.be/def"],
                                              "how": "even", "min_s": 15, "max_s": 30, "look_preset_id": look["id"]})
    assert r.status_code == 201, r.text
    body = r.json()
    try:
        assert len(body["sessions"]) == 2 and {x["run_id"] for x in body["sessions"]} == {body["run_id"]}
        assert body["sessions"][0]["url"] == "https://youtu.be/abc" and body["sessions"][0]["status"] == "queued"
        assert all(x["look"]["layout"]["canvas"]["aspect"] == "9:16" for x in body["sessions"])
        assert client.get("/api/dub/decor/presets?kind=look").json()[0]["uses"] == 1
        listed = client.get("/api/cut/sessions").json()
        assert {x["id"] for x in body["sessions"]} <= {x["id"] for x in listed}
        sid = body["sessions"][0]["id"]
        assert client.post(f"/api/cut/sessions/{sid}/cut", json={"rows": [{"start": 0, "end": 10}]}).status_code == 400
        assert client.post(f"/api/cut/sessions/{sid}/stop").json()["status"] == "error"
        # a queued one is not deleted (stop it first)
        d = client.post("/api/cut/sessions/delete", json={"ids": [body["sessions"][1]["id"]]}).json()
        assert not d["deleted"] and "dừng" in d["skipped"][0]["reason"]
        client.post(f"/api/cut/sessions/{body['sessions'][1]['id']}/stop")
        d = client.post("/api/cut/sessions/delete", json={"ids": [x["id"] for x in body["sessions"]]}).json()
        assert sorted(d["deleted"]) == sorted(x["id"] for x in body["sessions"])
    finally:
        for x in body["sessions"]:
            video_cut.SESSIONS.pop(x["id"], None)
        client.delete(f"/api/dub/decor/presets/{look['id']}")


def test_the_cut_feature_unlocks_the_editor_routes_it_needs():
    from flowboard import plans

    assert plans.feature_for("POST", "/api/dub/jobs/0a1b2c3d4e5f/render") == ("dub", "cut")
    assert plans.feature_for("GET", "/api/dub/jobs/0a1b2c3d4e5f/filmstrip.jpg") == ("dub", "cut")
    assert plans.feature_for("POST", "/api/dub/background") == ("dub", "cut")
    assert plans.feature_for("POST", "/api/dub/jobs") == ("dub",)
    assert plans.feature_for("GET", "/api/cut/sessions") == ("cut",)
    assert "cut" in plans.FEATURE_KEYS


def test_the_assistant_cuts_videos():
    from flowboard.services import assistant

    out = assistant.parse_answer('{"reply": "ok", "actions": [{"tool": "cut_video", "args": {"urls": ["https://youtu.be/x"], '
                                 '"prompt": "mỗi đoạn một mẹo", "max_parts": 99}}]}')
    a = out["actions"][0]
    assert a["tool"] == "cut_video" and a["args"]["how"] == "prompt" and a["args"]["max_parts"] == 30
    assert a["args"]["min_s"] == 30 and a["args"]["max_s"] == 60
    q = assistant.parse_answer('{"reply": "ok", "actions": [{"tool": "cut_video", "args": {"urls": []}}]}')
    assert not q["actions"] and "link" in q["reply"]
    assert "Cắt" in assistant._plan_summary(out["actions"], {"channels": [], "products": []})[0]
