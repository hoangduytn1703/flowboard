"""🎞 Chỉnh sửa video: files and clips come in as editor projects, are rendered without a word heard, hear later."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from flowboard import plans
from flowboard.db import get_session
from flowboard.db.models import Asset, Board, Node
from flowboard.services import dub, video_edit
from flowboard.services import media as media_service
from flowboard.services.video_export import probe_clip

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg missing")


def _clip(path: Path, seconds: float = 3.0) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=10:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def _wait(done, seconds: float = 90.0) -> None:
    end = time.time() + seconds
    while time.time() < end:
        if done():
            return
        time.sleep(0.1)
    raise AssertionError("timed out")


@pytest.fixture
def media_dir(monkeypatch, tmp_path):
    from flowboard import config

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    dub.JOBS.clear()
    video_edit._HEAR.clear()
    yield tmp_path
    dub.JOBS.clear()
    video_edit._HEAR.clear()


def _asset(media_dir: Path, media_id: str, seconds: float = 3.0) -> str:
    path = _clip(media_dir / f"{media_id}.mp4", seconds)
    with get_session() as db:
        db.add(Asset(kind="video", uuid_media_id=media_id, local_path=str(path), mime="video/mp4"))
        db.commit()
    return media_id


@needs_ffmpeg
def test_files_come_in_without_a_clip_and_render_with_no_words(client, media_dir):
    a, b = _asset(media_dir, "edita"), _asset(media_dir, "editb")
    r = client.post("/api/edit/import", json={"media": [{"media_id": a, "name": "Áo khoác 1.mp4"}, {"media_id": b, "name": "b.mp4"},
                                                        {"media_id": "nope", "name": "x.mp4"}]})
    assert r.status_code == 200, r.text
    made = r.json()
    assert len(made["job_ids"]) == 2 and made["errors"][0]["name"] == "x"
    items = client.get("/api/edit/items").json()["items"]
    assert [i["job_id"] for i in items] == made["job_ids"]
    first = items[0]
    assert first["name"] == "Áo khoác 1" and first["origin"] == "import" and first["lines"] == 0
    assert first["board_id"] is None and not first["edited"] and first["media_id"] == a
    with get_session() as db:  # nothing in "Clip của tôi" until an export
        assert db.exec(dub.select(Board)).all() == []
    # the dubbing list leaves them out; the picked-jobs read returns them
    assert client.get("/api/dub/jobs?all=true&brief=true").json() == []
    assert [j["job_id"] for j in client.get("/api/edit/jobs", params={"ids": ",".join(made["job_ids"] + ["gone", made["job_ids"][0]])}).json()] == made["job_ids"]

    # edit it: a square frame on a colour — rendered with no line at all → a clip of its own
    job = dub.JOBS[first["job_id"]]
    r = client.post(f"/api/dub/jobs/{job.id}/render", json={"layout": {"canvas": {"aspect": "1:1", "fit": "color"}}, "sub_lang": "none"})
    assert r.status_code == 200, r.text
    _wait(lambda: job.status in ("done", "error"))
    assert job.status == "done", job.error
    out = probe_clip(Path(media_service.cached_path(job.media_id)))
    assert out.width == out.height and out.has_audio and job.media_id != a
    assert job.board_id
    with get_session() as db:
        nodes = {n.type: n for n in db.exec(dub.select(Node).where(Node.board_id == job.board_id)).all()}
        assert nodes["export"].data["mediaId"] == job.media_id
    row = next(i for i in client.get("/api/edit/items").json()["items"] if i["job_id"] == job.id)
    assert row["edited"] and row["board_id"] == job.board_id

    # off the list: the untouched import loses its folder, the exported one keeps its clip and project
    other = dub.JOBS[made["job_ids"][1]]
    other_work = other.work
    gone = client.post("/api/edit/remove", json={"job_ids": made["job_ids"]}).json()
    assert gone["removed"] == made["job_ids"] and client.get("/api/edit/items").json()["items"] == []
    assert not other_work.exists() and job.id in dub.JOBS and (media_dir / "editb.mp4").is_file()
    with get_session() as db:
        assert db.get(Board, job.board_id) is not None


@needs_ffmpeg
def test_clips_bring_their_own_project_or_get_one(client, media_dir):
    src = _asset(media_dir, "clipvid")
    with get_session() as db:
        plain = Board(name="Clip quảng cáo", data={"quicktool": {"template_id": "fashion_ad"}})
        empty = Board(name="Chưa ghép", data={"quicktool": {"template_id": "fashion_ad"}})
        db.add(plain)
        db.add(empty)
        db.commit()
        db.refresh(plain)
        db.refresh(empty)
        db.add(Node(board_id=plain.id, short_id="ex01", type="export", x=0, y=0, data={"mediaId": src}, status="done"))
        db.commit()
        plain_id, empty_id = plain.id, empty.id
    # a dubbed clip: its board points at its job
    dubbed = dub.Job(id="dddd00000001", url=None, source_media_id=src, status="done", name="Đã lồng")
    dubbed.segments = [dub.Segment(0, 1, "hi", "chào")]
    dubbed.media_id, dubbed.work, dubbed.src_path = src, media_dir / "dub" / dubbed.id, media_dir / "clipvid.mp4"
    dub.JOBS[dubbed.id] = dubbed
    dubbed.board_id = dub._save_board(dubbed)

    got = client.post("/api/edit/clips", json={"board_ids": [dubbed.board_id, plain_id, empty_id]}).json()
    assert got["job_ids"][0] == dubbed.id and len(got["job_ids"]) == 2
    assert got["errors"][0]["name"] == "Chưa ghép"
    made = dub.JOBS[got["job_ids"][1]]
    assert video_edit.is_import(made) and made.cut["from_board"] == plain_id and made.name == "Clip quảng cáo" and made.board_id is None
    # asked again: the same project, not a second one
    again = client.post("/api/edit/clips", json={"board_ids": [plain_id]}).json()
    assert again["job_ids"] == [made.id]
    assert [i["job_id"] for i in client.get("/api/edit/items").json()["items"]] == [made.id, dubbed.id]
    # jobs sent over by the other tools join the list; a stranger does not
    assert client.post("/api/edit/add", json={"job_ids": ["zzzz", dubbed.id]}).json()["job_ids"] == [dubbed.id]
    assert client.get("/api/edit/items").json()["items"][0]["job_id"] == dubbed.id


@needs_ffmpeg
def test_words_are_heard_only_when_asked(client, media_dir, monkeypatch):
    a = _asset(media_dir, "hearme")
    jid = client.post("/api/edit/import", json={"media": [{"media_id": a, "name": "h.mp4"}]}).json()["job_ids"][0]
    job = dub.JOBS[jid]
    calls: list[str] = []

    def fake_runner(mode, wav, out, *rest, progress=None, stop=None):
        calls.append(mode)
        Path(out).write_text(json.dumps({"language": "en", "segments": [
            {"start": 0.2, "end": 1.4, "text": " Hello there "}, {"start": 1.6, "end": 2.8, "text": "Second line"},
            {"start": 2.9, "end": 2.9, "text": "x"}]}), encoding="utf-8")

    monkeypatch.setattr(dub, "_runner", fake_runner)
    monkeypatch.setattr(dub, "status", lambda: {"available": True})
    assert calls == [] and job.segments == []          # importing heard nothing
    assert client.post(f"/api/edit/jobs/{jid}/hear").json()["state"] in ("wait", "run", "done")
    _wait(lambda: client.get(f"/api/edit/jobs/{jid}/hear").json()["state"] == "done")
    assert calls == ["transcribe"]
    assert [(s.start, s.end, s.text) for s in job.segments] == [(0.2, 1.4, "Hello there"), (1.6, 2.8, "Second line")]
    assert job.sub_lang == "orig" and job.language == "en"
    assert client.post(f"/api/edit/jobs/{jid}/hear").status_code == 400   # already has its words
    assert client.get("/api/edit/items").json()["items"][0]["lines"] == 2


def test_the_page_is_for_plans_that_dub_or_cut():
    assert plans.feature_for("POST", "/api/edit/import") == ("dub", "cut")
    assert plans.feature_for("GET", "/api/edit/jobs") == ("dub", "cut")
    assert plans.feature_for("GET", "/api/dub/jobs") == ("dub",)
