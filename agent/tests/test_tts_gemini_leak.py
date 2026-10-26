"""Gemini TTS sometimes reads the prompt's instructions aloud: the clip comes
back far too long for its words, and is re-spoken (last try: the bare line)."""
import asyncio
import json

import pytest

from flowboard.services import tts


def test_leak_is_judged_by_length_for_the_words():
    assert not tts.gemini_leaked("Không làm được động tác mạnh", 1.5)
    assert tts.gemini_leaked("Không làm được động tác mạnh", 11.8)  # the 26/10 case
    long_line = "Lúc này giãn cả nhóm cơ lưng, giữ lưng thẳng và hít thở thật đều nhé các mẹ"
    assert not tts.gemini_leaked(long_line, 5.5) and tts.gemini_leaked(long_line, 17.4)


@pytest.fixture
def gemini_env(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "TTS_DIR", tmp_path)
    voice = next(v for v in tts.VOICES if tts.is_gemini_voice(v))
    durations: list[float] = []
    calls: list[bool] = []

    async def fake_synth(text, v, rate, style, out, plain=False):
        calls.append(plain)
        out.write_bytes(b"RIFF")

    monkeypatch.setattr(tts, "_synth_gemini", fake_synth)
    monkeypatch.setattr(tts, "_probe_duration", lambda p: durations.pop(0))
    return voice, durations, calls, tmp_path


def test_a_leaked_take_is_respoken_and_the_last_try_is_the_bare_line(gemini_env):
    voice, durations, calls, _ = gemini_env
    durations += [11.8, 12.0, 1.6]
    out = asyncio.run(tts.synthesize("Không làm được động tác mạnh", voice))
    assert out.duration == 1.6 and calls == [False, False, True]


def test_a_good_first_take_is_kept(gemini_env):
    voice, durations, calls, _ = gemini_env
    durations += [1.4]
    assert asyncio.run(tts.synthesize("Giữ ba giây", voice)).duration == 1.4 and calls == [False]


def test_three_leaked_takes_fail_clearly(gemini_env):
    voice, durations, calls, _ = gemini_env
    durations += [11.0, 11.0, 11.0]
    with pytest.raises(tts.TTSError, match="đọc thừa"):
        asyncio.run(tts.synthesize("Giữ ba giây", voice))


def test_a_leaked_line_already_in_the_cache_is_respoken(gemini_env):
    voice, durations, calls, tmp = gemini_env
    text = "Thả lỏng tay ở hai bên người"
    key = tts._cache_key(text, voice, 0, "")
    (tmp / f"{key}.wav").write_bytes(b"RIFF")
    (tmp / f"{key}.json").write_text(json.dumps({"duration": 15.8, "words": []}), encoding="utf-8")
    durations += [2.1]
    out = asyncio.run(tts.synthesize(text, voice))
    assert out.duration == 2.1 and calls == [False]
    assert json.loads((tmp / f"{key}.json").read_text(encoding="utf-8"))["duration"] == 2.1
