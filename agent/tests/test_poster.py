"""A still of a finished video for clip cards (services/poster, GET /api/media/{id}/poster)."""
import shutil
import subprocess

import pytest

from flowboard.services import media as media_service
from flowboard.services import poster

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def test_frame_time_stays_early_and_inside_the_video():
    assert poster.frame_time(0) == 0
    assert poster.frame_time(2) == 0.5      # short: half a second in
    assert poster.frame_time(12) == 1.2     # a tenth in
    assert poster.frame_time(600) == 3.0    # long: never later than 3 s
    assert poster.frame_time(0.6) == 0.3    # never past the middle


def test_poster_route_makes_a_still_once(client):
    mid = "a" * 32
    video = media_service.MEDIA_CACHE_DIR / f"{mid}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x568:rate=10:duration=3",
                    "-pix_fmt", "yuv420p", str(video)], check=True, timeout=60)
    r = client.get(f"/api/media/{mid}/poster")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    made = poster.poster_file(mid)
    assert made.is_file() and made.parent.name == "posters"
    stamp = made.stat().st_mtime_ns
    assert client.get(f"/api/media/{mid}/poster").status_code == 200 and made.stat().st_mtime_ns == stamp  # kept, not redone
    # not a video / unknown / bad id
    (media_service.MEDIA_CACHE_DIR / f"{'b' * 32}.txt").write_text("hello")
    assert client.get(f"/api/media/{'b' * 32}/poster").status_code == 404
    assert client.get(f"/api/media/{'c' * 32}/poster").status_code == 404
    assert client.get("/api/media/..%2Fsecret/poster").status_code in (400, 404)
