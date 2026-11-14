"""🧬 Giọng nhân bản: a recording → a saved voice that every voice picker and the readers take (fake runner)."""
from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from flowboard.services import dub, dub_runner, tts, voice_clone

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _silence_wav(path: Path, seconds: float = 1.0) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\0\0" * int(24000 * seconds))


@pytest.fixture
def recording(tmp_path) -> Path:
    out = tmp_path / "giong cua toi.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=6", "-c:a", "aac", str(out)],
                   check=True)
    return out


@pytest.fixture
def runner(monkeypatch):
    calls: list[tuple] = []

    def fake(*args, **kwargs):
        calls.append(args)
        if args[0] == "vieneu-enroll":
            ref, out_json = Path(args[1]), Path(args[2])
            assert ref.is_file() and ref.stat().st_size > 4000  # the recording, made into WAV
            out_json.write_text(json.dumps({"speaker_emb": [0.1] * 192, "codes": [[1, 2], [3, 4]]}), encoding="utf-8")
            if len(args) > 3:
                _silence_wav(Path(args[3]), 2.0)
            return {"ok": True, "speech_s": 5.8}
        if args[0] == "vieneu":
            for item in json.loads(Path(args[2]).read_text(encoding="utf-8")):
                _silence_wav(Path(item["out"]), 1.0)
            return {"ok": True, "done": 1, "missing": []}
        raise AssertionError(args)

    monkeypatch.setattr(dub, "_runner", fake)
    monkeypatch.setattr(tts, "vieneu_available", lambda: (True, ""))
    return calls


def _create(client, recording, **form):
    with open(recording, "rb") as fh:
        return client.post("/api/voices/clones", files={"file": ("giong.m4a", fh, "audio/mp4")},
                           data={"name": "Giọng của mình", "gender": "male", "consent": "true", **form})


def test_a_recording_becomes_a_voice_every_picker_and_reader_takes(client, recording, runner):
    assert client.get("/api/voices/clones").json() == []
    assert not any(g["id"] == "clone" for g in client.get("/api/llm/voices").json()["groups"])
    # no consent / no name → refused before any work
    assert _create(client, recording, consent="false").status_code == 400
    assert _create(client, recording, name="  ").status_code == 400
    assert runner == []

    r = _create(client, recording)
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["voice"] == f"vieneu:clone:{v['uid']}" and v["label"] == "Giọng của mình (nam)" and v["speech_s"] == 5.8
    assert [c[0] for c in runner] == ["vieneu-enroll"] and runner[0][4] == tts.PREVIEW_TEXT
    # in the pickers (first group), a voice everywhere
    groups = client.get("/api/llm/voices").json()["groups"]
    assert groups[0]["id"] == "clone" and groups[0]["voices"] == [{"id": v["voice"], "label": "Giọng của mình (nam)"}]
    assert tts.is_voice(v["voice"]) and tts.voice_kind(v["voice"]) == "vieneu"
    assert not tts.is_voice("vieneu:clone:000000000000") and not tts.is_voice("vieneu:clone:../../x")
    # "Nghe thử": the sample was read while learning — no second runner call
    p = client.post("/api/llm/voices/preview", json={"voice": v["voice"]})
    assert p.status_code == 200, p.text
    assert len(runner) == 1
    # reading a line: the runner gets the saved embedding as a file
    narration = _run(tts.synthesize("Câu thử giọng nhân bản.", v["voice"]))
    assert narration.path.is_file() and runner[-1][0] == "vieneu" and runner[-1][1].startswith("@")
    saved = json.loads(Path(runner[-1][1][1:]).read_text(encoding="utf-8"))
    assert saved["codes"] == [[1, 2], [3, 4]] and len(saved["speaker_emb"]) == 192

    # rename, delete → gone from every check
    assert client.patch(f"/api/voices/clones/{v['uid']}", json={"name": "Giọng review", "gender": "female"}).json()["label"] \
        == "Giọng review (nữ)"
    assert client.delete(f"/api/voices/clones/{v['uid']}").json() == {"ok": True}
    assert client.delete(f"/api/voices/clones/{v['uid']}").status_code == 404
    assert not tts.is_voice(v["voice"])
    assert client.post("/api/llm/voices/preview", json={"voice": v["voice"]}).status_code == 400
    with pytest.raises(tts.TTSError):
        _run(tts.synthesize("Câu khác.", v["voice"]))


def test_a_machine_without_vieneu_says_so(client, recording, monkeypatch):
    monkeypatch.setattr(tts, "vieneu_available", lambda: (False, "cần gói lồng tiếng"))
    r = _create(client, recording)
    assert r.status_code == 400 and "gói lồng tiếng" in r.json()["detail"]


def test_not_an_audio_file_is_refused(client, runner, tmp_path):
    bad = tmp_path / "x.mp3"
    bad.write_bytes(b"not audio at all" * 400)
    with open(bad, "rb") as fh:
        r = client.post("/api/voices/clones", files={"file": ("x.mp3", fh, "audio/mpeg")},
                        data={"name": "x", "consent": "true"})
    assert r.status_code == 400 and "Không đọc được file ghi âm" in r.json()["detail"]
    assert runner == []


def test_the_runner_measures_speech_not_the_room():
    sr = 24000
    tone = (0.3 * np.sin(np.linspace(0, 2 * np.pi * 220 * 3, sr * 3))).astype(np.float32)
    wav = np.concatenate([np.zeros(sr * 2, np.float32), tone, np.zeros(sr, np.float32) + 1e-4])
    assert 2.8 <= dub_runner._speech_seconds(wav, sr) <= 3.1
    assert dub_runner._speech_seconds(np.zeros(10, np.float32), sr) == 0.0


def _run(coro):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)
