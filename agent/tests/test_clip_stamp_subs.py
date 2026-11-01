"""Clip export: Flow's ✦ stamp taken out of the clips (services/video_watermark), the subtitle look on the ffmpeg
path, and the Remotion path falling back to ffmpeg. Real ffmpeg (skipped without)."""
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.services import tts, video_export, video_watermark, watermark

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or shutil.which("ffprobe") is None, reason="ffmpeg not installed")
W, H, FPS, N = 360, 640, 24, 48
ALPHA = 0.32


def _texture(i: int) -> np.ndarray:
    """A moving wood-ish pattern (BGR): the corner changes every frame, as in a real clip."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    v = 110 + 40 * np.sin((xx + yy * 0.6 + i * 5) / 9.0) + 15 * np.sin((yy - i * 3) / 23.0)
    return np.stack([v * 0.55, v * 0.75, v], axis=2).clip(0, 255).astype(np.uint8)


def _star_box() -> tuple[np.ndarray, int, int]:
    """The stamp's shape and its top-left on the frame: centre ~60 px from the right and bottom edges (the 120 px of
    a 720-wide Flow clip, scaled to this 360-wide one)."""
    tpl, _ty, _tx = watermark._template()
    th, tw = tpl.shape
    return tpl, H - 60 - th // 2, W - 60 - tw // 2


def _write(frames: list[np.ndarray], path: Path) -> None:
    proc = subprocess.Popen([FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-f", "lavfi", "-i", "sine=frequency=330:duration=2",
                             "-shortest", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
                            stdin=subprocess.PIPE)
    for f in frames:
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0


def _stamped_clip(path: Path) -> list[np.ndarray]:
    tpl, y, x = _star_box()
    truth, frames = [], []
    for i in range(N):
        f = _texture(i)
        truth.append(f.copy())
        box = f[y:y + tpl.shape[0], x:x + tpl.shape[1]].astype(np.float32)
        a = (ALPHA * tpl)[:, :, None]
        f[y:y + tpl.shape[0], x:x + tpl.shape[1]] = (box * (1 - a) + 255 * a).clip(0, 255).astype(np.uint8)
        frames.append(f)
    _write(frames, path)
    return truth


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


def _box_error(frames: list[np.ndarray], truth: list[np.ndarray]) -> float:
    tpl, y, x = _star_box()
    core = tpl > 0.5
    errs = [np.abs(f[y:y + tpl.shape[0], x:x + tpl.shape[1]].astype(np.float32)
                   - t[y:y + tpl.shape[0], x:x + tpl.shape[1]].astype(np.float32))[core].mean()
            for f, t in zip(frames, truth)]
    return float(np.mean(errs))


@needs_ffmpeg
def test_the_stamp_comes_out_of_a_clip(tmp_path):
    src = tmp_path / "flow.mp4"
    truth = _stamped_clip(src)
    stamps, _info = video_watermark.find_static_stamps(src)
    assert len(stamps) == 1 and 0.22 < stamps[0].alpha < 0.42
    before = _box_error(_frames(src), truth)
    out = tmp_path / "clean.mp4"
    report = video_watermark.clean_video(src, out)
    assert report and report["static"] == 1 and report["frames"] == N
    after = _box_error(_frames(out), truth)
    assert before > 25 and after < before / 3, (before, after)
    info = video_export.probe_clip(out)
    assert info and info.has_audio and (info.width, info.height) == (W, H)


@needs_ffmpeg
def test_a_star_that_leaves_is_not_inverted_where_it_is_gone(tmp_path):
    """The scene picture's star leaves with the scene: frames without it must not get a dark star painted in."""
    tpl, y, x = _star_box()
    truth, frames = [], []
    for i in range(N):
        f = _texture(i)
        truth.append(f.copy())
        if i < N * 2 // 3:
            box = f[y:y + tpl.shape[0], x:x + tpl.shape[1]].astype(np.float32)
            a = (ALPHA * tpl)[:, :, None]
            f[y:y + tpl.shape[0], x:x + tpl.shape[1]] = (box * (1 - a) + 255 * a).clip(0, 255).astype(np.uint8)
        frames.append(f)
    src = tmp_path / "leaves.mp4"
    _write(frames, src)
    out = tmp_path / "clean.mp4"
    assert video_watermark.clean_video(src, out)["static"] == 1
    got = _frames(out)
    cut = N * 2 // 3 + 1
    assert _box_error(got[:cut - 2], truth[:cut - 2]) < 12
    assert _box_error(got[cut:], truth[cut:]) < 6  # untouched where the star is gone


@needs_ffmpeg
def test_a_clip_without_the_stamp_is_left_alone_and_not_probed_twice(tmp_path, monkeypatch):
    src = tmp_path / "own.mp4"
    _write([_texture(i) for i in range(N)], src)
    assert video_watermark.clean_video(src, tmp_path / "x.mp4") == {"static": 0}
    assert not (tmp_path / "x.mp4").exists()
    cache = tmp_path / "clean"
    assert video_watermark.cleaned_copy(src, cache) == src
    assert (cache / "own.nostamp").is_file()
    monkeypatch.setattr(video_watermark, "clean_video", lambda *a, **k: pytest.fail("probed again"))
    assert video_watermark.cleaned_copy(src, cache) == src


@needs_ffmpeg
def test_the_export_uses_the_stamp_free_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(video_export.config, "STORAGE_DIR", tmp_path)
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path / "media")
    src = tmp_path / "flow.mp4"
    truth = _stamped_clip(src)
    with get_session() as s:
        a = Asset(kind="video", uuid_media_id="5" * 8 + "-3333-4333-8333-333333333333", local_path=str(src))
        s.add(a); s.commit(); s.refresh(a); aid = a.id
    media, err, report = video_export.export_video([aid], smooth60=False)
    assert err is None and media and report["stamps_cleaned"] == 1
    with get_session() as s:
        out = Path(s.exec(__import__("sqlmodel").select(Asset).where(Asset.uuid_media_id == media)).first().local_path)
    assert _box_error(_frames(out), truth) < 12


def test_subtitle_looks_and_engine_choice(tmp_path, monkeypatch):
    for style, needle in (("outline", ",1,"), ("box_yellow", "&H0014D8FF"), ("box_white", "&H00F4F4F4")):
        p = tts.write_ass([(0, 1, "Xin chào")], tmp_path / f"{style}.ass", width=720, height=1280, style=style)
        line = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("Style: Default")][0]
        assert needle in line
        assert (",3," in line) == style.startswith("box")
    from flowboard.services import dub_remotion

    monkeypatch.setattr(dub_remotion, "available", lambda: (True, ""))
    assert video_export.subtitle_choice("remotion", "rm_karaoke") == ("remotion", "rm_karaoke")
    assert video_export.subtitle_choice("remotion", "nope") == ("remotion", dub_remotion.DEFAULT_STYLE)
    monkeypatch.setattr(dub_remotion, "available", lambda: (False, "no node"))
    assert video_export.subtitle_choice("remotion", "rm_box") == ("ass", "box_yellow")
    assert video_export.subtitle_choice("ass", "box_white") == ("ass", "box_white")
    assert video_export.subtitle_choice(None, None) == ("ass", "outline")


@needs_ffmpeg
def test_remotion_subtitles_fall_back_to_ffmpeg(tmp_path, monkeypatch):
    """Remotion fails: the same lines are burned by ffmpeg on the joined clip; the clips themselves carry none."""
    monkeypatch.setattr(video_export.config, "STORAGE_DIR", tmp_path)
    from flowboard.services import dub_remotion, media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path / "media")
    ids = []
    for i in range(2):
        f = tmp_path / f"c{i}.mp4"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x334455:size=360x640:rate=24:duration=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(f)], check=True)
        with get_session() as s:
            a = Asset(kind="video", uuid_media_id=f"{i + 6}" * 8 + "-4444-4444-8444-444444444444", local_path=str(f))
            s.add(a); s.commit(); s.refresh(a); ids.append(a.id)
    monkeypatch.setattr(video_export, "_synth_line", lambda text, opts, rate, voice=None: _fake_narration(tmp_path, text))
    monkeypatch.setattr(video_export, "_synth_to_fit", lambda text, opts, dur, voice=None: (_fake_narration(tmp_path, text), 0))
    calls = []

    def boom(spec, **_):
        calls.append(spec)
        raise RuntimeError("node missing")

    monkeypatch.setattr(dub_remotion, "render", boom)
    opts = video_export.NarrationOptions(lines=["Câu một", "Câu hai"], sub_engine="remotion", sub_style="rm_box")
    media, err, report = video_export.export_video(ids, smooth60=False, narration=opts)
    assert err is None and media
    assert calls and [c["text"] for c in calls[0]["props"]["cues"]] == ["Câu một", "Câu hai"]
    assert calls[0]["props"]["cues"][1]["start"] >= 2.0  # the second clip's line on the joined timeline
    assert report["subtitles_engine"] == "ass" and "node missing" in report["subtitles_error"]
    assert all("cues" not in c for c in report["clips"])


def _fake_narration(tmp_path: Path, text: str) -> "tts.Narration":
    wav = tmp_path / f"n{abs(hash(text)) % 10000}.wav"
    if not wav.exists():
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(wav)], check=True)
    return tts.Narration(path=wav, duration=1.0, words=[])
