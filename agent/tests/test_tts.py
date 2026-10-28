"""Voice-over helpers: subtitle cue timing and the ASS file. edge-tts itself
is not called."""
from pathlib import Path

from flowboard.services import tts


def _narration(words, duration):
    return tts.Narration(Path("x.mp3"), duration, [tts.Word(s, e, t) for s, e, t in words])


def test_cues_follow_word_timings_and_wrap_lines():
    text = "Áo thun cotton dày dặn mặc rất mát mẻ và thoải mái cả ngày dài"
    tokens = text.split()
    words = [(i * 0.4, i * 0.4 + 0.35, t) for i, t in enumerate(tokens)]
    cues = tts.subtitle_cues(_narration(words, 6.0), text, max_chars=20)
    assert all(len(line) <= 20 for _, _, line in cues)
    assert " ".join(line for _, _, line in cues) == text
    assert cues[0][0] == 0.0 and cues[0][1] >= 0.3
    for (s1, e1, _), (s2, _, _) in zip(cues, cues[1:]):
        assert s2 >= e1  # cues never overlap
    assert cues[-1][1] == 6.0  # the last cue hangs until the audio ends


def test_cues_spread_evenly_without_word_timings():
    text = "một hai ba bốn năm sáu"
    cues = tts.subtitle_cues(_narration([], 3.0), text, max_chars=11)
    assert [c[2] for c in cues] == ["một hai ba", "bốn năm sáu"]
    assert cues[0][0] == 0.0 and abs(cues[0][1] - 1.5) < 0.2 and cues[1][1] == 3.0


def test_write_ass_scales_to_the_frame(tmp_path):
    out = tts.write_ass([(0.0, 1.5, "Xin chào"), (1.5, 3.0, "mọi người")], tmp_path / "s.ass",
                        width=720, height=1280)
    text = out.read_text(encoding="utf-8")
    assert "PlayResX: 720" in text and "PlayResY: 1280" in text
    assert "Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,Xin chào" in text
    assert "Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,mọi người" in text


def test_filter_path_escapes_windows_drive():
    from flowboard.services.video_export import _filter_path
    assert _filter_path(Path(r"D:\a b\s.ass")) == "'D\:/a b/s.ass'"


def test_gemini_voice_uses_the_key_pool_and_caches(tmp_path, monkeypatch):
    import asyncio
    import wave
    from flowboard.services.llm import gemini_api

    monkeypatch.setattr(tts, "TTS_DIR", tmp_path)
    calls = []

    async def fake_speak(prompt, voice, *, model=None, timeout=None):
        calls.append((prompt, voice))
        import io
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(24000); wf.writeframes(b"\x00\x00" * 24000)
        return buf.getvalue()

    monkeypatch.setattr(gemini_api, "speak", fake_speak)
    n = asyncio.run(tts.synthesize("Xin chào mọi người", "gemini:Kore", 20, "giọng kể chuyện kịch tính"))
    assert n.path.suffix == ".wav" and n.words == [] and 0.9 <= n.duration <= 1.1
    # Style + rate go in a separate notes block; only the transcript is spoken
    # ("<style>: <text>" made Gemini read the style aloud, 2026-10-22).
    assert len(calls) == 1 and calls[0][1] == "Kore"
    prompt = calls[0][0]
    assert "giọng kể chuyện kịch tính, nói nhanh hơn bình thường" in prompt.split("### TRANSCRIPT")[0]
    assert prompt.split("### TRANSCRIPT")[1].strip() == "Xin chào mọi người"
    assert "never say them" in prompt
    # cached: the same line does not hit the service again
    asyncio.run(tts.synthesize("Xin chào mọi người", "gemini:Kore", 20, "giọng kể chuyện kịch tính"))
    assert len(calls) == 1
    # the subtitle cues still spread over the audio without word timings
    cues = tts.subtitle_cues(n, "Xin chào mọi người")
    assert cues and cues[-1][1] == n.duration


def test_voice_groups_lists_every_family_with_availability():
    groups = {g["id"]: g for g in tts.voice_groups()}
    assert list(groups) == ["edge", "vieneu", "gemini", "fpt"]
    assert len(groups["edge"]["voices"]) == 2 and len(groups["gemini"]["voices"]) >= 10
    assert all(tts.is_gemini_voice(v["id"]) for v in groups["gemini"]["voices"])
    assert len(groups["vieneu"]["voices"]) == 25 and all(tts.voice_kind(v["id"]) == "vieneu" for v in groups["vieneu"]["voices"])
    assert len(groups["fpt"]["voices"]) == 7 and groups["fpt"]["available"] is False and "key" in groups["fpt"]["reason"]
    for g in groups.values():
        assert "available" in g
    assert tts.voice_kind("vi-VN-HoaiMyNeural") == "edge" and tts.voice_kind("gemini:Kore") == "gemini"
