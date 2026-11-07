"""Flow's stamps the first clean-up got wrong (7/11, found on real Omni clips): the scene picture's star TWINKLING (its
opacity — and on some clips its size — pulsing from nothing to fully white every ~20 frames), and Flow's own star
missed on the stacked corner because a hard edge of the scene crossed it. Clips are built at 720×1280 with the stars
where Flow puts them; real ffmpeg (skipped without)."""
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from flowboard.services import video_watermark, watermark

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or shutil.which("ffprobe") is None, reason="ffmpeg not installed")
W, H, FPS, N = 720, 1280, 24, 40
R = 302  # the corner the clean-up works on (video_watermark._corner_size)
OWN = (H - R + 155, W - R + 155)  # Flow's own star box: (155, 155) of the corner
SCENE_CENTRE = (H - 90, W - 90)  # the scene picture's star, ~90 px from the edges


def _floor(i: int) -> np.ndarray:
    """A still, wood-ish floor with a little grain noise per frame (an encode's flicker) — BGR."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    v = 120 + 35 * np.sin((xx * 0.8 + yy * 0.3) / 11.0) + 12 * np.sin(yy / 37.0)
    rng = np.random.default_rng(i)
    v = v + rng.normal(0, 0.8, v.shape)
    return np.stack([v * 0.55, v * 0.75, v], axis=2).clip(0, 255).astype(np.uint8)


def _base() -> np.ndarray:
    tpl, _ty, _tx = watermark._template()
    return tpl


def _put(frame: np.ndarray, cov: np.ndarray, y: int, x: int, alpha: float) -> None:
    """A white star of coverage ``cov`` laid over ``frame`` at (y, x) with ``alpha``."""
    h, w = cov.shape
    box = frame[y:y + h, x:x + w].astype(np.float32)
    a = (alpha * cov)[:, :, None]
    frame[y:y + h, x:x + w] = (box * (1 - a) + 255 * a).clip(0, 255).astype(np.uint8)


def _scaled(scale: float) -> np.ndarray:
    import cv2

    return cv2.resize(_base(), None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _write(frames: list[np.ndarray], path: Path) -> None:
    proc = subprocess.Popen([FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(path)],
                            stdin=subprocess.PIPE)
    for f in frames:
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0


def _frames(path: Path) -> list[np.ndarray]:
    import cv2

    cap = cv2.VideoCapture(str(path))
    out = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        out.append(f)
    cap.release()
    return out


def _twinkle(i: int) -> float:
    """0.02 → fully white → 0.02 every 20 frames, as measured on the real clips."""
    return 0.02 + 0.98 * (0.5 - 0.5 * np.cos(2 * np.pi * i / 20.0))


def _err(got: list[np.ndarray], truth: list[np.ndarray], y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
    """Mean |cleaned − truth| over a box, per frame."""
    return np.array([np.abs(g[y0:y1, x0:x1].astype(np.float32) - t[y0:y1, x0:x1].astype(np.float32)).mean()
                     for g, t in zip(got, truth)])


def _clip(path: Path, *, scale_pulse: bool = False) -> list[np.ndarray]:
    own = _base()
    truth, frames = [], []
    for i in range(N):
        f = _floor(i)
        truth.append(f.copy())
        _put(f, own, OWN[0], OWN[1], 0.3)
        a = _twinkle(i)
        cov = _scaled(0.75 + 0.45 * (a - 0.02) / 0.98) if scale_pulse else _scaled(0.95)
        h, w = cov.shape
        _put(f, cov, SCENE_CENTRE[0] - h // 2, SCENE_CENTRE[1] - w // 2, a)
        frames.append(f)
    _write(frames, path)
    return truth


def test_twinkle_is_told_from_a_steady_overlay():
    assert video_watermark._twinkles([0.05, 0.2, 0.5, 0.8, 1.0, 0.7, 0.3, 0.1])
    assert not video_watermark._twinkles([0.29, 0.31, 0.3, 0.33, 0.28, 0.3])  # Flow's own star
    assert not video_watermark._twinkles([0.15, 0.3, 0.44, 0.2, 0.38, 0.25])  # a busy floor wobbling a steady one
    assert not video_watermark._twinkles([0.9, 0.95])  # too few reads to say


@needs_ffmpeg
@pytest.mark.parametrize("scale_pulse", [False, True], ids=["opacity", "opacity+size"])
def test_a_twinkling_scene_star_comes_out_on_every_frame(tmp_path, scale_pulse):
    src = tmp_path / "flow.mp4"
    truth = _clip(src, scale_pulse=scale_pulse)
    stamps, _info = video_watermark.find_static_stamps(src)
    assert sorted(st.varying for st in stamps) == [False, True]
    out = tmp_path / "clean.mp4"
    report = video_watermark.clean_video(src, out)
    assert report["static"] == 2 and report["twinkling"] == 1 and report["plate_frames"] > N // 2
    got, orig = _frames(out), _frames(src)
    cy, cx = SCENE_CENTRE
    box = (cy - 45, cy + 45, cx - 45, cx + 45)
    before, after = _err(orig, truth, *box), _err(got, truth, *box)
    assert before.max() > 18  # the star at full white (mean over the box)
    # every frame clean — the old clean-up left a white star at the peaks and painted a dark one on the faint frames
    assert after.max() < 6, after.round(1)
    own_box = (OWN[0], OWN[0] + 54, OWN[1], OWN[1] + 54)
    assert _err(got, truth, *own_box).mean() < 5


@needs_ffmpeg
def test_flows_own_star_is_found_where_a_hard_edge_crosses_it(tmp_path):
    """A black jacket edge sways across Flow's own star: the stacked corner shows a smeared edge, the star is read
    frame by frame at its fixed place instead (it was left in, 7/11)."""
    own = _base()
    truth, frames = [], []
    for i in range(N):
        f = _floor(i)
        edge = OWN[1] + 27 + int(round(18 * np.sin(2 * np.pi * i / N)))  # the jacket's edge moving over the star
        f[:, :edge] = (f[:, :edge].astype(np.float32) * 0.12).astype(np.uint8)
        truth.append(f.copy())
        _put(f, own, OWN[0], OWN[1], 0.3)
        frames.append(f)
    src = tmp_path / "jacket.mp4"
    _write(frames, src)
    stamps, info = video_watermark.find_static_stamps(src)
    assert any(video_watermark._near_own(st, info["corner"], info["k"]) for st in stamps)
    out = tmp_path / "clean.mp4"
    assert video_watermark.clean_video(src, out)["static"] >= 1
    box = (OWN[0], OWN[0] + 54, OWN[1], OWN[1] + 54)
    before, after = _err(_frames(src), truth, *box), _err(_frames(out), truth, *box)
    assert before.mean() > 15 and after.mean() < before.mean() / 3, (before.mean(), after.mean())


@needs_ffmpeg
def test_a_steady_star_is_pinned_and_not_pulled_by_a_bright_neighbour(tmp_path):
    """Flow's own star never moves: a twinkling neighbour at full white used to tilt the per-frame tracking by a pixel
    and the shifted inversion drew a dark arc along its edge."""
    src = tmp_path / "flow.mp4"
    _clip(src)
    stamps, _info = video_watermark.find_static_stamps(src)
    steady = [st for st in stamps if not st.varying]
    assert steady and steady[0].fixed


@needs_ffmpeg
def test_a_copy_left_by_the_older_clean_up_is_not_reused(tmp_path):
    """Copies the first clean-up made (a white / dark twinkling star left in) must not be picked up by the next join."""
    src = tmp_path / "flow.mp4"
    _clip(src)
    cache = tmp_path / "clean"
    cache.mkdir()
    stale = cache / "flow.clean.mp4"
    stale.write_bytes(b"made by the old clean-up")
    out = video_watermark.cleaned_copy(src, cache)
    assert out.name == f"flow.clean{video_watermark.CLEAN_VERSION}.mp4" and out.stat().st_size > 10_000
    assert not stale.exists()
    assert video_watermark.known_clean(src, cache) == out
