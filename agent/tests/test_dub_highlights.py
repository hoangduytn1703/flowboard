"""✨ Nhấn chữ quan trọng in the dubbing tool: the key moments (shared with Edit auto CapCut), the burned-in
key word, the push-in zoom, the sound effects, and the editor's pick route."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from flowboard.services import dub, key_moments, sfx


def test_highlights_are_normalized_and_off_by_default():
    assert dub.normalize_highlights(None) == {"on": False, "words": True, "zoom": True, "sfx": True, "sfx_set": "builtin",
                                              "y": None, "points": [], "picked": ""}
    hl = dub.normalize_highlights({"on": 1, "sfx": False, "sfx_set": "capcut", "y": 5,
                                   "points": [{"at": "3.2", "words": "  giá  99k ", "line": 1}, {"at": 1, "words": ""}, "x",
                                              {"at": 0.5, "words": "sớm"}]})
    assert hl["on"] and not hl["sfx"] and hl["words"] and hl["sfx_set"] == "capcut" and hl["y"] == dub.HL_Y_MAX
    assert hl["points"] == [{"at": 0.5, "words": "sớm", "line": None}, {"at": 3.2, "words": "giá 99k", "line": 1}]


def test_zoom_curve_rises_holds_and_falls_the_same_in_ffmpeg_and_python():
    pts = [{"at": 2.0}, {"at": 10.0}]
    assert key_moments.zoom_at(pts, 1.9) == 1.0
    assert key_moments.zoom_at(pts, 2.15) == pytest.approx(1.06)
    assert key_moments.zoom_at(pts, 2.8) == pytest.approx(1.12)
    assert key_moments.zoom_at(pts, 3.5) == pytest.approx(1.06)
    assert key_moments.zoom_at(pts, 3.8) == 1.0
    assert key_moments.zoom_at(pts, 11.0) == pytest.approx(1.18)  # the second point takes the other level
    expr = key_moments.zoom_expr(pts)
    assert expr.startswith("1+0.120*min(clip((in_time-2.000)/0.3,0,1)") and "0.180*" in expr
    hl = {"on": True, "zoom": True, "points": pts}
    assert dub.zoom_filter(hl, 720, 1280, "30000/1001").startswith("zoompan=z='1+") and ":s=720x1280:fps=30000/1001" in dub.zoom_filter(hl, 720, 1280, "30000/1001")
    assert dub.zoom_filter({**hl, "zoom": False}, 720, 1280, "30") == "" and dub.zoom_filter({**hl, "points": []}, 720, 1280, "30") == ""


def test_the_key_word_goes_above_the_subtitles_and_into_the_ass(tmp_path):
    hl = dub.normalize_highlights({"on": True, "points": [{"at": 1.0, "words": "giá 99k"}, {"at": 4.0, "words": "miễn phí"}]})
    layout = {"x": 0.5, "y": 0.8, "scale": 1.0}
    assert dub.emphasis_y(layout, hl) == pytest.approx(0.6)
    assert dub.emphasis_y(layout, {**hl, "y": 0.3}) == 0.3
    ev = dub.emphasis_events(hl, layout, 4.5)
    assert ev == [(1.0, 2.2, "GIÁ 99K", 0.5, 0.6), (4.0, 4.5, "MIỄN PHÍ", 0.5, 0.6)]
    assert dub.emphasis_events({**hl, "words": False}, layout, 10) == []
    ass = dub.write_sub_ass([(0.0, 1.5, "Câu một")], tmp_path / "s.ass", width=720, height=1280, layout=layout, emphasis=ev)
    text = ass.read_text(encoding="utf-8")
    assert "Style: Emph,Arial," in text and text.count("Dialogue: 1,") == 2
    assert "\\an5\\pos(360,730)\\fscx70\\fscy70\\t(0,120,\\fscx100\\fscy100)}GIÁ 99K" in text


def test_audio_mix_adds_music_and_sound_effects_to_the_voice():
    assert dub.audio_mix(False, None) == ("", "1:a:0")
    g, m = dub.audio_mix(True, None)
    assert "amix=inputs=2" in g and m == "[a]"
    g, m = dub.audio_mix(True, 3)
    assert f"[3:a]volume={key_moments.SFX_VOLUME}[fx]" in g and "[1:a][b][fx]amix=inputs=3" in g
    g, _ = dub.audio_mix(False, 2)
    assert "[1:a][fx]amix=inputs=2" in g


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_builtin_sounds_exist_and_take_turns(tmp_path, monkeypatch):
    from flowboard import config

    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    snd = sfx.builtin_sounds()
    assert [s["label"] for s in snd] == ["pop", "whoosh", "ding", "click"] and all(s["path"].is_file() for s in snd)
    pts = [{"at": float(i * 6)} for i in range(6)]
    pieces = sfx.pieces(pts, "builtin")
    names = [p.stem for _a, p, _d in pieces]
    assert len(pieces) == 6 and all(a != b for a, b in zip(names, names[1:])) and len(set(names)) == 4
    assert sfx.sets()[0]["key"] == "builtin" and sfx.sets()[0]["count"] == 4


def test_pick_falls_back_to_numbers_when_the_ai_fails(monkeypatch):
    async def boom(lines, total):
        raise ValueError("no json")

    monkeypatch.setattr(key_moments, "pick_points", boom)
    job = dub.Job(id="h1", url=None, source_media_id=None)
    job.segments = [dub.Segment(0, 3, "a", "Giá chỉ 99k thôi"), dub.Segment(3, 6, "b", "Mua ngay!")]
    job.duration_s = 6.0
    pts, how = dub.pick_highlights(job)
    assert how == "fallback" and pts and pts[0]["words"] == "99k thôi" and pts[0]["line"] == 0
    hl = dub._ensure_points(type("J", (), {"highlights": {"on": True}, "segments": job.segments, "duration_s": 6.0,
                                               "stop": False, "phase": "", "progress": 0})())
    assert hl["points"] and hl["picked"] == "fallback"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_render_burns_the_key_word_zooms_and_adds_the_sounds(client, tmp_path, monkeypatch):
    """The ffmpeg path with highlights on: the ASS has the Emph events, the command zooms, a sfx track is mixed in."""
    from flowboard import config
    from flowboard.services import media as media_service

    ffmpeg = shutil.which("ffmpeg")
    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    src = tmp_path / "src.mp4"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x284:rate=10:duration=4",
                    "-f", "lavfi", "-i", "sine=frequency=200:duration=4", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(src)], check=True)
    piece = tmp_path / "piece.wav"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=0.5", "-ar", "48000", "-ac", "1", str(piece)], check=True)
    monkeypatch.setattr(dub, "_voice_pieces", lambda job: [(0.0, piece, 0.5), (2.0, piece, 0.5)])
    monkeypatch.setattr(dub, "status", lambda: {"separate": False, "available": True})
    ran: list[list[str]] = []
    real_run = dub._run

    def spy(cmd, timeout):
        ran.append(list(cmd))
        return real_run(cmd, timeout)

    monkeypatch.setattr(dub, "_run", spy)
    monkeypatch.setattr(dub, "_run_encode", lambda cmd, timeout, *a, **k: dub._run(cmd, timeout))
    job = dub.Job(id="c0ffee000001", url=None, source_media_id="src")
    job.segments = [dub.Segment(0, 1.5, "a", "Giá chỉ 99k thôi"), dub.Segment(2, 3.5, "b", "Mua ngay nha")]
    job.duration_s = 4.0
    job.highlights = {"on": True, "points": [{"at": 0.4, "words": "99k", "line": 0}, {"at": 2.2, "words": "Mua ngay", "line": 1}]}
    job.work = tmp_path / "dub" / job.id
    job.work.mkdir(parents=True)
    job.src_path = src
    dub._render(job)
    assert job.status == "done", job.error
    assert (job.work / "sfx.wav").is_file()
    ass = (job.work / "subs.ass").read_text(encoding="utf-8")
    assert "}99K" in ass and "}MUA NGAY" in ass
    final = [c for c in ran if any(str(a).endswith(f"{job.media_id}.mp4") for a in c)][-1]
    graph = final[final.index("-filter_complex") + 1]
    assert "zoompan=z='1+" in graph and "amix=inputs=2" in graph and "[fx]" in graph
    out = media_service.MEDIA_CACHE_DIR / f"{job.media_id}.mp4"
    assert out.is_file() and dub.read_tag(out) == job.id
    # off again: a layout-only re-render reuses the voice and has no zoom / sfx
    job.highlights = {"on": False}
    job.voice_key = dub.voice_key(job)
    ran.clear()
    dub._render(job)
    graph = [c for c in ran if any(str(a).endswith(f"{job.media_id}.mp4") for a in c)][-1]
    graph = graph[graph.index("-filter_complex") + 1]
    assert "zoompan" not in graph and "[fx]" not in graph


def test_the_pick_route_uses_the_editors_lines(client, tmp_path, monkeypatch):
    seen = {}

    def fake_pick(job):
        seen["lines"] = [s.text for s in job.segments]
        seen["starts"] = [s.start for s in job.segments]
        return [{"at": 0.5, "words": "99k", "line": 0}], "ai"

    monkeypatch.setattr(dub, "pick_highlights", fake_pick)
    job = dub.Job(id="r0ad00000001", url=None, source_media_id=None)
    job.segments = [dub.Segment(0, 1.5, "a", "cũ"), dub.Segment(2, 3.5, "b", "cũ 2")]
    job.work = tmp_path
    dub.JOBS[job.id] = job
    try:
        r = client.post(f"/api/dub/jobs/{job.id}/highlights/pick", json={"lines": ["Giá chỉ 99k", "Mua ngay"], "timings": [[0.2, 1.7], [2, 3.5]]})
        assert r.status_code == 200, r.text
        assert r.json() == {"points": [{"at": 0.5, "words": "99k", "line": 0}], "picked": "ai"}
        assert seen["lines"] == ["Giá chỉ 99k", "Mua ngay"] and seen["starts"][0] == 0.2
        assert job.segments[0].text == "cũ"  # the job itself is untouched until "Xuất"
        r = client.post(f"/api/dub/jobs/{job.id}/render", json={"highlights": {"on": True, "points": [{"at": 0.5, "words": "99k"}]}})
        assert r.status_code == 400  # no source file: refused, but the body is accepted
    finally:
        dub.JOBS.pop(job.id, None)
