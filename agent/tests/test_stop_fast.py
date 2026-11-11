"""11/11: "Dừng" ends the work at once — a running child (yt-dlp, ffmpeg) is killed with what it started, a job still
waiting its turn ends on the spot, and the page is told a stop is under way (so the button cannot be pressed twice)."""
from __future__ import annotations

import shutil
import subprocess
import sys
import time

import pytest

from flowboard.services import dub, dub_split, proc, video_cut

FFMPEG = shutil.which("ffmpeg")


def test_a_running_child_is_killed_within_a_moment():
    flag = {"stop": False}
    t0 = time.time()

    def stop() -> bool:
        if time.time() - t0 > 0.6:
            flag["stop"] = True
        return flag["stop"]

    with pytest.raises(proc.Stopped):
        proc.run_stoppable([sys.executable, "-c", "import time; time.sleep(60)"], 120, stop)
    assert time.time() - t0 < 5
    # left alone it ends like subprocess.run, with its output
    done = proc.run_stoppable([sys.executable, "-c", "print('ok')"], 60, lambda: False)
    assert done.returncode == 0 and done.stdout.strip() == b"ok"
    with pytest.raises(subprocess.TimeoutExpired):
        proc.run_stoppable([sys.executable, "-c", "import time; time.sleep(60)"], 0.5, None)


def test_cutting_stops_in_the_middle_of_a_part(tmp_path):
    if FFMPEG is None:
        pytest.skip("needs ffmpeg")
    src = tmp_path / "src.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=120",
                    "-c:v", "libx264", "-preset", "ultrafast", str(src)], check=True)
    t0 = time.time()
    with pytest.raises(dub_split.SplitError, match="Đã dừng"):
        dub_split._cut(FFMPEG, src, 0, 120, tmp_path / "part.mp4", "tag", stop=lambda: time.time() - t0 > 0.5)
    assert time.time() - t0 < 6 and not (tmp_path / "part.mp4").exists()


def test_a_waiting_job_ends_on_the_spot_and_a_running_one_says_it_is_stopping(monkeypatch):
    monkeypatch.setattr(dub, "_pump", lambda: None)
    monkeypatch.setattr(dub, "persist", lambda job: None)
    waiting = dub.Job(id="5707000000a1", url=None, source_media_id="m", status="queued")
    dub.stop_job(waiting)
    assert waiting.status == "error" and "Đã dừng" in (waiting.error or "") and waiting.public()["stopping"] is False
    running = dub.Job(id="5707000000a2", url=None, source_media_id="m", status="rendering")
    dub.stop_job(running)
    assert running.stop is True and running.status == "rendering" and running.public()["stopping"] is True
    s = video_cut.Session(id="5707000000b1", run_id="r", status="running")
    s.stop = True
    assert video_cut.public(s, brief=True)["stopping"] is True
    s.status = "error"
    assert video_cut.public(s, brief=True)["stopping"] is False
