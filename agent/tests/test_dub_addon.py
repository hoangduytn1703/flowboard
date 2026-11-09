"""The "gói lồng tiếng" (services/dub_addon.py): where dubbing finds its speech AI, the one-click install (every
step faked — no downloads), resumable downloads, the routes, and the runner's OCR band finder."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from flowboard import plans
from flowboard.main import app
from flowboard.services import dub, dub_addon, dub_runner, video_clean

client = TestClient(app)


@pytest.fixture()
def addon(tmp_path, monkeypatch):
    root = tmp_path / "addons" / "dub"
    monkeypatch.setenv("FLOWBOARD_DUB_ADDON_DIR", str(root))
    monkeypatch.setattr(video_clean, "erase_python", lambda: None)  # no VieDub on this "machine"
    monkeypatch.setattr(dub_addon, "nvidia_gpu", lambda refresh=False: None)
    dub_addon._state.update(running=False, error="", phase="", done_mb=0, total_mb=0)
    dub_addon._stop.clear()
    return root


def _fake_installed(root: Path, cuda: bool = True) -> None:
    py = dub_addon.venv_python(root)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("")
    model = root / "models" / dub_addon.WHISPER_DIR / "model.bin"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"x")
    onnx = root / "models" / "onnx"
    onnx.mkdir(parents=True, exist_ok=True)
    for n in dub_addon.SPLEETER_FILES:
        (onnx / n).write_bytes(b"x")
    (root / "addon.json").write_text(json.dumps({"version": 1, "cuda": cuda, "device": "cuda" if cuda else "cpu"}))


def test_the_runtime_is_viedub_first_then_the_addon(addon, monkeypatch, tmp_path):
    assert dub_addon.runtime() is None
    st = dub.status()
    assert st["available"] is False and st["runtime"] == "none"
    assert "gói lồng tiếng" in st["reason"] and st["addon"]["installed"] is False

    _fake_installed(addon)
    root, python, env = dub_addon.runtime()
    assert root == addon and python == dub_addon.venv_python(addon)
    assert env["HF_HOME"] == str(addon / "hf")  # VieNeu's model lands next to the add-on, not on C:
    st = dub.status()
    assert st["available"] is True and st["runtime"] == "addon" and st["separate"] is True

    # a half-installed add-on (no addon.json yet) does not count
    (addon / "addon.json").unlink()
    assert dub_addon.runtime() is None

    # a VieDub on the machine wins (it also has torch / LaMa)
    viedub = tmp_path / "viedub"
    fake_py = viedub / ".venv" / "python.exe"
    fake_py.parent.mkdir(parents=True)
    fake_py.write_text("")
    monkeypatch.setattr(video_clean, "erase_python", lambda: fake_py)
    monkeypatch.setattr(video_clean, "erase_root", lambda: viedub)
    assert dub_addon.runtime() == (viedub, fake_py, {})


def test_vieneu_and_the_runner_follow_the_runtime(addon, monkeypatch):
    from flowboard.services import tts

    ok, why = tts.vieneu_available()
    assert ok is False and "gói lồng tiếng" in why
    with pytest.raises(dub.DubError, match="gói lồng tiếng"):
        dub._runner("check")

    _fake_installed(addon)
    seen = {}

    class FakeProc:
        returncode = 0
        stdout = None
        stderr: list = []

        def __init__(self, cmd, **kw):
            seen.update(cmd=cmd, env=kw["env"], cwd=kw["cwd"])

        def poll(self):
            return 0

    monkeypatch.setattr(dub.subprocess, "Popen", FakeProc)
    assert tts.vieneu_available() == (True, "")
    dub._runner("check")
    assert seen["cmd"][0] == str(dub_addon.venv_python(addon)) and seen["cmd"][-1] == "check"
    assert seen["env"]["FLOWBOARD_ERASE_ROOT"] == str(addon) and seen["env"]["HF_HOME"] == str(addon / "hf")
    assert seen["cwd"] == str(addon)


def test_install_runs_every_step_and_writes_addon_json_last(addon, monkeypatch):
    commands: list[list[str]] = []
    downloaded: list[str] = []
    monkeypatch.setattr(dub_addon, "_free_mb", lambda p: 100_000)
    monkeypatch.setattr(dub_addon, "_ensure_uv", lambda root: root / "uv" / "uv.exe")
    monkeypatch.setattr(dub_addon, "pypi_wheel", lambda n, v, tag: (f"https://x/{n}.whl", 10, f"{n}-{v}.whl"))

    def fake_download(urls, dest, on_bytes=None, expect=0, attempts=4):
        downloaded.append(dest.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x" * 10)
        if on_bytes:
            on_bytes(10)
        return dest

    def fake_run(cmd, root, env=None, timeout=3600):
        commands.append(cmd)
        assert not (root / "addon.json").exists()  # never "ready" before the end
        if "venv" in cmd:
            py = dub_addon.venv_python(root)
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("")
        return ""

    monkeypatch.setattr(dub_addon, "download", fake_download)
    monkeypatch.setattr(dub_addon, "_run", fake_run)
    monkeypatch.setattr(dub_addon, "_warm_vieneu", lambda root, python, base: "")
    monkeypatch.setattr(dub_addon, "_check", lambda root, python: {"ok": True, "cuda": True, "device": "cuda"})

    gpu = {"name": "NVIDIA GeForce RTX 3060", "driver": "580.97", "vram_mb": 12288, "old_driver": False}
    dub_addon._install(gpu)
    pip = next(c for c in commands if "pip" in c)
    assert any(a.endswith("nvidia-cudnn-cu12-9.10.2.21.whl") for a in pip)  # the card's libraries, from local wheels
    assert "faster-whisper==1.2.1" in pip and "vieneu==3.8.3" in pip
    assert set(dub_addon.WHISPER_FILES) <= set(downloaded) and set(dub_addon.SPLEETER_FILES) <= set(downloaded)
    info = json.loads((addon / "addon.json").read_text(encoding="utf-8"))
    assert info["cuda"] is True and info["device"] == "cuda" and info["gpu"]["name"].endswith("3060")
    assert dub_addon.ready() and not (addon / "downloads").exists()
    assert dub_addon._state["done_mb"] == dub_addon._state["total_mb"] == dub_addon.plan_mb(True)

    # no NVIDIA card: no CUDA wheels, smaller download
    commands.clear()
    dub_addon._install(None)
    pip = next(c for c in commands if "pip" in c)
    assert not any("nvidia" in a for a in pip)
    assert dub_addon.plan_mb(False) < dub_addon.plan_mb(True)


def test_install_refuses_a_full_disk_and_reports_failures(addon, monkeypatch):
    monkeypatch.setattr(dub_addon, "_free_mb", lambda p: 1200)
    with pytest.raises(dub_addon.AddonError, match="chỉ còn 1.2 GB"):
        dub_addon._install({"name": "RTX", "driver": "580", "vram_mb": 0, "old_driver": False})

    def boom(gpu):
        raise dub_addon.AddonError("PyPI không trả lời")

    monkeypatch.setattr(dub_addon, "_install", boom)
    dub_addon._state["running"] = True
    dub_addon._worker(None)
    st = dub_addon.status()
    assert st["running"] is False and "PyPI không trả lời" in st["error"]
    assert dub_addon.outcome()["ok"] is False

    def cancelled(gpu):
        raise dub_addon._Cancelled()

    monkeypatch.setattr(dub_addon, "_install", cancelled)
    dub_addon._worker(None)
    assert "huỷ" in dub_addon.status()["error"].lower()


def test_download_resumes_a_part_and_falls_back_to_a_mirror(tmp_path, monkeypatch):
    body = b"0123456789"
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.host, request.headers.get("range", "")))
        if request.url.host == "down.example":
            return httpx.Response(503)
        rng = request.headers.get("range", "")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            return httpx.Response(206, content=body[start:], headers={"content-range": f"bytes {start}-9/10"})
        return httpx.Response(200, content=body)

    monkeypatch.setattr(dub_addon, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
    monkeypatch.setattr(dub_addon.time, "sleep", lambda s: None)
    dub_addon._stop.clear()
    dest = tmp_path / "model.bin"
    (tmp_path / "model.bin.part").write_bytes(body[:4])  # an earlier try stopped after 4 bytes
    got: list[int] = []
    dub_addon.download(["https://down.example/m", "https://mirror.example/m"], dest, got.append, attempts=2)
    assert dest.read_bytes() == body and not (tmp_path / "model.bin.part").exists()
    assert ("mirror.example", "bytes=4-") in calls and sum(got) == 6
    # already there: nothing fetched
    calls.clear()
    dub_addon.download(["https://mirror.example/m"], dest, expect=10)
    assert calls == []
    # "Huỷ" stops it
    dub_addon._stop.set()
    with pytest.raises(dub_addon._Cancelled):
        dub_addon.download(["https://mirror.example/m"], tmp_path / "other.bin")
    dub_addon._stop.clear()


def test_nvidia_smi_is_read(monkeypatch):
    monkeypatch.setattr(dub_addon.shutil, "which", lambda name: "nvidia-smi")
    monkeypatch.setattr(dub_addon.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout="NVIDIA GeForce RTX 3060, 512.15, 12288\n", stderr=""))
    gpu = dub_addon.nvidia_gpu(refresh=True)
    assert gpu["name"] == "NVIDIA GeForce RTX 3060" and gpu["vram_mb"] == 12288
    assert gpu["old_driver"] is (dub_addon.sys.platform == "win32")  # 512 < 528: CUDA 12 wants a newer driver
    monkeypatch.setattr(dub_addon.shutil, "which", lambda name: None)
    monkeypatch.setattr(dub_addon.sys, "platform", "linux")
    assert dub_addon.nvidia_gpu(refresh=True) is None
    dub_addon._gpu_cache.update(at=0.0, value=None)


def test_routes_and_plans(addon, monkeypatch):
    r = client.get("/api/dub/addon")
    assert r.status_code == 200
    body = r.json()
    assert body["installed"] is False and body["dir"] == str(addon) and body["download_mb"] > 2000
    started = {}
    monkeypatch.setattr(dub_addon, "install", lambda: started.setdefault("yes", {"running": True}))
    assert client.post("/api/dub/addon/install").json()["running"] is True
    _fake_installed(addon)
    assert client.post("/api/dub/addon/remove").status_code == 200
    assert not addon.exists()
    assert plans.feature_for("GET", "/api/dub/addon") is None  # machine setup, open to every plan
    assert plans.feature_for("POST", "/api/dub/addon/install") is None


def test_the_editor_finds_burnt_in_subtitles_with_the_addon(addon, monkeypatch, tmp_path):
    _fake_installed(addon)
    monkeypatch.setattr(dub, "_runner", lambda *a, **k: {"bands": [{"y0": 0.8, "y1": 0.88, "hits": 20}], "info": "ok"})
    got = video_clean.detect_bands(tmp_path / "v.mp4")
    assert got["bands"][0]["y0"] == 0.8


def test_the_runner_groups_text_lines_into_subtitle_bands():
    h, w = 1000, 600
    assert dub_runner.sub_like((150, 800, 450, 840), w, h)          # a wide line near the bottom
    assert not dub_runner.sub_like((10, 100, 40, 300), w, h)        # tall and thin
    assert not dub_runner.sub_like((500, 800, 590, 830), w, h)      # off to one side
    lines = [(800 + (i % 3), 842, i) for i in range(10)] + [(100, 140, 0), (101, 141, 1)]  # a band + a stray title
    bands = dub_runner.bands_from_lines(lines, h, 3)
    assert len(bands) == 1 and bands[0]["hits"] == 10
    assert 0.78 < bands[0]["y0"] < 0.80 and 0.85 < bands[0]["y1"] < 0.86
