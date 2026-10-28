"""📂 Reopen a dubbed video later: the tag inside the mp4, fingerprints, the board snapshot, the upload route."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from flowboard.services import dub
from flowboard.services import media as media_service


def _ffmpeg() -> str:
    f = shutil.which("ffmpeg")
    if f is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg / ffprobe missing")
    return f


def _clip(path: Path, colour: str = "blue") -> Path:
    subprocess.run([_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", f"color={colour}:size=160x284:rate=10:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.fixture
def media_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    dub.JOBS.clear()
    yield tmp_path
    dub.JOBS.clear()


def _job(jid: str, work: Path) -> dub.Job:
    job = dub.Job(id=jid, url="https://v.douyin.com/x/", source_media_id="src", status="done", name="Mẹo cho mẹ bầu")
    job.segments = [dub.Segment(0, 1, "你好", "Chào các mẹ", {"y": 0.4})]
    job.media_id, job.work = "out1", work
    return job


def test_tag_is_written_and_read_back(tmp_path):
    video = _clip(tmp_path / "a.mp4")
    assert dub.read_tag(video) is None
    dub._tag_file(_ffmpeg(), video, "flowboard-dub:abc123def456")
    assert dub.read_tag(video) == "abc123def456"


def test_a_downloaded_video_finds_its_project_by_tag_or_fingerprint(media_dir):
    ffmpeg = _ffmpeg()
    job = _job("abc123def456", media_dir / "dub" / "abc123def456")
    job.work.mkdir(parents=True)
    tagged = _clip(media_dir / "out1.mp4")
    dub._tag_file(ffmpeg, tagged, dub.output_tag(job))
    dub._record_output(job, tagged, "out1")
    dub.persist(job)
    dub.JOBS.clear()  # a restart: only job.json is left
    found = dub.identify(tagged)
    assert found and found["kind"] == "dub" and found["via"] == "tag" and found["job"].id == job.id
    assert found["job"].segments[0].look == {"y": 0.4}
    # a file without a tag (the tag was stripped) is still known by its bytes
    plain = _clip(media_dir / "plain.mp4", "red")
    dub.JOBS[job.id].outputs.append({"media_id": "x", "size": plain.stat().st_size, "sha256": dub.file_sha256(plain)})
    found = dub.identify(plain)
    assert found and found["via"] == "fingerprint" and found["job"].id == job.id
    # anything else: not ours
    assert dub.identify(_clip(media_dir / "other.mp4", "green")) is None


def test_project_comes_back_from_the_clip_snapshot_when_job_json_is_gone(client, media_dir):
    job = _job("feedbeef0001", media_dir / "dub" / "feedbeef0001")
    job.layout = dub.normalize_layout({"y": 0.7, "w": 0.8})
    job.board_id = dub._save_board(job)
    dub.JOBS.clear()  # job.json was never written (or the media folder was cleaned)
    back = dub.find_job("feedbeef0001")
    assert back is not None and back.board_id == job.board_id and back.status == "done"
    assert back.segments[0].text == "Chào các mẹ" and back.segments[0].look == {"y": 0.4} and back.layout["w"] == 0.8
    assert (media_dir / "dub" / "feedbeef0001" / "job.json").is_file()  # saved locally again
    assert client.get("/api/dub/jobs/feedbeef0001").status_code == 200


def test_identify_route_opens_a_dub_or_a_wizard_clip_and_refuses_strangers(client, media_dir):
    from flowboard.db import get_session
    from flowboard.db.models import Asset, Board, Node

    ffmpeg = _ffmpeg()
    job = _job("0123456789ab", media_dir / "dub" / "0123456789ab")
    job.work.mkdir(parents=True)
    out = _clip(media_dir / "dubbed.mp4")
    dub._tag_file(ffmpeg, out, dub.output_tag(job))
    dub.persist(job)
    with open(out, "rb") as f:
        r = client.post("/api/dub/identify", files={"file": ("my clip.mp4", f, "video/mp4")})
    assert r.status_code == 200 and r.json()["kind"] == "dub" and r.json()["job"]["job_id"] == job.id
    # a clip made in the wizard (no tag): matched against the clip's final video
    clip_file = _clip(media_dir / "wizard.mp4", "yellow")
    with get_session() as s:
        board = Board(name="Cơm cháy", data={"quicktool": {"template_id": "fast_food_ad"}})
        s.add(board)
        s.commit()
        s.refresh(board)
        s.add(Node(board_id=board.id, short_id="ex01", type="export", data={"mediaId": "wiz1"}, status="done"))
        s.add(Asset(kind="video", uuid_media_id="wiz1", local_path=str(clip_file), mime="video/mp4"))
        s.commit()
        board_id = board.id
    with open(clip_file, "rb") as f:
        r = client.post("/api/dub/identify", files={"file": ("download.mp4", f, "video/mp4")})
    assert r.status_code == 200 and r.json() == {"kind": "clip", "board_id": board_id, "name": "Cơm cháy"}
    with open(_clip(media_dir / "stranger.mp4", "white"), "rb") as f:
        r = client.post("/api/dub/identify", files={"file": ("x.mp4", f, "video/mp4")})
    assert r.status_code == 404 and "Không nhận ra" in r.json()["detail"]


def test_older_clips_get_a_snapshot_once(client, media_dir):
    from flowboard.db import get_session
    from flowboard.db.models import Board

    job = _job("cafe00000001", media_dir / "dub" / "cafe00000001")
    job.board_id = dub._save_board(job)
    with get_session() as s:  # a clip made before snapshots existed
        b = s.get(Board, job.board_id)
        qt = dict(b.data["quicktool"])
        qt["dub"] = {k: v for k, v in qt["dub"].items() if k != "snapshot"}
        b.data = {**b.data, "quicktool": qt}
        s.add(b)
        s.commit()
    dub.JOBS[job.id] = job
    assert client.get("/api/dub/jobs").status_code == 200
    with get_session() as s:
        assert s.get(Board, job.board_id).data["quicktool"]["dub"]["snapshot"]["segments"][0]["text"] == "Chào các mẹ"
    assert dub.backfill_snapshots() == 0  # once per job


def test_job_list_brief_and_limit(client, media_dir):
    for k in range(7):
        job = _job(f"aaaa0000000{k}", media_dir / "dub" / f"aaaa0000000{k}")
        job.started_at = 1000.0 + k
        dub.JOBS[job.id] = job
    five = client.get("/api/dub/jobs", params={"limit": 5}).json()
    assert [j["job_id"] for j in five][:2] == ["aaaa00000006", "aaaa00000005"] and len(five) == 5
    brief = client.get("/api/dub/jobs", params={"all": "true", "brief": "true"}).json()
    assert len(brief) == 7 and brief[0]["segments"] == [] and brief[0]["lines"] == 1 and brief[0]["started_at"] == 1006.0


def test_deleting_from_the_list_keeps_the_video_and_the_clip(client, media_dir):
    from flowboard.db import get_session
    from flowboard.db.models import Asset, Board

    job = _job("dddd00000001", media_dir / "dub" / "dddd00000001")
    job.work.mkdir(parents=True)
    (job.work / "voice.wav").write_bytes(b"w")
    out = media_dir / "out1.mp4"
    out.write_bytes(b"video")
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id="out1", local_path=str(out), mime="video/mp4"))
        s.commit()
    job.board_id = dub._save_board(job)
    dub.persist(job)
    running = _job("dddd00000002", media_dir / "dub" / "dddd00000002")
    running.status = "running"
    dub.JOBS[running.id] = running
    r = client.post("/api/dub/jobs/delete", json={"ids": [job.id, running.id, "nope"]}).json()
    assert r["deleted"] == [job.id]
    assert {x["job_id"] for x in r["skipped"]} == {running.id, "nope"}
    assert not job.work.exists() and job.id not in dub.JOBS
    assert job.id not in [j["job_id"] for j in client.get("/api/dub/jobs", params={"all": "true", "brief": "true"}).json()]
    # the exported video and the clip are untouched…
    assert out.read_bytes() == b"video"
    with get_session() as s:
        assert s.get(Board, job.board_id) is not None
    # …and the project still comes back when it is asked for (dropping the video in, the clip's step-5 link)
    assert dub.find_job(job.id) is not None
