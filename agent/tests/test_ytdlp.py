"""yt-dlp for links (services/ytdlp.py): which one runs, the own copy downloaded from yt-dlp's release and checked against
SHA2-256SUMS, its periodic self-update; and the link download itself (routes/reference_video._run_ytdlp): no size cap, a
duration filter, the agent's copy fetched when the machine has none (seen 10/11: "yt-dlp không có trên máy")."""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from flowboard.main import app
from flowboard.routes import reference_video as rv
from flowboard.services import ytdlp

client = TestClient(app)


@pytest.fixture()
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWBOARD_TOOLS_DIR", str(tmp_path / "tools"))
    monkeypatch.delenv("FLOWBOARD_YTDLP", raising=False)
    monkeypatch.setattr(ytdlp.shutil, "which", lambda name: None)
    return tmp_path / "tools"


def _release(monkeypatch, body: bytes, listed: bytes | None = None) -> list[str]:
    asset = ytdlp._asset()
    sums = f"{hashlib.sha256(listed if listed is not None else body).hexdigest()}  {asset}\n0000  yt-dlp.tar.gz\n"
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path.rsplit("/", 1)[-1])
        if request.url.path.endswith("SHA2-256SUMS"):
            return httpx.Response(200, text=sums)
        return httpx.Response(200, content=body)

    monkeypatch.setattr(ytdlp, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
    return asked


def test_the_machines_own_yt_dlp_comes_first_then_ours(tools, monkeypatch, tmp_path):
    assert ytdlp.find() is None and ytdlp.available()  # none yet, but it can be fetched
    own = ytdlp.own_path()
    own.parent.mkdir(parents=True)
    own.write_bytes(b"x")
    assert ytdlp.find() == str(own)
    monkeypatch.setattr(ytdlp.shutil, "which", lambda name: "/usr/bin/yt-dlp" if name == "yt-dlp" else None)
    assert ytdlp.find() == "/usr/bin/yt-dlp"
    chosen = tmp_path / "custom-yt-dlp"
    chosen.write_bytes(b"x")
    monkeypatch.setenv("FLOWBOARD_YTDLP", str(chosen))
    assert ytdlp.find() == str(chosen)


def test_our_copy_is_downloaded_and_checked_against_the_release_sums(tools, monkeypatch):
    asked = _release(monkeypatch, b"the real yt-dlp")
    path = ytdlp.ensure()
    assert Path(path) == ytdlp.own_path() and Path(path).read_bytes() == b"the real yt-dlp"
    assert asked == ["SHA2-256SUMS", ytdlp._asset()]

    ytdlp.own_path().unlink()
    _release(monkeypatch, b"something else", listed=b"the real yt-dlp")
    with pytest.raises(ytdlp.YtdlpError, match="mã kiểm tra"):
        ytdlp.ensure()
    assert not ytdlp.own_path().exists() and not list(tools.glob("*.part"))


def test_an_old_copy_updates_itself_once(tools, monkeypatch):
    own = ytdlp.own_path()
    own.parent.mkdir(parents=True)
    own.write_bytes(b"x")
    runs: list[list[str]] = []
    monkeypatch.setattr(ytdlp.subprocess, "run", lambda cmd, **k: runs.append(cmd) or subprocess.CompletedProcess(cmd, 0, b"Updated", b""))
    assert ytdlp.ensure() == str(own) and runs == []  # fresh: used as is
    old = time.time() - ytdlp.UPDATE_AFTER_S - 60
    os.utime(own, (old, old))
    ytdlp.ensure()
    assert runs == [[str(own), "-U"]]
    ytdlp.ensure()
    assert len(runs) == 1  # the clock restarted


def test_node_is_handed_to_yt_dlp_for_youtube(monkeypatch):
    monkeypatch.setattr(ytdlp.shutil, "which", lambda name: "/bin/node" if name == "node" else None)
    assert ytdlp.js_args() == ["--js-runtimes", "node"]
    monkeypatch.setattr(ytdlp.shutil, "which", lambda name: "/bin/x" if name in ("node", "deno") else None)
    assert ytdlp.js_args() == []  # deno is used by yt-dlp by itself
    monkeypatch.setattr(ytdlp.shutil, "which", lambda name: None)
    assert ytdlp.js_args() == []


def test_link_download_has_no_size_cap_and_refuses_long_videos(tmp_path, monkeypatch):
    from flowboard.services import media

    monkeypatch.setattr(media, "MEDIA_CACHE_DIR", tmp_path)
    monkeypatch.setattr(ytdlp, "ensure", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp, "js_args", lambda: [])
    seen: dict = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        if seen.get("long"):
            return subprocess.CompletedProcess(cmd, 0, b"[download] Crash does not pass filter (duration <= 3600), skipping ..", b"")
        (tmp_path / "m1.mp4").write_bytes(b"v")
        return subprocess.CompletedProcess(cmd, 0, b"title::Learjet 60 crash", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    path, title, err = rv._run_ytdlp("https://youtu.be/x", "m1", 3600)
    assert path == tmp_path / "m1.mp4" and title == "Learjet 60 crash" and not err
    assert "--max-filesize" not in seen["cmd"]
    assert "!duration | duration <= 3600" in seen["cmd"]
    seen["long"] = True
    path, _t, err = rv._run_ytdlp("https://youtu.be/y", "m2", 3600)
    assert path is None and "dài hơn 60 phút" in err

    def no_tool():
        raise ytdlp.YtdlpError("không tải được yt-dlp từ GitHub (offline)")

    monkeypatch.setattr(ytdlp, "ensure", no_tool)
    path, _t, err = rv._run_ytdlp("https://youtu.be/z", "m3")
    assert path is None and "yt-dlp" in err and "offline" in err


def test_an_upload_goes_to_disk_whole_without_a_size_cap(tmp_path, monkeypatch):
    from flowboard.services import media

    monkeypatch.setattr(media, "MEDIA_CACHE_DIR", tmp_path)
    big = b"\x00" * (3 * 1024 * 1024 + 7)  # several chunks
    r = client.post("/api/reference-video/upload", files={"file": ("long.mp4", big, "video/mp4")})
    assert r.status_code == 200 and r.json()["size"] == len(big)
    saved = tmp_path / f"{r.json()['media_id']}.mp4"
    assert saved.read_bytes() == big and not list(tmp_path.glob("*.part"))
    r = client.post("/api/reference-video/upload", files={"file": ("empty.mp4", b"", "video/mp4")})
    assert r.status_code == 400 and not list(tmp_path.glob("*.part"))
