"""An Edge call that never answers (dropped connection) must not hang the dub job: each attempt has a
deadline and a timed-out attempt is retried like a refused one (29/10: a 332-line job sat at 71 % for good)."""
from __future__ import annotations

import asyncio

import pytest

from flowboard.services import tts


class _Stream:
    calls = 0

    def __init__(self, text, voice, **_kw):
        self.text = text

    async def stream(self):
        type(self).calls += 1
        if type(self).calls == 1:
            await asyncio.Event().wait()  # the hung attempt: never answers
        yield {"type": "audio", "data": b"ID3fake-mp3"}
        yield {"type": "WordBoundary", "offset": 0, "duration": 5_000_000, "text": "xin"}


def test_a_hung_edge_attempt_times_out_and_the_next_try_reads_the_line(monkeypatch, tmp_path):
    import edge_tts

    _Stream.calls = 0
    monkeypatch.setattr(tts, "TTS_DIR", tmp_path)
    monkeypatch.setattr(edge_tts, "Communicate", _Stream)
    monkeypatch.setattr(tts, "edge_attempt_timeout", lambda text: 0.2)
    monkeypatch.setattr(tts, "_probe_duration", lambda p: 0.5)

    async def no_wait(_s):
        return None

    monkeypatch.setattr(tts.asyncio, "sleep", no_wait)
    narr = asyncio.run(asyncio.wait_for(tts.synthesize("Xin chào", tts.DEFAULT_VOICE, 0), 10))
    assert _Stream.calls == 2 and narr.duration == 0.5 and narr.path.read_bytes() == b"ID3fake-mp3"


def test_the_deadline_grows_with_the_line_but_stays_bounded():
    assert tts.edge_attempt_timeout("ngắn") == pytest.approx(20.2)
    assert 20 < tts.edge_attempt_timeout("x" * 300) < 60
    assert tts.edge_attempt_timeout("x" * 5000) == 60
