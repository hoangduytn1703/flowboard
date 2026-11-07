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

The scene picture's star often TWINKLES (found 7/11 on 4 of 20 clips: Flow animates it from nothing to fully white and
back every ~0.8 s). One opacity for the whole clip left a white star on the bright frames and painted a dark one on the
faint frames, so such a star (:attr:`Stamp.varying`) has its opacity read on every frame, and where it is nearly opaque
— where the inversion would divide by almost nothing — it is filled in from around it instead (:func:`_remove`).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from dataclasses import dataclass, replace
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
#: a stamp TWINKLES (opacity read per frame) when it gets brighter than Flow's own overlay ever reads (0.2–0.45 over 20
#: clips) and swings widely: measured p90 0.58–1.02 with p90 − p25 ≥ 0.35 on the twinkling scene stars, p90 ≤ 0.45 on
#: the steady ones even where a busy floor makes the reading wobble (std up to 0.13)
TWINKLE_HIGH = 0.5
TWINKLE_SWING = 0.2
#: a GENTLE twinkle (a scene star swinging 0.11 → 0.42 and back, never brighter than Flow's own overlay): p90 − p25 ≥
#: 0.17 and p90 / p25 ≥ 1.9 over 48 frames of 40 clips (steady scene stars ≤ 0.12 / ≤ 1.5). Flow's own star on a busy floor
#: wobbles as much in the reading (to 0.20 / 1.9) — it is never taken for a twinkle (its place says what it is).
GENTLE_SWING = 0.17
GENTLE_RATIO = 1.9
#: a twinkling star is taken out of a frame only where the spot is star-shaped: the high-passed box correlates with
#: the star ≥ 0.6 whenever it reads above 0.06, 0.1–0.25 when it is not there (7/11)
FRAME_MIN_CORR = 0.45
FRAME_MIN_ALPHA = 0.04
#: past FILL_FROM the inversion amplifies the frame's noise (×3 at 0.67, ∞ at 1): the star is filled in from around it,
#: blended with the inversion up to FILL_TO so the patch does not pop as the star brightens
FILL_FROM, FILL_TO = 0.45, 0.75
FILL_CAP = 0.9
#: a twinkling star without a clean plate: filled in from much fainter on (inverting it left its outline at 0.4)
TWINKLE_FILL_FROM, TWINKLE_FILL_TO = 0.12, 0.35


@dataclass
class Stamp:
    y: int  # top-left of the star's box in the corner region
    x: int
    shape: np.ndarray  # coverage 0–1 of the star's box
    alpha: float = 0.0
    varying: bool = False  # twinkles: its opacity is read on each frame (see TWINKLE_HIGH, GENTLE_SWING)
    strong: bool = False  # twinkles up to (near) white: the fallback without a clean plate fills it in early
    fixed: bool = False  # never seen off its place: not tracked frame by frame (see FIXED_SHARE)
    white: float = 255.0  # the grey level the overlay is drawn in (see STEADY_WHITE)


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
    a = float(np.median((g[core] - b[core]) / np.maximum(stamp.white - b[core], 1.0) / stamp.shape[core]))
    return a, lift


#: how far a stamp that "stays put" is looked for around its place in each frame (the scene star drifts slowly)
TRACK_PX = 6
#: a stamp moves on a frame only when the match there beats staying put by this much
TRACK_GAIN = 0.03
#: a stamp seen at its place on this share of the sampled frames is pinned there (Flow's own overlay never moves)
FIXED_SHARE = 0.7
#: colour is stored at half resolution in the video (4:2:0) and smeared by the encode: the star's mark on the colour
#: planes is wider and softer than on brightness, so they are inverted with the shape blurred this much (px)
CHROMA_BLUR = 1.2
#: the grey level Flow's own (steady) star is drawn in. One clip's floor (dark → light under the star) suggested ~230,
#: but that came from the inpainted background across a hard edge: cleaning 6 clips with 255 / 240 / 230 left the same
#: (≈ 0 everywhere but that edge, where 230 looked slightly worse) — kept at white, like the image stamp (7/11).
STEADY_WHITE = 255.0
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
    if score < 0.3:
        return stamp.y, stamp.x
    # move only for a clearly better match: a bright neighbour (the twinkling star at full white) tilts the
    # correlation by a pixel and the shifted inversion drew a dark arc along the star's edge (7/11)
    ny, nx = stamp.y - y0, stamp.x - x0
    stay = float(res[ny, nx]) if 0 <= ny < res.shape[0] and 0 <= nx < res.shape[1] else -1.0
    return (y0 + by, x0 + bx) if score - stay >= TRACK_GAIN else (stamp.y, stamp.x)


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
    expect = alpha * float(np.median(np.maximum(stamp.white - b[core], 0.0)))
    return lift >= max(MIN_LIFT, PRESENT_SHARE * expect)


def _unblend(region: np.ndarray, stamp: Stamp, alpha: float, cap: float = MAX_ALPHA) -> None:
    """The star taken out of ``region`` (BGR, in place) and its widened rim inpainted from around it."""
    import cv2

    h, w = stamp.shape.shape
    y, x = stamp.y, stamp.x
    if y < 0 or x < 0 or y + h > region.shape[0] or x + w > region.shape[1]:
        return
    # on a crop a little larger than the star's box: the colour planes' (blurred) mark reaches past it, and the rim
    # inpaint needs plain pixels to draw from
    cy0, cx0, cy1, cx1 = _crop_bounds(region, stamp)
    crop0 = region[cy0:cy1, cx0:cx1]
    a = np.zeros(crop0.shape[:2], np.float32)
    a[y - cy0:y - cy0 + h, x - cx0:x - cx0 + w] = min(alpha, cap) * stamp.shape
    ac = np.minimum(cv2.GaussianBlur(a, (0, 0), CHROMA_BLUR), cap)
    # a white overlay is affine in YCrCb as in BGR: Y → 255, Cr/Cb → 128 (neutral); brightness with the sharp shape,
    # colour with the blurred one
    ycc = cv2.cvtColor(crop0, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    ycc[..., 0] = (ycc[..., 0] - a * stamp.white) / (1.0 - a)
    ycc[..., 1:] = (ycc[..., 1:] - ac[..., None] * 128.0) / (1.0 - ac[..., None])
    restored = cv2.cvtColor(np.clip(np.rint(ycc), 0, 255).astype(np.uint8), cv2.COLOR_YCrCb2BGR)
    touched = (a > 1e-3) | (ac > 1e-3)  # the YCrCb round trip is not lossless: leave the rest of the crop alone
    crop0[touched] = restored[touched]
    body = np.zeros((cy1 - cy0, cx1 - cx0), np.uint8)
    core = np.zeros_like(body)
    body[y - cy0:y - cy0 + h, x - cx0:x - cx0 + w] = (stamp.shape > watermark.EDGE_LOW).astype(np.uint8)
    core[y - cy0:y - cy0 + h, x - cx0:x - cx0 + w] = (stamp.shape > RIM_CORE).astype(np.uint8)
    rim = (cv2.dilate(body, np.ones((3, 3), np.uint8), iterations=RIM_GROW) & (1 - core)) * 255
    crop = np.ascontiguousarray(region[cy0:cy1, cx0:cx1])
    region[cy0:cy1, cx0:cx1] = cv2.inpaint(crop, rim, 3, cv2.INPAINT_TELEA)


def _crop_bounds(region: np.ndarray, stamp: Stamp, m: int = 8) -> tuple[int, int, int, int]:
    h, w = stamp.shape.shape
    return (max(0, stamp.y - m), max(0, stamp.x - m),
            min(region.shape[0], stamp.y + h + m), min(region.shape[1], stamp.x + w + m))


def _fill(region: np.ndarray, stamp: Stamp) -> None:
    """The star's whole body (and its widened rim) painted over from around it (BGR, in place)."""
    import cv2

    h, w = stamp.shape.shape
    y, x = stamp.y, stamp.x
    cy0, cx0, cy1, cx1 = _crop_bounds(region, stamp)
    body = np.zeros((cy1 - cy0, cx1 - cx0), np.uint8)
    body[y - cy0:y - cy0 + h, x - cx0:x - cx0 + w] = (stamp.shape > watermark.EDGE_LOW).astype(np.uint8)
    mask = cv2.dilate(body, np.ones((3, 3), np.uint8), iterations=RIM_GROW + 1) * 255
    crop = np.ascontiguousarray(region[cy0:cy1, cx0:cx1])
    region[cy0:cy1, cx0:cx1] = cv2.inpaint(crop, mask, 4, cv2.INPAINT_TELEA)


def _smoothstep(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def _remove(region: np.ndarray, stamp: Stamp, alpha: float, fill_from: float = FILL_FROM, fill_to: float = FILL_TO) -> None:
    """The star at its opacity on THIS frame taken out of ``region`` (BGR, in place): inverted while it is see-through,
    filled in from around it as it turns opaque, and a blend of both in between (no pop as a twinkling star brightens)."""
    h, w = stamp.shape.shape
    if stamp.y < 0 or stamp.x < 0 or stamp.y + h > region.shape[0] or stamp.x + w > region.shape[1]:
        return
    if alpha <= fill_from:
        _unblend(region, stamp, alpha)
        return
    cy0, cx0, cy1, cx1 = _crop_bounds(region, stamp)
    inverted = region.copy()
    _unblend(inverted, stamp, alpha, cap=FILL_CAP)
    filled = region.copy()
    _fill(filled, stamp)
    wt = _smoothstep((alpha - fill_from) / (fill_to - fill_from))
    mix = (inverted[cy0:cy1, cx0:cx1].astype(np.float32) * (1.0 - wt) + filled[cy0:cy1, cx0:cx1].astype(np.float32) * wt)
    region[cy0:cy1, cx0:cx1] = np.clip(np.rint(mix), 0, 255).astype(np.uint8)


#: a twinkling star's "clean plate": the background under it, kept from the frames where it was (almost) gone —
#: Flow's twinkle goes down to 0.03–0.1 every ~20 frames — and pasted back while it shines, as long as the scene around
#: it has not changed (a model of the star never fits it exactly: it is drawn as a glowing thing, not an even overlay)
PLATE_MAX_ALPHA = 0.12
PLATE_MAX_AGE = 36  # frames (1.5 s at 24 fps)
PLATE_RING_DIFF = 4.0  # mean grey-level change of the ring around the star (after a common shift) still "the same scene"
PLATE_MAX_SHIFT = 12.0  # a brightness change of the whole ring larger than this = not the same scene
#: a twinkling star also grows and shrinks with its brightness on some clips (a dot-sized star when faint, the tips past
#: the fitted shape at its peak — 7/11): each frame it is matched at these sizes (× the fitted one), and the plate is
#: pasted over the largest it can reach
TWINKLE_SCALES = (0.45, 0.6, 0.75, 0.9, 1.0, 1.1, 1.2, 1.32)
TWINKLE_ZONE_GROW = 1.12


class _Twinkle:
    """A twinkling star's frame-by-frame model: its shape at each size on a canvas around its place, the zone a plate
    is pasted over (the star at its largest, widened) and the ring outside it that tells whether the scene moved."""

    def __init__(self, st: Stamp, k: float):
        import cv2

        base, _ty, _tx = watermark._template()
        h, w = st.shape.shape
        sc, dy, dx, sigma = h / base.shape[0], 0.0, 0.0, 0.0
        e = int(np.ceil(0.3 * max(h, w))) + 8
        self.st, self.k, self.e = st, k, e
        self.size = (h + 2 * e, w + 2 * e)
        self.variants = [_render(base, sc * kk, dy, dx, sigma, self.size) for kk in TWINKLE_SCALES]
        # each size is matched only over its own box (+2 px): over the whole canvas a hard edge nearby (a floor line)
        # diluted the match and a plain twinkle went unseen
        self.boxes = []
        for s in self.variants:
            ys, xs = np.nonzero(s > 0.03)
            self.boxes.append((max(0, ys.min() - 2), min(s.shape[0], ys.max() + 3),
                               max(0, xs.min() - 2), min(s.shape[1], xs.max() + 3)))
        big = _render(base, sc * max(TWINKLE_SCALES) * TWINKLE_ZONE_GROW, dy, dx, sigma, self.size)
        kernel = np.ones((3, 3), np.uint8)
        self.zone = cv2.dilate((big > watermark.EDGE_LOW).astype(np.uint8), kernel, iterations=2)
        self.ring = (cv2.dilate(self.zone, kernel, iterations=4) > 0) & ~(self.zone > 0)
        self.weight = np.clip(cv2.GaussianBlur(self.zone.astype(np.float32), (0, 0), 1.5) * 1.15, 0.0, 1.0)[..., None]

    def origin(self, hp: np.ndarray) -> tuple[int, int]:
        st = self.st
        y, x = (st.y, st.x) if st.fixed else _track(hp, st, self.k)
        return y - self.e, x - self.e

    def read(self, region: np.ndarray) -> Optional[tuple[Stamp, float, bool, np.ndarray, tuple[int, int]]]:
        """(the star as it is on this frame, its opacity, really there?, the grey corner, canvas origin); None when the
        canvas falls off the corner."""
        import cv2

        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.float32)
        hp = _highpass(gray)
        oy, ox = self.origin(hp)
        hh, ww = self.size
        if oy < 0 or ox < 0 or oy + hh > gray.shape[0] or ox + ww > gray.shape[1]:
            return None
        win = np.ascontiguousarray(hp[oy:oy + hh, ox:ox + ww])
        best_c, best = -1.0, self.variants[0]
        for s, (y0, y1, x0, x1) in zip(self.variants, self.boxes):
            c = float(cv2.matchTemplate(np.ascontiguousarray(win[y0:y1, x0:x1]), np.ascontiguousarray(s[y0:y1, x0:x1]),
                                        cv2.TM_CCOEFF_NORMED)[0, 0])
            if c > best_c:
                best_c, best = c, s
        here = Stamp(oy, ox, best, white=255.0)
        a, lift = _alpha(gray, here)
        present = lift >= MIN_LIFT and a >= FRAME_MIN_ALPHA and best_c >= FRAME_MIN_CORR
        return here, a, present, gray, (oy, ox)


@dataclass
class _Plate:
    origin: tuple[int, int]  # the twinkle canvas's top-left in the corner when it was taken
    patch: np.ndarray  # BGR float32 of the canvas
    gray: np.ndarray
    frame: int

    @classmethod
    def take(cls, region: np.ndarray, tw: _Twinkle, origin: tuple[int, int], frame: int) -> "_Plate":
        import cv2

        oy, ox = origin
        hh, ww = tw.size
        patch = region[oy:oy + hh, ox:ox + ww].astype(np.float32).copy()
        return cls(origin, patch, cv2.cvtColor(patch.astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32), frame)

    def shift_for(self, gray: np.ndarray, tw: _Twinkle, origin: tuple[int, int], frame: int) -> Optional[float]:
        """The brightness shift to paste with when this plate still shows the scene around the star on this frame
        (``gray`` = the frame's corner); None when it is too old, from another place, or the scene moved."""
        if abs(frame - self.frame) > PLATE_MAX_AGE or origin != self.origin:
            return None
        oy, ox = origin
        hh, ww = tw.size
        diff = gray[oy:oy + hh, ox:ox + ww][tw.ring] - self.gray[tw.ring]
        shift = float(np.median(diff))
        if abs(shift) > PLATE_MAX_SHIFT or float(np.mean(np.abs(diff - shift))) > PLATE_RING_DIFF:
            return None
        return shift

    def paste(self, region: np.ndarray, tw: _Twinkle, shift: float) -> None:
        """The plate laid over the star's zone (feathered edge), brightened / darkened by ``shift`` like the frame."""
        oy, ox = self.origin
        hh, ww = tw.size
        area = region[oy:oy + hh, ox:ox + ww].astype(np.float32)
        mix = area * (1.0 - tw.weight) + (self.patch + shift) * tw.weight
        region[oy:oy + hh, ox:ox + ww] = np.clip(np.rint(mix), 0, 255).astype(np.uint8)


def _twinkles(alphas: list[float]) -> bool:
    """Does a stamp read this way twinkle up to (near) white (see :data:`TWINKLE_HIGH`)?"""
    if len(alphas) < 4:
        return False
    hi, lo = float(np.percentile(alphas, 90)), float(np.percentile(alphas, 25))
    return hi >= TWINKLE_HIGH and hi - lo >= TWINKLE_SWING


def _twinkles_gently(alphas: list[float]) -> bool:
    """Does a stamp read this way swing in opacity though it stays faint (see :data:`GENTLE_SWING`)?"""
    if len(alphas) < 4:
        return False
    hi, lo = float(np.percentile(alphas, 90)), float(np.percentile(alphas, 25))
    return hi - lo >= GENTLE_SWING and hi / max(lo, 0.01) >= GENTLE_RATIO


def _render(base: np.ndarray, scale: float, dy: float, dx: float, sigma: float, size: tuple[int, int]) -> np.ndarray:
    """The star (``base`` coverage map) at ``scale``, centred in a ``size`` box then shifted (dy, dx) px, blurred ``sigma``."""
    import cv2

    hh, ww = size
    bh, bw = base.shape
    m = np.float32([[scale, 0, (ww - bw * scale) / 2.0 + dx], [0, scale, (hh - bh * scale) / 2.0 + dy]])
    out = cv2.warpAffine(base, m, (ww, hh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if sigma > 0:
        out = cv2.GaussianBlur(out, (0, 0), sigma)
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def _unblend_gray(gray: np.ndarray, stamp: Stamp, alpha: float) -> None:
    """The star inverted out of a grey corner (in place) — for finding the next one."""
    h, w = stamp.shape.shape
    box = gray[stamp.y:stamp.y + h, stamp.x:stamp.x + w]
    a = min(alpha, MAX_ALPHA) * stamp.shape
    gray[stamp.y:stamp.y + h, stamp.x:stamp.x + w] = (box - a * stamp.white) / (1.0 - a)


#: candidates tried per round on the stacked corner before giving up
CANDIDATES = 3
#: where the scene picture's star sits when the clip does not zoom or pan: centre (90, 86) px from the right / bottom
#: edges (40 clips, 7/11 — the picture's own stamp, scaled into the frame). A star that stays put anywhere else was
#: never real in the clips looked at (an orange glow on a skin / sheet edge at (143, 94) was taken for one and its
#: "removal" painted red and black blotches); a star that drifts with the camera is left to the per-frame finder.
SCENE_CENTRE_PX = (90, 86)
SCENE_NEAR_PX = 16
#: Flow's own overlay is drawn at one place and one size: its box at (155, 155) of the 302-px corner with the template at
#: scale 1 — centre 120.5 px from the right and bottom edges — on 29 of the 31 Omni clips where it was found (the rest
#: within 2 px), portrait and landscape alike (7/11). When the stacked corner does not show it — a hard edge of the
#: scene cuts across it (a black jacket against a light wall: the median star scored 0.38) — it is read frame by frame
#: right there and taken when enough frames show a star-shaped brightening of one steady opacity
OWN_CENTRE_PX = 120.5
OWN_BOX_PX = 147  # its box's top-left, px from the right / bottom edges (302 − 155)
OWN_NEAR_PX = 15
#: no search around it: ±2 px let a black jacket's edge pull the box 2 px off the star (a white crescent left on one side,
#: a dark smudge on the other) while the fixed place read the star clearer on every frame (7/11)
OWN_SEARCH_PX = 0
OWN_READS = 12
OWN_MIN_CORR = 0.5  # the brightening against the star shape (inpainted background taken away)
OWN_AGREE = 0.4  # share of the read frames that must show it, at one opacity (± OWN_SPREAD)
OWN_SPREAD = 0.06
OWN_ALPHA = (0.15, 0.45)


def _accepted(score: float, reads: list[tuple[float, float]]) -> list[float]:
    """The opacities a candidate reads with when it counts as an overlay that stays put, else []."""
    alphas = [a for a, lift in reads if lift >= MIN_LIFT]
    steady = [a for a, lift in reads if lift >= STEADY_LIFT]
    if score >= STATIC_MIN_SCORE:
        ok = len(alphas) >= max(2, len(reads) // 3)
    else:
        ok = len(steady) >= max(3, 2 * len(reads) // 3) and float(np.std(steady)) < STEADY_SPREAD
    if not ok or float(np.clip(np.median(alphas), MIN_ALPHA, MAX_ALPHA)) <= MIN_ALPHA:
        return []
    return alphas


def _near_scene(st: Stamp, region: int, k: float) -> bool:
    h, w = st.shape.shape
    cx, cy = region - SCENE_CENTRE_PX[0] * k, region - SCENE_CENTRE_PX[1] * k
    return abs(st.x + w / 2 - cx) <= SCENE_NEAR_PX * k and abs(st.y + h / 2 - cy) <= SCENE_NEAR_PX * k


def _near_own(st: Stamp, region: int, k: float) -> bool:
    h, w = st.shape.shape
    c = region - OWN_CENTRE_PX * k
    return abs(st.y + h / 2 - c) <= OWN_NEAR_PX * k and abs(st.x + w / 2 - c) <= OWN_NEAR_PX * k


def _own_template(k: float) -> np.ndarray:
    import cv2

    base, _ty, _tx = watermark._template()
    return base if abs(k - 1.0) < 1e-3 else cv2.resize(base, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)


def _own_stamp(region: int, k: float, alpha: float = 0.0) -> Stamp:
    """Flow's own star at its fixed place and size (see OWN_CENTRE_PX)."""
    at = region - int(round(OWN_BOX_PX * k))
    return Stamp(at, at, _own_template(k), alpha=alpha)


#: Flow's own star's opacity read across its outline: each pixel just inside (shape > 0.97, 1.5–4 px in) against the
#: pixel just outside along the outline's normal (3 px past it), kept only where the background is flat along that
#: normal on both sides (< PAIR_FLAT grey levels over PAIR_STEP px). The inpainted-background reading smears a hard edge
#: under the star (dark floor / light wall) and read 0.347 on such a clip — a dark "V" was left at its lower tip; the
#: pairs read 0.306, where forcing the opacity by hand looked cleanest (~0.31). Used when at least PAIR_MIN_SHARE of
#: the pairs are kept (on a busy background there are too few flat ones to trust)
PAIR_IN_PX = (1.5, 4.0)
PAIR_GAP_PX = 3.0
PAIR_STEP_PX = 2.0
PAIR_FLAT = 3.0
PAIR_MIN_SHARE = 0.3


def _pair_alpha(grays: list[np.ndarray], stamp: Stamp) -> Optional[float]:
    """Opacity of ``stamp`` from pixel pairs across its outline (see PAIR_*), or None when too few pairs are usable."""
    import cv2

    s = stamp.shape.astype(np.float32)
    dist_in = cv2.distanceTransform((s > 0.5).astype(np.uint8), cv2.DIST_L2, 5)
    gy, gx = np.gradient(cv2.GaussianBlur(s, (0, 0), 1.5))
    mag = np.hypot(gx, gy)
    ys, xs = np.nonzero((s > 0.97) & (dist_in >= PAIR_IN_PX[0]) & (dist_in <= PAIR_IN_PX[1]) & (mag > 1e-3))
    if ys.size == 0:
        return None
    normal = np.stack([-gy[ys, xs], -gx[ys, xs]], 1) / mag[ys, xs][:, None]  # pointing out of the star
    inside = np.stack([ys, xs], 1).astype(np.float32)
    outside = inside + normal * (dist_in[ys, xs] + PAIR_GAP_PX)[:, None]

    def at(img: np.ndarray, pts: np.ndarray) -> np.ndarray:
        return cv2.remap(img, np.ascontiguousarray(pts[:, 1:2], np.float32), np.ascontiguousarray(pts[:, 0:1], np.float32),
                         cv2.INTER_LINEAR, borderValue=0).ravel()

    pts = (inside, inside - normal * PAIR_STEP_PX, outside, outside + normal * PAIR_STEP_PX)
    ok = (at(s, pts[2]) < 0.02) & (at(s, pts[1]) > 0.97)
    pts = tuple(x[ok] + np.array([stamp.y, stamp.x], np.float32) for x in pts)
    if pts[0].shape[0] == 0:
        return None
    vals, total = [], 0
    for g in grays:
        gp, gp2, gq, gq2 = (at(g, x) for x in pts)
        keep = (np.abs(gq - gq2) < PAIR_FLAT) & (np.abs(gp - gp2) < PAIR_FLAT)
        vals.append(((gp - gq) / np.maximum(stamp.white - gq, 1.0))[keep])
        total += gp.size
    kept = np.concatenate(vals)
    if total == 0 or kept.size < PAIR_MIN_SHARE * total:
        return None
    return float(np.median(kept))


def _probe_own_stamp(grays: list[np.ndarray], k: float) -> Optional[Stamp]:
    """Flow's own star read frame by frame at its fixed place (see OWN_CENTRE_PX); None when the frames do not show
    it clearly enough."""
    import cv2

    region = grays[0].shape[0]
    tpl = _own_template(k)
    th, tw = tpl.shape
    c = region - OWN_CENTRE_PX * k
    reads_from = grays[:: max(1, len(grays) // OWN_READS)]
    pad = int(round(OWN_SEARCH_PX * k))
    best: Optional[tuple[int, Stamp, float]] = None
    for dy in range(-pad, pad + 1):
        for dx in range(-pad, pad + 1):
            st = Stamp(region - int(round(OWN_BOX_PX * k)) + dy, region - int(round(OWN_BOX_PX * k)) + dx, tpl)
            if st.y < 0 or st.x < 0 or st.y + th > region or st.x + tw > region:
                continue
            seen: list[float] = []
            for g in reads_from:
                bg = _background(g, st)
                delta = np.ascontiguousarray((g - bg)[st.y:st.y + th, st.x:st.x + tw])
                corr = float(cv2.matchTemplate(delta, tpl, cv2.TM_CCOEFF_NORMED)[0, 0])
                a, lift = _alpha(g, st)
                if corr >= OWN_MIN_CORR and lift >= MIN_LIFT and OWN_ALPHA[0] <= a <= OWN_ALPHA[1]:
                    seen.append(a)
            if not seen:
                continue
            med = float(np.median(seen))
            agree = sum(1 for a in seen if abs(a - med) <= OWN_SPREAD)
            if best is None or agree > best[0]:
                best = (agree, st, med)
    if best is None or best[0] < OWN_AGREE * len(reads_from):
        return None
    _n, st, med = best
    st.alpha = float(np.clip(med, MIN_ALPHA, MAX_ALPHA))
    return st


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
    originals = [g.copy() for g in grays]
    # every sampled frame is read (32, spread over the clip): a twinkle lasts ~20 frames, 12 evenly spaced reads
    # could all land on the same phase of it
    reads_from = grays
    for _ in range(2):
        # the next few candidates, best first: a stripe or an edge that scores high but does not read as an overlay is
        # passed over — the loop used to stop at the first one and miss a real star ranked third (7/11)
        picked = None
        for score, y, x, shape in _matches(work, STEADY_MIN_SCORE, limit=CANDIDATES, avoid=stamps, k=k):
            st = Stamp(y, x, shape)
            if not (_near_own(st, r, k) or _near_scene(st, r, k)):  # only the two places a still star can be
                continue
            # (two stars can overlap at one place — a scene picture made from a picture that already had one: both are
            # real, 16 px apart. The same star matched again is not: it is taken out of the median first, and what is
            # left of it does not read as an overlay)
            reads = [_alpha(g, st) for g in reads_from]
            alphas = _accepted(score, reads)
            if alphas:
                picked = (st, reads, alphas, score)
                break
        if picked is None:
            break
        st, reads, alphas, score = picked
        st.alpha = float(np.clip(np.median(alphas), MIN_ALPHA, MAX_ALPHA))
        st.strong = _twinkles(alphas)
        st.varying = st.strong or _twinkles_gently(alphas)
        stamps.append(st)
        _unblend_gray(work, st, st.alpha)
        for g, (a, lift) in zip(reads_from, reads):  # each read frame at the opacity the star had on it
            if lift >= MIN_LIFT:
                _unblend_gray(g, st, a if st.varying else st.alpha)
        logger.info("video_watermark: %s star at corner (%d,%d) score %.2f alpha %.2f%s", path.name, st.y, st.x, score,
                    st.alpha, " (twinkles: opacity per frame)" if st.varying else "")
    if not any(_near_own(st, r, k) for st in stamps):
        own = _probe_own_stamp(reads_from, k)
        if own is not None:
            stamps.append(own)
            logger.info("video_watermark: %s Flow's own star found frame by frame at (%d,%d) alpha %.2f", path.name,
                        own.y, own.x, own.alpha)
    # each star's opacity read again on the frames with the other star taken out (they often overlap), in the grey the
    # overlay is drawn in, and whether it ever moves. (Fitting its shape to the clip — finer scale, sub-pixel place,
    # blur — was tried 7/11 and dropped: on a busy fabric the fit chased the texture and left stars the plain template
    # removed; it fixed nothing the plates and the pinning did not.)
    snapped = False
    for i, st in enumerate(list(stamps)):
        if _near_own(st, r, k):
            # Flow's own overlay never twinkles — a busy floor only makes its reading wobble. On the 720-px clips Flow
            # makes it is always the same box and size (a match on the stacked corner can land a template step smaller,
            # 45 px at (157, 159)); other sizes keep the match (the fixed place was measured on 720 only)
            st.varying = st.strong = False
            if abs(k - 1.0) < 0.05 and not snapped:  # (a second star next to it is another star: left where found)
                st = stamps[i] = _own_stamp(r, k, st.alpha)
                snapped = True
        st.white = 255.0 if st.varying else STEADY_WHITE
        frames = []
        for g in originals:
            g = g.copy()
            for j, other in enumerate(stamps):
                if j != i:
                    a, lift = _alpha(g, other)
                    if lift >= MIN_LIFT:
                        _unblend_gray(g, other, a if other.varying else other.alpha)
            frames.append(g)
        reads = [_alpha(g, st) for g in frames]
        alphas = [a for a, lift in reads if lift >= MIN_LIFT]
        if len(alphas) >= 2:
            st.alpha = float(np.clip(np.median(alphas), MIN_ALPHA, MAX_ALPHA))
        if _near_own(st, r, k):  # read across its outline when the background allows (see PAIR_*)
            paired = _pair_alpha(frames, st)
            if paired is not None:
                st.alpha = float(np.clip(paired, MIN_ALPHA, MAX_ALPHA))
        # never seen off its place on the frames where it shows: pinned (tracking only adds jitter). Flow's own star
        # never moves at all — a hard edge across it would only fool the tracking
        seen = [_track(_highpass(g), st, k) for g, (_a, lift) in zip(frames, reads) if lift >= STEADY_LIFT]
        st.fixed = _near_own(st, r, k) or (bool(seen) and sum(1 for y, x in seen if (y, x) == (st.y, st.x)) >= FIXED_SHARE * len(seen))
    info["corner"] = r
    return stamps, info


def _remove_steady(region: np.ndarray, steady: list[Stamp], k: float) -> None:
    """The steady stars out of this frame's corner (BGR, in place): each placed on the frame as it came, and only where
    it really is on this frame — the scene picture's star leaves with the scene, and inverting a star that is not there
    paints a dark one."""
    import cv2

    if not steady:
        return
    gray0 = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.float32)
    hp = _highpass(gray0)
    for st in steady:
        here = st if st.fixed else replace(st, **dict(zip(("y", "x"), _track(hp, st, k))))
        if _present(gray0, here, st.alpha):
            _unblend(region, here, st.alpha)


def _collect_plates(src: Path, info: dict, steady: list[Stamp], twinkles: list[_Twinkle]) -> dict[int, list[_Plate]]:
    """One pass over the clip: the background under each twinkling star on every frame where it is (almost) gone."""
    import cv2

    w, h, r, k = info["width"], info["height"], info["corner"], info["k"]
    out: dict[int, list[_Plate]] = {i: [] for i in range(len(twinkles))}
    cap = cv2.VideoCapture(str(src))
    n = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            region = frame[h - r:h, w - r:w]
            _remove_steady(region, steady, k)
            for i, tw in enumerate(twinkles):
                read = tw.read(region)
                if read is None:
                    continue
                here, a, present, _g, origin = read
                if present and a > PLATE_MAX_ALPHA:
                    continue
                if present:  # faint: its inversion is exact enough at this opacity
                    _unblend(region, here, a)
                out[i].append(_Plate.take(region, tw, origin, n))
            n += 1
    finally:
        cap.release()
    return out


def _pick_plate(plates: list[_Plate], gray: np.ndarray, tw: _Twinkle, origin: tuple[int, int],
                frame: int) -> Optional[tuple[_Plate, float]]:
    """The nearest plate in time (before or after) that still shows the scene around the star on this frame."""
    for plate in sorted(plates, key=lambda p: abs(p.frame - frame)):
        if abs(plate.frame - frame) > PLATE_MAX_AGE:
            break
        shift = plate.shift_for(gray, tw, origin, frame)
        if shift is not None:
            return plate, shift
    return None


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
    steady = [st for st in stamps if not st.varying]
    twinkling = [st for st in stamps if st.varying]
    k = info["k"]
    twinkles = [_Twinkle(st, k) for st in twinkling]
    # the twinkling stars' clean plates, from the whole clip (a frame early on may take one from a moment later)
    try:
        plates = _collect_plates(src, info, steady, twinkles) if twinkles else {}
    except Exception as exc:  # noqa: BLE001 — without plates each frame falls back on the model
        logger.warning("video_watermark: plates failed for %s: %s", src.name, exc)
        plates = {}
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    frames = moved = twinkled = plated = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            region = frame[h - r:h, w - r:w]
            _remove_steady(region, steady, k)
            for i, tw in enumerate(twinkles):
                read = tw.read(region)
                if read is None:
                    continue
                here, a, present, gray1, origin = read
                if not present:
                    continue
                picked = _pick_plate(plates.get(i, []), gray1, tw, origin, frames)
                if picked is not None:  # the real background, from a moment before or after
                    picked[0].paste(region, tw, picked[1])
                    plated += 1
                elif tw.st.strong:  # no plate fits (start of the clip, the scene moving): filled in early — the
                    # inversion of a star twinkling to white leaves its outline (it is drawn as a glow)
                    _remove(region, here, a, TWINKLE_FILL_FROM, TWINKLE_FILL_TO)
                else:  # a gentle one stays see-through: inverted at this frame's opacity
                    _remove(region, here, a)
                twinkled += 1
            if moving:
                gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.float32)
                for _score, y, x, shape in _matches(gray, MOVING_MIN_SCORE, limit=1, avoid=stamps, k=info["k"]):
                    st = Stamp(y, x, shape)
                    a, lift = _alpha(gray, st)
                    if lift >= MIN_LIFT and MIN_ALPHA < a <= FILL_CAP + 0.15:
                        _remove(region, st, a)
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
    return {"static": len(stamps), "twinkling": len(twinkling), "twinkle_frames": twinkled, "plate_frames": plated,
            "moving_frames": moved, "frames": frames}


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


def known_clean(src: Path, cache_dir: Path) -> Optional[Path]:
    """What :func:`cleaned_copy` would hand back for ``src`` when that is already settled (the stamp-free copy, or
    ``src`` itself: no stamp / clean-up off), without doing the work; None while not known yet."""
    if not turned_on():
        return src
    try:
        mtime = src.stat().st_mtime
    except OSError:
        return None
    out, none = _cache_names(src, cache_dir)
    if out.is_file() and out.stat().st_mtime >= mtime:
        return out
    if none.is_file() and none.stat().st_mtime >= mtime:
        return src
    return None


#: bumped when the clean-up changes what it writes, so copies made by an older one are not reused: 2 = twinkling
#: scene stars, Flow's own star found frame by frame, pinned stars, colour inverted with the blurred shape; 3 = Flow's
#: own star at its fixed box, gentle twinkles, still stars only at the two known places, one star per place (7/11);
#: 4 = Flow's own star's opacity read across its outline (no dark "V" on a hard edge)
CLEAN_VERSION = 4


def _cache_names(src: Path, cache_dir: Path) -> tuple[Path, Path]:
    """(the stamp-free copy, the "no stamp" marker) of ``src`` for this :data:`CLEAN_VERSION`."""
    return cache_dir / f"{src.stem}.clean{CLEAN_VERSION}.mp4", cache_dir / f"{src.stem}.nostamp{CLEAN_VERSION}"


def _drop_older(src: Path, cache_dir: Path) -> None:
    """Copies / markers an older clean-up left for ``src`` (they are not read any more)."""
    for old in [cache_dir / f"{src.stem}.clean.mp4", cache_dir / f"{src.stem}.nostamp",
                *(cache_dir / f"{src.stem}.clean{v}.mp4" for v in range(2, CLEAN_VERSION)),
                *(cache_dir / f"{src.stem}.nostamp{v}" for v in range(2, CLEAN_VERSION))]:
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass


def _cleaned_copy(src: Path, cache_dir: Path) -> Path:
    out, none = _cache_names(src, cache_dir)
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
    _drop_older(src, cache_dir)
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
