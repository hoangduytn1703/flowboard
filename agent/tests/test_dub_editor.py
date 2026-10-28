"""Timeline editor for dubbed videos: line timings, the voice key, film strip and waveform."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from flowboard.services import dub


def _job(tmp_path: Path, n: int = 3) -> dub.Job:
    job = dub.Job(id="j1", url=None, source_media_id=None)
    job.segments = [dub.Segment(i * 2.0, i * 2.0 + 1.5, f"src {i}", f"câu {i}") for i in range(n)]
    job.duration_s = n * 2.0
    job.work = tmp_path
    return job


def test_timings_stay_in_order_inside_the_video_and_long_enough(tmp_path):
    job = _job(tmp_path)
    dub.apply_timings(job, [[0.5, 1.0], [0.8, 0.9], [5.9, 9.0]])
    s = [(seg.start, seg.end) for seg in job.segments]
    assert s[0] == (0.5, 1.0)
    # line 2 may not start before line 1 ends, and is stretched to the minimum slot
    assert s[1][0] == 1.0 and s[1][1] == pytest.approx(1.0 + dub.MIN_SLOT_S)
    # line 3 is pulled back inside the 6 s video
    assert s[2][1] == 6.0 and s[2][1] - s[2][0] >= dub.MIN_SLOT_S - 1e-9
    with pytest.raises(dub.DubError):
        dub.apply_timings(job, [[0, 1]])


def test_moving_a_line_invalidates_the_voice_but_old_keys_still_count(tmp_path):
    job = _job(tmp_path)
    job.voice_key = dub._legacy_voice_key(job)  # saved before slots were in the key
    dub._upgrade_voice_key(job)
    assert job.voice_key == dub.voice_key(job)
    before = dub.voice_key(job)
    dub.apply_timings(job, [[0.0, 1.5], [2.4, 3.9], [4.0, 5.5]])
    assert dub.voice_key(job) != before


def test_render_job_takes_timings(tmp_path, monkeypatch):
    job = _job(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    job.src_path = src
    job.status = "done"
    monkeypatch.setattr(dub, "_pump", lambda: None)
    monkeypatch.setattr(dub, "persist", lambda j: None)
    dub.render_job(job, lines=None, voice=None, style=None, keep_bgm=None, name=None,
                   timings=[[0.2, 1.2], [2.0, 3.0], [4.0, 5.0]])
    assert job.segments[0].start == 0.2 and job.status == "queued"


def _ffmpeg() -> str:
    f = shutil.which("ffmpeg")
    if f is None:
        pytest.skip("ffmpeg missing")
    return f


def test_filmstrip_and_waveform_are_drawn_once(tmp_path):
    ffmpeg = _ffmpeg()
    job = _job(tmp_path)
    src = tmp_path / "src.mp4"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x568:rate=25:duration=6",
                    "-c:v", "libx264", "-g", "25", "-pix_fmt", "yuv420p", str(src)], check=True)
    job.src_path = src
    strip = dub.filmstrip(job)
    assert strip.is_file() and strip.stat().st_size > 1000
    mtime = strip.stat().st_mtime_ns
    assert dub.filmstrip(job).stat().st_mtime_ns == mtime  # cached

    with pytest.raises(dub.DubError):
        dub.waveform(job)  # no voice yet
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=6",
                    "-ac", "1", "-ar", "48000", str(tmp_path / "voice.wav")], check=True)
    wave = dub.waveform(job)
    assert wave.is_file() and wave.stat().st_size > 200
    assert job.public()["voice_url"] == "/api/dub/jobs/j1/voice"


def test_box_width_sets_how_much_text_fits_one_line():
    narrow = dub.sub_max_chars(720, 1280, {"w": 0.3})
    wide = dub.sub_max_chars(720, 1280, {"w": 0.95})
    assert narrow < dub.sub_max_chars(720, 1280) <= wide
    # same width, bigger letters → fewer characters (font size stays its own setting)
    assert dub.sub_max_chars(720, 1280, {"w": 0.95, "scale": 1.6}) < wide
    assert dub.normalize_layout({"w": 5})["w"] == dub.W_MAX
    assert dub.normalize_layout({})["w"] is None


def test_a_line_can_have_its_own_place_and_size(tmp_path):
    assert dub.normalize_look({"y": 0.3, "junk": 1}) == {"y": 0.3}
    assert dub.normalize_look({}) is None and dub.normalize_look("x") is None
    ass = dub.write_sub_ass([(0, 1, "chung"), (1, 2, "riêng", {"y": 0.3, "scale": 1.5})], tmp_path / "s.ass",
                            width=720, height=1280, style="box_yellow", layout={"y": 0.8})
    lines = [l for l in ass.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue")]
    assert r"\pos(360,1024)" in lines[0] and r"\fs" not in lines[0]
    assert r"\pos(360,384)" in lines[1] and r"\fs69" in lines[1]


def test_render_job_takes_looks_and_remotion_gets_them(tmp_path, monkeypatch):
    from flowboard.services import dub_remotion

    job = _job(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    job.src_path, job.status = src, "done"
    monkeypatch.setattr(dub, "_pump", lambda: None)
    monkeypatch.setattr(dub, "persist", lambda j: None)
    key = dub.voice_key(job)
    dub.render_job(job, lines=None, voice=None, style=None, keep_bgm=None, name=None,
                   looks=[None, {"y": 0.4, "w": 0.9}, {}])
    assert job.segments[1].look == {"y": 0.4, "w": 0.9} and job.segments[2].look is None
    assert dub.voice_key(job) == key  # placement only: the voice is kept
    assert job.segments[1].public()["look"] == {"y": 0.4, "w": 0.9}
    spec = dub_remotion.build_spec(src=src, out=tmp_path / "o.mp4", cues=[(0, 1, "a"), (1, 2, "b", {"y": 0.4})],
                                   layout={"x": 0.5, "y": 0.8, "scale": 1, "w": 0.7}, style="rm_box", width=720, height=1280, duration_s=2)
    assert spec["props"]["cues"][1]["look"] == {"y": 0.4} and "look" not in spec["props"]["cues"][0]
    assert spec["props"]["layout"]["w"] == 0.7


def test_a_line_edge_keeps_refusing_gets_another_round(tmp_path, monkeypatch):
    from flowboard.services import tts

    ffmpeg = _ffmpeg()
    wav = tmp_path / "line.wav"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=0.5", str(wav)], check=True)
    asked: dict[str, int] = {}

    async def flaky(text, voice, rate=0, style=None):
        asked[text] = asked.get(text, 0) + 1
        # line 2 is refused by the parallel first pass AND by its first round, then read in round 2
        if text == "câu 1" and asked[text] <= 2:
            raise tts.TTSError("edge-tts failed: No audio was received")
        return tts.Narration(wav, 0.5, [])

    monkeypatch.setattr(tts, "synthesize", flaky)
    monkeypatch.setattr(dub, "VOICE_ROUND_WAIT_S", 0)
    job = _job(tmp_path)
    job.voice = "vi-VN-NamMinhNeural"
    pieces = dub._voice_pieces(job)
    assert len(pieces) == 3 and [p[0] for p in pieces] == [0.0, 2.0, 4.0]  # in order, though fitted in parallel
    assert asked["câu 1"] == 3 and asked["câu 0"] == 2  # parallel pass + the loop (a real voice is a cache hit then)
    # a voice that is not Edge has no extra rounds (its own retries already ran) and no parallel pass
    asked.clear()
    job.voice = next(v for v in tts.VOICES if tts.voice_kind(v) == "gemini")
    with pytest.raises(dub.DubError) as err:
        dub._voice_pieces(job)
    assert "câu 2/3" in str(err.value) and asked["câu 1"] == 1


def test_music_is_separated_while_the_voice_is_read(client, tmp_path, monkeypatch):
    import threading

    from flowboard.services import media as media_service

    ffmpeg = _ffmpeg()
    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    src = tmp_path / "src.mp4"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x284:rate=10:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=200:duration=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(src)], check=True)
    voice_wav = tmp_path / "piece.wav"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=0.5", "-ar", "48000", "-ac", "1",
                    str(voice_wav)], check=True)
    music_started = threading.Event()
    voice_done = threading.Event()

    def fake_separate(job, ff, s, bgm, progress):
        music_started.set()
        assert voice_done.wait(10), "separation should overlap the voice step"
        subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=100:duration=2", "-ar", "44100", str(bgm)], check=True)

    def fake_voice(job):
        assert music_started.wait(10), "the music should already be separating"
        voice_done.set()
        return [(0.0, voice_wav, 0.5)]

    monkeypatch.setattr(dub, "_separate_bgm", fake_separate)
    monkeypatch.setattr(dub, "_voice_pieces", fake_voice)
    monkeypatch.setattr(dub, "status", lambda: {"separate": True, "available": True})
    job = dub.Job(id="b9a0aa000001", url=None, source_media_id="src", keep_bgm=True)
    job.segments = [dub.Segment(0, 1, "a", "Một")]
    job.work = tmp_path / "dub" / job.id
    job.work.mkdir(parents=True)
    job.src_path = src
    dub._render(job)
    assert job.status == "done" and (job.work / "bgm.wav").is_file() and dub.read_tag(media_service.MEDIA_CACHE_DIR / f"{job.media_id}.mp4") == job.id


def test_subtitles_follow_the_voice_when_a_long_line_pushes_the_next_ones():
    job = dub.Job(id="f0110e000001", url=None, source_media_id=None)
    job.segments = [dub.Segment(0.0, 1.0, "a", "Một câu dài"), dub.Segment(1.0, 1.5, "b", ""),  # line 2 taken out
                    dub.Segment(1.5, 3.0, "c", "Câu ba"), dub.Segment(5.0, 6.0, "d", "Câu bốn")]
    # the voice really landed: line 1 ran 2.2 s, so line 3 was pushed to 2.2 s; line 4 kept its mark
    dub.follow_voice(job, [(0.0, 2.2), (2.2, 1.0), (5.0, 0.8)], total_s=7.0)
    s = job.segments
    assert (s[0].start, s[0].end) == (0.0, 2.2)          # until the next line starts (no tail into it)
    assert (s[2].start, s[2].end) == (2.2, 3.45)         # moved with its voice, + the short tail
    assert (s[3].start, s[3].end) == (5.0, 6.05)
    assert s[1].start >= s[0].end                        # the removed line slides after the line before it


def test_each_line_gets_a_word_budget_from_its_window():
    segs = [dub.Segment(0.0, 2.0, "a"), dub.Segment(3.0, 4.0, "b")]
    assert dub.line_window(segs, 0) == 3.0                # its slot + the pause before line 2
    assert dub.line_window(segs, 1, total_s=6.0) == 3.0   # the last line runs to the end of the video
    assert dub.word_budget(segs, 0) == int(3.0 * dub.WORDS_PER_SECOND)
    assert dub.word_budget([dub.Segment(0.0, 0.1, "x")], 0) == 2  # never below 2 words


def test_voice_pieces_lose_the_silence_edge_pads_them_with(tmp_path, monkeypatch):
    from flowboard.services import tts

    ffmpeg = _ffmpeg()
    padded = tmp_path / "padded.wav"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=0.3",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=1", "-filter_complex", "[0][1][0]concat=n=3:v=0:a=1",
                    str(padded)], check=True)

    async def edge(text, voice, rate=0, style=None):
        return tts.Narration(padded, 1.6, [])

    monkeypatch.setattr(tts, "synthesize", edge)
    job = _job(tmp_path)  # slots of 1.5 s, 2 s apart: the trimmed 1 s line fits without speeding up
    job.voice = next(v for v in tts.VOICES if tts.voice_kind(v) == "gemini")
    pieces = dub._voice_pieces(job)
    assert all(0.95 < d < 1.05 for _, _, d in pieces), pieces
