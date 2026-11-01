"""Strip the Gemini ✦ stamp from Flow's generated videos (the image side lives in ``services/watermark``).

A Flow clip carries the white four-pointed star near its bottom-right corner in every frame (measured 1/11 on
720×1280 Omni clips: centred ~120 px from the right and bottom, ~52 px wide — the same shape as the image stamp).
Often a second star rides along: the one baked into the scene picture the clip was animated from (Flow keeps its own
copy of the picture, stamp included), sitting ~90 px from the corner and drifting with the camera.

How: the corner of a few dozen frames, median-stacked, shows what stays put (the moving picture averages out) — the
stamp(s) are found there by template matching at a few scales, and each one's opacity is read off the frames. Then
every frame is unblended at those places (``orig = (shown − a·255)/(1 − a)``, rim inpainted, like the images) and a
star that moves is looked for frame by frame. A clip without a stamp is left alone (``clean_video`` returns None), so
the seller's own footage, Muse clips and dubbed videos go through untouched.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from flowboard.services import watermark

logger = logging.getLogger(__name__)

#: corner searched (fraction of the short side; 300 px on a 720-wide clip)
CORNER_FRAC = 0.42
#: frames median-stacked to find the stamps that stay put
SAMPLE_FRAMES = 32
SCALES = (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2)
#: template match needed on the median corner / on one frame
STATIC_MIN_SCORE = 0.5
MOVING_MIN_SCORE = 0.62
#: a fainter match still counts when the frames agree it is an overlay that stays put: the same opacity everywhere
#: (spread under STEADY_SPREAD) and clearly brighter than around it (STEADY_LIFT) — the scene star on a light floor
#: scored 0.48 with opacity 0.27–0.29 and +9 levels on every frame read (1/11)
STEADY_MIN_SCORE = 0.38
STEADY_LIFT = 5.0
STEADY_SPREAD = 0.05
#: the star adds at least this much brightness over its surroundings (grey levels)
MIN_LIFT = 3.0
MIN_ALPHA, MAX_ALPHA = 0.08, 0.6
#: where a stamp's centre can be, px from the right / bottom edge on a 720-wide clip (scaled with the clip): the
#: clip's own star sits at ~120, the scene picture's at ~90 and drifting
ZONE_PX = (45, 175)
#: a stamp already taken out blocks matches only this close to it (the scene star often overlaps the clip's)
SUPPRESS_PX = 7
ENCODE_TIMEOUT_S = 15 * 60


@dataclass
class Stamp:
    y: int  # top-left of the star's box in the corner region
    x: int
    shape: np.ndarray  # coverage 0–1 of the star's box
    alpha: float = 0.0


def _ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def _corner_size(w: int, h: int) -> int:
    return max(160, min(int(round(min(w, h) * CORNER_FRAC)), w, h))


def _templates() -> list[tuple[float, np.ndarray]]:
    import cv2

    tpl, _ty, _tx = watermark._template()
    return [(sc, cv2.resize(tpl, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)) for sc in SCALES]


def _highpass(gray: np.ndarray) -> np.ndarray:
    import cv2

    return gray - cv2.GaussianBlur(gray, (0, 0), 12)


def _zone_mask(res: np.ndarray, region: int, th: int, tw: int, k: float) -> None:
    """Match positions whose star centre falls outside :data:`ZONE_PX` of the corner set to −1 (in place)."""
    lo, hi = ZONE_PX[0] * k, ZONE_PX[1] * k
    ys = region - (np.arange(res.shape[0]) + th / 2)  # centre's distance from the bottom edge
    xs = region - (np.arange(res.shape[1]) + tw / 2)  # … from the right edge
    res[(ys < lo) | (ys > hi), :] = -1
    res[:, (xs < lo) | (xs > hi)] = -1


def _matches(gray: np.ndarray, min_score: float, limit: int = 2, avoid: Optional[list[Stamp]] = None,
             k: float = 1.0) -> list[tuple[float, int, int, np.ndarray]]:
    """Up to ``limit`` star-shaped bright spots in the stamp zone of the corner: ``(score, y, x, shape)``, best first,
    not on top of each other nor of ``avoid``. ``k`` = clip width / 720."""
    import cv2

    hp = _highpass(gray)
    found: list[tuple[float, int, int, np.ndarray]] = []
    taken = [(st.y, st.x) for st in (avoid or [])]
    sup = max(2, int(round(SUPPRESS_PX * k)))
    for _ in range(limit):
        best: Optional[tuple[float, int, int, np.ndarray]] = None
        for _sc, tpl in _templates():
            th, tw = tpl.shape
            if th >= hp.shape[0] or tw >= hp.shape[1]:
                continue
            res = cv2.matchTemplate(np.ascontiguousarray(hp), tpl, cv2.TM_CCOEFF_NORMED)
            _zone_mask(res, gray.shape[0], th, tw, k)
            for y, x in taken + [(f[1], f[2]) for f in found]:  # never the same star twice
                res[max(0, y - sup):y + sup + 1, max(0, x - sup):x + sup + 1] = -1
            _mn, score, _ml, (bx, by) = cv2.minMaxLoc(res)
            if best is None or score > best[0]:
                best = (float(score), by, bx, tpl)
        if best is None or best[0] < min_score:
            break
        found.append(best)
    return found


def _background(gray: np.ndarray, stamp: Stamp) -> np.ndarray:
    """The corner without the star: its box (a little wider) inpainted from around it."""
    import cv2

    mask = np.zeros(gray.shape, np.uint8)
    h, w = stamp.shape.shape
    mask[stamp.y:stamp.y + h, stamp.x:stamp.x + w] = (stamp.shape > 0.03).astype(np.uint8) * 255
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=2)
    return cv2.inpaint(np.clip(gray, 0, 255).astype(np.uint8), mask, 3, cv2.INPAINT_TELEA).astype(np.float32)


def _alpha(gray: np.ndarray, stamp: Stamp) -> tuple[float, float]:
    """``(opacity, lift)`` of the star on this corner: on its solid core each pixel adds ``a · (255 − background)``."""
    bg = _background(gray, stamp)
    h, w = stamp.shape.shape
    g = gray[stamp.y:stamp.y + h, stamp.x:stamp.x + w]
    b = bg[stamp.y:stamp.y + h, stamp.x:stamp.x + w]
    core = stamp.shape > 0.75
    if not core.any():
        return 0.0, 0.0
    lift = float(np.median(g[core] - b[core]))
    a = float(np.median((g[core] - b[core]) / np.maximum(255.0 - b[core], 1.0) / stamp.shape[core]))
    return a, lift


#: how far a stamp that "stays put" is looked for around its place in each frame (the scene star drifts slowly)
TRACK_PX = 6
#: the rim inpainted after the inversion: the star's soft edge, widened (video compression smears it)
RIM_GROW = 3
RIM_CORE = 0.8


def _track(hp: np.ndarray, stamp: Stamp, k: float) -> tuple[int, int]:
    """Where ``stamp`` is on this frame (its high-passed corner), within :data:`TRACK_PX` of its place."""
    import cv2

    h, w = stamp.shape.shape
    t = max(2, int(round(TRACK_PX * k)))
    y0, x0 = max(0, stamp.y - t), max(0, stamp.x - t)
    y1, x1 = min(hp.shape[0], stamp.y + h + t), min(hp.shape[1], stamp.x + w + t)
    win = np.ascontiguousarray(hp[y0:y1, x0:x1])
    if win.shape[0] < h or win.shape[1] < w:
        return stamp.y, stamp.x
    res = cv2.matchTemplate(win, stamp.shape.astype(np.float32), cv2.TM_CCOEFF_NORMED)
    _mn, score, _ml, (bx, by) = cv2.minMaxLoc(res)
    return (y0 + by, x0 + bx) if score >= 0.3 else (stamp.y, stamp.x)


#: a stamp counts as there on a frame when it adds at least this share of the brightness its opacity should give
PRESENT_SHARE = 0.45


def _present(gray: np.ndarray, stamp: Stamp, alpha: float) -> bool:
    """Is the star really on this frame? Its core must be brighter than the inpainted background by a fair share of
    ``alpha · (255 − background)`` — a striped or busy floor gives a few levels by chance, the star gives tens."""
    bg = _background(gray, stamp)
    h, w = stamp.shape.shape
    g = gray[stamp.y:stamp.y + h, stamp.x:stamp.x + w]
    b = bg[stamp.y:stamp.y + h, stamp.x:stamp.x + w]
    core = stamp.shape > 0.75
    if not core.any():
        return False
    lift = float(np.median(g[core] - b[core]))
    expect = alpha * float(np.median(255.0 - b[core]))
    return lift >= max(MIN_LIFT, PRESENT_SHARE * expect)


def _unblend(region: np.ndarray, stamp: Stamp, alpha: float) -> None:
    """The star taken out of ``region`` (BGR, in place) and its widened rim inpainted from around it."""
    import cv2

    h, w = stamp.shape.shape
    y, x = stamp.y, stamp.x
    if y < 0 or x < 0 or y + h > region.shape[0] or x + w > region.shape[1]:
        return
    box = region[y:y + h, x:x + w]
    a = (min(alpha, MAX_ALPHA) * stamp.shape)[:, :, None]
    restored = (box.astype(np.float32) - a * 255.0) / (1.0 - a)
    region[y:y + h, x:x + w] = np.clip(np.rint(restored), 0, 255).astype(np.uint8)
    # the rim, on a crop a little larger than the star's box so the inpaint has plain pixels to draw from
    m = 8
    cy0, cx0 = max(0, y - m), max(0, x - m)
    cy1, cx1 = min(region.shape[0], y + h + m), min(region.shape[1], x + w + m)
    body = np.zeros((cy1 - cy0, cx1 - cx0), np.uint8)
    core = np.zeros_like(body)
    body[y - cy0:y - cy0 + h, x - cx0:x - cx0 + w] = (stamp.shape > watermark.EDGE_LOW).astype(np.uint8)
    core[y - cy0:y - cy0 + h, x - cx0:x - cx0 + w] = (stamp.shape > RIM_CORE).astype(np.uint8)
    rim = (cv2.dilate(body, np.ones((3, 3), np.uint8), iterations=RIM_GROW) & (1 - core)) * 255
    crop = np.ascontiguousarray(region[cy0:cy1, cx0:cx1])
    region[cy0:cy1, cx0:cx1] = cv2.inpaint(crop, rim, 3, cv2.INPAINT_TELEA)


def _unblend_gray(gray: np.ndarray, stamp: Stamp, alpha: float) -> None:
    """The star inverted out of a grey corner (in place) — for finding the next one."""
    h, w = stamp.shape.shape
    box = gray[stamp.y:stamp.y + h, stamp.x:stamp.x + w]
    a = min(alpha, MAX_ALPHA) * stamp.shape
    gray[stamp.y:stamp.y + h, stamp.x:stamp.x + w] = (box - a * 255.0) / (1.0 - a)


def find_static_stamps(path: Path) -> tuple[list[Stamp], dict]:
    """The stamps that stay put in this clip, with their opacity; ``([], info)`` when there is none."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        info = {"width": w, "height": h, "frames": n}
        if n <= 0 or min(w, h) < watermark.MIN_SIDE:
            return [], info
        r = _corner_size(w, h)
        grays: list[np.ndarray] = []
        for i in np.linspace(0, max(n - 1, 0), min(SAMPLE_FRAMES, n)).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, frame = cap.read()
            if ok and frame is not None:
                grays.append(cv2.cvtColor(frame[h - r:h, w - r:w], cv2.COLOR_BGR2GRAY).astype(np.float32))
    finally:
        cap.release()
    if len(grays) < 4:
        return [], info
    med = np.median(np.stack(grays), axis=0)
    if float(np.median(med)) > 248:  # a white corner hides the star (nothing to take out)
        return [], info
    stamps: list[Stamp] = []
    k = min(w, h) / 720.0
    info["k"] = k
    # one star at a time: once found, it is taken out of the median and the frames before looking for the next —
    # the same star matched again at another scale would otherwise be inverted twice (a dark star)
    work = med.copy()
    reads_from = grays[:: max(1, len(grays) // 12)]
    for _ in range(2):
        found = _matches(work, STEADY_MIN_SCORE, limit=1, avoid=stamps, k=k)
        if not found:
            break
        score, y, x, shape = found[0]
        st = Stamp(y, x, shape)
        reads = [_alpha(g, st) for g in reads_from]
        alphas = [a for a, lift in reads if lift >= MIN_LIFT]
        steady = [a for a, lift in reads if lift >= STEADY_LIFT]
        if score >= STATIC_MIN_SCORE:
            if len(alphas) < max(2, len(reads) // 3):
                break
        elif not (len(steady) >= max(3, 2 * len(reads) // 3) and float(np.std(steady)) < STEADY_SPREAD):
            break
        st.alpha = float(np.clip(np.median(alphas), MIN_ALPHA, MAX_ALPHA))
        if st.alpha <= MIN_ALPHA:
            break
        stamps.append(st)
        for g in [work, *reads_from]:
            _unblend_gray(g, st, st.alpha)
        logger.info("video_watermark: %s star at corner (%d,%d) score %.2f alpha %.2f", path.name, y, x, score, st.alpha)
    info["corner"] = r
    return stamps, info


def clean_video(src: Path, dst: Path, *, moving: bool = True) -> Optional[dict]:
    """``src`` re-encoded into ``dst`` without the stamp (sound copied): ``{static, moving_frames, frames}``;
    ``{"static": 0}`` when ``src`` has no stamp (nothing written); None when the clean-up could not run."""
    import cv2

    ffmpeg = _ffmpeg()
    if ffmpeg is None:
        return None
    try:
        stamps, info = find_static_stamps(src)
    except Exception as exc:  # noqa: BLE001 — a probe that fails must never break the export
        logger.warning("video_watermark: probe failed for %s: %s", src.name, exc)
        return None
    if not stamps:
        return {"static": 0}
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    w, h, r = info["width"], info["height"], info["corner"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".part.mp4")
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.6f}",
           "-i", "-", "-i", str(src), "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "libx264", "-preset", "fast",
           "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    frames = moved = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            region = frame[h - r:h, w - r:w]
            gray0 = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.float32)
            hp = _highpass(gray0)
            # each stamp placed on the frame as it came, and only where it really is on this frame: the scene
            # picture's star leaves with the scene, and inverting a star that is not there paints a dark one
            for st in stamps:
                y, x = _track(hp, st, info["k"])
                here = Stamp(y, x, st.shape)
                if _present(gray0, here, st.alpha):
                    _unblend(region, here, st.alpha)
            if moving:
                gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.float32)
                for _score, y, x, shape in _matches(gray, MOVING_MIN_SCORE, limit=1, avoid=stamps, k=info["k"]):
                    st = Stamp(y, x, shape)
                    a, lift = _alpha(gray, st)
                    if lift >= MIN_LIFT and MIN_ALPHA < a <= MAX_ALPHA:
                        _unblend(region, st, a)
                        moved += 1
            assert proc.stdin is not None
            proc.stdin.write(frame.tobytes())
            frames += 1
        assert proc.stdin is not None
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        code = proc.wait(timeout=ENCODE_TIMEOUT_S)
    except (BrokenPipeError, OSError, subprocess.TimeoutExpired) as exc:
        proc.kill()
        logger.warning("video_watermark: encode failed for %s: %s", src.name, exc)
        tmp.unlink(missing_ok=True)
        return None
    finally:
        cap.release()
    if code != 0 or not tmp.is_file() or tmp.stat().st_size == 0 or frames == 0:
        logger.warning("video_watermark: ffmpeg failed for %s: %s", src.name, err[-300:])
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(dst)
    return {"static": len(stamps), "moving_frames": moved, "frames": frames}


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(str(path), threading.Lock())


def turned_on() -> bool:
    try:
        return watermark.enabled()
    except Exception:  # noqa: BLE001 — no database (tests, logged out): on by default
        return True


def cleaned_copy(src: Path, cache_dir: Path) -> Path:
    """The clip without its stamp for an export: a copy kept in ``cache_dir`` (made once per source file), or
    ``src`` itself when it has no stamp or the clean-up failed. Off when the user turned the stamp clean-up off.
    One clean-up per file at a time (the background warm-up and an export may ask together)."""
    if not turned_on():
        return src
    with _lock_for(src):
        return _cleaned_copy(src, cache_dir)


def _cleaned_copy(src: Path, cache_dir: Path) -> Path:
    out = cache_dir / f"{src.stem}.clean.mp4"
    none = cache_dir / f"{src.stem}.nostamp"
    try:
        stat = src.stat()
    except OSError:
        return src
    if out.is_file() and out.stat().st_mtime >= stat.st_mtime:
        return out
    if none.is_file() and none.stat().st_mtime >= stat.st_mtime:
        return src
    report = clean_video(src, out)
    if report is None:  # could not run this time: the export goes on with the clip as it is
        return src
    if not report.get("static"):
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            none.write_text("no stamp", encoding="utf-8")  # remembered: the probe is not repeated for this file
        except OSError:
            pass
        return src
    logger.info("video_watermark: cleaned %s (%s)", src.name, report)
    return out


def prewarm(src: Path, cache_dir: Path) -> None:
    """A Flow clip just landed: clean it in the background so the export finds the copy ready ("chạy ngầm")."""
    if not turned_on():
        return

    def run() -> None:
        try:
            cleaned_copy(src, cache_dir)
        except Exception as exc:  # noqa: BLE001 — a warm-up never breaks anything; the export tries again
            logger.warning("video_watermark: warm-up failed for %s: %s", src.name, exc)

    threading.Thread(target=run, name=f"stamp-{src.stem[:8]}", daemon=True).start()
