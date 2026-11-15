"""The resident VieNeu (services/voice_server) and the dub's early work (music + voice while the names are checked)."""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from flowboard.services import dub, tts, voice_server

# A stand-in for ``dub_runner.py serve``: the same protocol, no model. "slow" lines take 0.4 s each.
FAKE = r'''
import json, os, sys, time
MARK = "@@DFLOW "
out = sys.stdout
for raw in sys.stdin:
    req = json.loads(raw)
    if req.get("op") == "quit": break
    rid = req["id"]
    if req["op"] == "load":
        out.write(MARK + json.dumps({"id": rid, "ok": True}) + "\n"); out.flush(); continue
    print("some library chatter on stdout")  # not an answer: the agent skips it
    lines, done, cancelled = req["lines"], 0, False
    for i, item in enumerate(lines):
        if req.get("cancel_file") and os.path.exists(req["cancel_file"]): cancelled = True; break
        if item["text"] == "slow": time.sleep(0.4)
        open(item["out"], "wb").write(b"RIFF" + b"\0" * 400)
        done += 1
        sys.stderr.write(f"SPROGRESS {rid} {i + 1} {len(lines)}\n"); sys.stderr.flush()
    if cancelled:
        out.write(MARK + json.dumps({"id": rid, "ok": False, "cancelled": True}) + "\n")
    else:
        out.write(MARK + json.dumps({"id": rid, "ok": True, "done": done, "missing": [], "voice": req["voice"]}) + "\n")
    out.flush()
'''


@pytest.fixture
def server(tmp_path, monkeypatch):
    script = tmp_path / "fake_serve.py"
    script.write_text(FAKE, encoding="utf-8")
    monkeypatch.setattr(voice_server, "_command", lambda: ([sys.executable, str(script)], None, tmp_path))
    monkeypatch.setenv("FLOWBOARD_VOICE_SERVER", "1")
    monkeypatch.setenv("FLOWBOARD_VOICE_POOL", "1")
    voice_server.shutdown()
    yield tmp_path
    voice_server.shutdown()


def _items(folder: Path, *texts: str) -> list[dict[str, str]]:
    return [{"text": t, "out": str(folder / f"l{i}.wav")} for i, t in enumerate(texts)]


def test_the_model_stays_loaded_between_requests(server):
    seen = []
    ans = voice_server.speak("Hải Đăng", _items(server, "Một", "Hai"), progress=lambda k, n: seen.append((k, n)))
    assert ans["done"] == 2 and ans["servers"] == 1 and (server / "l1.wav").is_file()
    assert seen == [(1, 2), (2, 2)]
    pid = voice_server._servers[0].proc.pid
    voice_server.speak("@" + str(server / "voice.json"), _items(server, "Ba"))
    assert voice_server._servers[0].proc.pid == pid  # the same process: no second model load


def test_a_busy_server_sends_the_next_request_the_old_way(server):
    started = threading.Event()

    def long():
        started.set()
        voice_server.speak("Hải Đăng", _items(server, "slow", "slow", "slow"))

    th = threading.Thread(target=long)
    th.start()
    started.wait(5)
    time.sleep(0.2)
    with pytest.raises(voice_server.Busy):
        voice_server.speak("Hải Đăng", _items(server, "Một"))
    th.join(10)


def test_stop_ends_a_request_between_two_lines_and_the_server_lives_on(server):
    flag = {"stop": False}
    threading.Timer(0.5, lambda: flag.update(stop=True)).start()
    with pytest.raises(voice_server.Stopped):
        voice_server.speak("Hải Đăng", _items(server, *["slow"] * 10), stop=lambda: flag["stop"])
    assert voice_server.running()
    assert voice_server.speak("Hải Đăng", _items(server, "Một"))["done"] == 1


def test_a_dead_server_is_started_again_and_an_idle_one_goes(server, monkeypatch):
    voice_server.speak("Hải Đăng", _items(server, "Một"))
    old = voice_server._servers[0].proc
    old.kill()
    old.wait(5)
    assert voice_server.speak("Hải Đăng", _items(server, "Hai"))["done"] == 1
    assert voice_server._servers[0].proc.pid != old.pid
    monkeypatch.setattr(voice_server, "IDLE_S", 0.5)
    voice_server._last_used = time.time() - 10
    voice_server._reaper = None
    with voice_server._guard:
        voice_server._ensure()  # starts the idle watch again with the short limit
    for _ in range(40):
        if not voice_server.running():
            break
        time.sleep(0.25)
    assert not voice_server.running()


def test_a_long_request_is_shared_between_two_servers(server, monkeypatch):
    monkeypatch.setenv("FLOWBOARD_VOICE_POOL", "2")
    monkeypatch.setattr(voice_server, "POOL_START_LINES", 8)
    # shorter than POOL_START_LINES with no second server loaded: one server
    assert voice_server.speak("Hải Đăng", _items(server, *["Một"] * 7))["servers"] == 1
    seen = []
    texts = ["slow"] * 4 + ["Một"] * 3 + ["slow"] * 3
    t0 = time.time()
    ans = voice_server.speak("Hải Đăng", _items(server, *texts), progress=lambda k, n: seen.append((k, n)))
    took = time.time() - t0
    assert ans["done"] == 10 and ans["servers"] == 2 and all((server / f"l{i}.wav").is_file() for i in range(10))
    assert len([s for s in voice_server._servers if s is not None and s.alive()]) == 2
    assert seen[-1] == (10, 10) and [k for k, _ in seen] == sorted(k for k, _ in seen)
    assert took < 7 * 0.4  # seven slow lines would take 2.8 s on one server
    # a short request stays on the first one; a middle one uses the second now that it is loaded
    assert voice_server.speak("Hải Đăng", _items(server, "Một"))["servers"] == 1
    assert voice_server.speak("Hải Đăng", _items(server, *["slow"] * 7))["servers"] == 2
    monkeypatch.setenv("FLOWBOARD_VOICE_POOL", "")
    assert voice_server.pool_size() in (1, 2)


def test_warm_loads_the_model_ahead(server):
    assert voice_server.warm()
    for _ in range(40):
        if voice_server._first() is not None and voice_server._first().loaded:
            break
        time.sleep(0.1)
    assert voice_server._first().loaded


def test_tts_reads_through_the_server_and_falls_back_when_busy(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "TTS_DIR", tmp_path)
    monkeypatch.setattr(tts, "vieneu_available", lambda: (True, ""))
    monkeypatch.setenv("FLOWBOARD_VOICE_SERVER", "1")
    calls = []

    def fake_speak(voice, items, progress=None, stop=None, run_lines=None):
        calls.append(("server", voice, len(items)))
        if len(calls) == 2:
            raise voice_server.Busy("busy")
        for it in items:
            Path(it["out"]).write_bytes(b"RIFF" + b"\0" * 400)
        return {"done": len(items), "missing": []}

    def fake_runner(*args, **kwargs):
        calls.append(("runner", args[0]))
        for it in json.loads(Path(args[2]).read_text(encoding="utf-8")):
            Path(it["out"]).write_bytes(b"RIFF" + b"\0" * 400)
        return {"done": 1, "missing": []}

    monkeypatch.setattr(voice_server, "speak", fake_speak)
    monkeypatch.setattr(dub, "_runner", fake_runner)
    asyncio_run = __import__("asyncio").run
    asyncio_run(tts._synth_vieneu_many([("Một", tmp_path / "a.wav")], "vieneu:Hải Đăng"))
    asyncio_run(tts._synth_vieneu_many([("Hai", tmp_path / "b.wav")], "vieneu:Hải Đăng"))
    assert calls == [("server", "Hải Đăng", 1), ("server", "Hải Đăng", 1), ("runner", "vieneu")]


def test_the_voice_is_read_while_the_names_are_checked(tmp_path, monkeypatch):
    """_prepare: the music separates right after Whisper and the voice is read during the name check."""
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    src = tmp_path / "src.mp4"
    subprocess.run([dub._ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x284:rate=10:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=200:duration=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(src)], check=True)
    monkeypatch.setattr(media_service, "cached_path", lambda mid: src)

    def fake_runner(*args, **kwargs):
        if args[0] == "transcribe":
            Path(args[2]).write_text(json.dumps({"language": "zh", "segments": [
                {"start": 0, "end": 1, "text": "一"}, {"start": 1, "end": 2, "text": "二"}]}), encoding="utf-8")
        return {}

    order: list[str] = []
    voice_started = threading.Event()

    async def fake_translate(job):
        for s in job.segments:
            s.text = {"一": "Câu một", "二": "Câu hai"}[s.src]

    def fake_separate(job, ff, s, bgm, progress):
        order.append("music")

    async def fake_many(lines, voice, rate=0, style=None, progress=None, stop=None, run_lines=None):
        order.append("voice:" + "|".join(lines))
        voice_started.set()
        return []

    async def fake_names(job, title=""):
        assert voice_started.wait(5), "the voice should be read while the names are checked"
        order.append("names")
        job.segments[0].text = "Câu đã sửa"

    monkeypatch.setattr(dub, "_runner", fake_runner)
    monkeypatch.setattr(dub, "_translate", fake_translate)
    monkeypatch.setattr(dub, "_separate_bgm", fake_separate)
    monkeypatch.setattr(dub, "_check_names", fake_names)
    monkeypatch.setattr(dub, "needs_name_check", lambda job: True)
    monkeypatch.setattr(dub, "status", lambda: {"separate": True, "available": True})
    monkeypatch.setattr(tts, "synthesize_many", fake_many)
    job = dub.Job(id="e4a1ee000001", url=None, source_media_id="src", voice="vieneu:Hải Đăng", keep_bgm=True)
    dub._prepare(job)
    dub._wait_early_voice(job)
    th, errors = job._early_bgm
    th.join(5)
    assert "music" in order and "voice:Câu một|Câu hai" in order and order.index("voice:Câu một|Câu hai") < order.index("names")
    assert not errors and job.segments[0].text == "Câu đã sửa"
    # subtitles only / a review first: nothing started early
    job2 = dub.Job(id="e4a1ee000002", url=None, source_media_id="src", voice="vieneu:Hải Đăng", keep_bgm=True, mode="sub")
    order.clear()
    voice_started.set()
    dub._prepare(job2)
    assert getattr(job2, "_early_voice", None) is None and getattr(job2, "_early_bgm", None) is None and "music" not in order
