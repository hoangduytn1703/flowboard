"""The machine check (services/machine): the NVIDIA card is asked for once and remembered in a file."""
from __future__ import annotations

import json
import subprocess

import pytest

from flowboard.services import machine, video_clean


@pytest.fixture()
def box(tmp_path, monkeypatch):
    """A machine of our own: its answer file, a countable nvidia-smi and a driver signature we can change."""
    calls = {"n": 0, "out": "NVIDIA GeForce RTX 3060, 566.36, 12288\n", "sig": "C:/smi|1|1"}

    def run(*a, **k):
        calls["n"] += 1
        return subprocess.CompletedProcess(a, 0 if calls["out"] else 9, stdout=calls["out"], stderr="")

    monkeypatch.setenv("FLOWBOARD_MACHINE_FILE", str(tmp_path / "machine.json"))
    monkeypatch.setattr(machine, "_mem", None)
    monkeypatch.setattr(machine, "_smi", lambda: "nvidia-smi" if calls["sig"] != "none" else None)
    monkeypatch.setattr(machine, "signature", lambda: calls["sig"])
    monkeypatch.setattr(machine.subprocess, "run", run)
    return calls


def test_the_card_is_asked_for_once_and_remembered(box, tmp_path, monkeypatch):
    assert machine.gpu()["name"] == "NVIDIA GeForce RTX 3060" and box["n"] == 1
    assert machine.has_gpu() and machine.limits() == [] and box["n"] == 1  # memory
    saved = json.loads((tmp_path / "machine.json").read_text(encoding="utf-8"))
    assert saved["gpu"]["vram_mb"] == 12288 and saved["signature"] == "C:/smi|1|1"
    # the next start: a new process reads the file — nvidia-smi is not started again
    monkeypatch.setattr(machine, "_mem", None)
    assert machine.gpu()["driver"] == "566.36" and box["n"] == 1
    # "Kiểm tra lại" asks again
    assert machine.public(refresh=True)["gpu"]["name"].endswith("3060") and box["n"] == 2


def test_a_new_driver_is_noticed_without_being_asked(box, monkeypatch):
    box["sig"], box["out"] = "none", ""
    assert machine.gpu() is None and box["n"] == 0  # no nvidia-smi on the machine: nothing to start
    keys = {x["key"]: x["state"] for x in machine.limits()}
    assert keys == {"ai_erase": "off", "whisper": "slow"}
    # a card + driver installed later: the signature changes, so the next start checks by itself
    monkeypatch.setattr(machine, "_mem", None)
    box["sig"], box["out"] = "C:/smi|2|2", "NVIDIA GeForce RTX 4060, 580.10, 8188\n"
    assert machine.gpu()["name"].endswith("4060") and box["n"] == 1 and machine.limits() == []


def test_a_file_that_is_broken_or_old_is_checked_again(box, tmp_path, monkeypatch):
    (tmp_path / "machine.json").write_text("{not json", encoding="utf-8")
    assert machine.has_gpu() and box["n"] == 1
    monkeypatch.setattr(machine, "_mem", None)
    (tmp_path / "machine.json").write_text(json.dumps({"version": 0, "gpu": None, "signature": "C:/smi|1|1"}), encoding="utf-8")
    assert machine.has_gpu() and box["n"] == 2


def test_no_card_switches_the_ai_erase_off_and_says_why(box, tmp_path, monkeypatch, client):
    root = tmp_path / "viedub"
    root.mkdir()
    (root / "vi_dub_erase.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(video_clean, "erase_python", lambda: root / "python.exe")
    monkeypatch.setattr(video_clean, "erase_root", lambda: root)
    assert video_clean.ai_status()["available"] is True  # the card is there
    monkeypatch.setattr(machine, "_mem", None)
    box["sig"], box["out"] = "none", ""
    st = video_clean.ai_status()
    assert st["available"] is False and st["no_gpu"] is True and "card màn hình" in st["reason"]
    with pytest.raises(video_clean.UnavailableError, match="card màn hình"):
        video_clean.start_ai_job("m1", tmp_path / "a.mp4", [])
    # the settings page shows it, and can ask again
    m = client.get("/api/app/status").json()["machine"]
    assert m["gpu"] is None and [x["key"] for x in m["limits"]] == ["ai_erase", "whisper"]
    box["sig"], box["out"] = "C:/smi|3|3", "NVIDIA GeForce GTX 1650, 551.23, 4096\n"
    again = client.post("/api/app/machine/recheck").json()
    assert again["gpu"]["name"].endswith("1650") and again["limits"] == []
