"""Remove the Gemini sparkle ("✦") Flow stamps on generated images.

Flow's image models blend a four-point star, about 48 px wide, white,
into the bottom-right corner (74–124 px from the edges) of every image,
at the same place whatever the image size. Its *shape* (per-pixel
coverage, 0–1) was measured once on images with flat corners and shipped
as ``assets/gemini_star_alpha.png`` (160×160, the bottom-right corner).
Its *opacity* is not one number: measured on 70 images it sits around
0.20–0.23 on 1024² renders and 0.30–0.35 on 768×1376 / 1376×768 ones, so
it is estimated per image from how much brighter the star's core is than
the band around it (:func:`estimate_alpha`).

The overlay is plain alpha blending — ``shown = (1 − a)·orig + a·255`` — so
the original pixels come back: ``orig = (shown − a·255) / (1 − a)``. The
star's thin edge (where JPEG smeared the stamp) is then inpainted over a
2 px band. Images that do not carry the star (uploads, already-cleaned
files, white corners) are left alone: :func:`has_mark` checks that the
star's pixels really are brighter than their surroundings first.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

ALPHA_FILE = Path(__file__).resolve().parent.parent / "assets" / "gemini_star_alpha.png"
#: The corner the alpha map covers (pixels, from the bottom-right).
REGION = 160
#: Images smaller than this cannot carry the stamp at that offset.
MIN_SIDE = 300
#: Opacity estimates are kept in this range (division by 1 − a blows up noise above it).
MIN_ALPHA, MAX_ALPHA = 0.06, 0.6
#: Pixels of the star's rim that get inpainted after the inversion.
EDGE_LOW, EDGE_HIGH = 0.03, 0.45
#: The star must stand out from its surroundings by at least this much (0–255 levels).
DETECT_MIN_DELTA = 3.0
#: The stamp sits a few px further from the corner on 1024² renders than on
#: 768×1376 ones: the shape is matched within this many px of its nominal place.
MAX_SHIFT = 10
#: Template-match score below which there is no star there.
DETECT_MIN_SCORE = 0.35
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}


@lru_cache(maxsize=1)
def shape_map() -> np.ndarray:
    """Coverage of the star per pixel of the corner, 0–1 (1 = solid core)."""
    return np.asarray(Image.open(ALPHA_FILE).convert("L"), dtype=np.float32) / 255.0


def alpha_map() -> np.ndarray:  # kept for callers that want the shape
    return shape_map()


@lru_cache(maxsize=1)
def _masks() -> tuple[np.ndarray, np.ndarray]:
    """``(core, ring)``: the star's solid pixels, and a band of plain pixels around it."""
    import cv2

    a = shape_map()
    core = a > 0.75
    star = (a > 0.03).astype(np.uint8)
    k = np.ones((7, 7), np.uint8)
    ring = cv2.dilate(star, k, iterations=3).astype(bool) & ~cv2.dilate(star, k, iterations=1).astype(bool)
    return core, ring


def _corner(arr: np.ndarray) -> Optional[tuple[slice, slice]]:
    h, w = arr.shape[:2]
    if h < MIN_SIDE or w < MIN_SIDE:
        return None
    return slice(h - REGION, h), slice(w - REGION, w)


def _gray(region: np.ndarray) -> np.ndarray:
    reg = region.astype(np.float32)
    return reg.mean(axis=2) if reg.ndim == 3 else reg


@lru_cache(maxsize=1)
def _template() -> tuple[np.ndarray, int, int]:
    """The star alone (its bounding box, 2 px of margin) and where it sits in the corner."""
    s = shape_map()
    ys, xs = np.nonzero(s > 0.03)
    y0, y1, x0, x1 = max(ys.min() - 2, 0), min(ys.max() + 3, s.shape[0]), max(xs.min() - 2, 0), min(xs.max() + 3, s.shape[1])
    return np.ascontiguousarray(s[y0:y1, x0:x1]), y0, x0


def _background(region_gray: np.ndarray) -> np.ndarray:
    """What the corner looks like without the star: the star's area (with
    room for the shift) inpainted from its surroundings."""
    import cv2

    s = shape_map()
    mask = cv2.dilate((s > 0.03).astype(np.uint8), np.ones((5, 5), np.uint8), iterations=MAX_SHIFT // 2 + 1) * 255
    return cv2.inpaint(np.clip(region_gray, 0, 255).astype(np.uint8), mask, 3, cv2.INPAINT_TELEA).astype(np.float32)


def locate(region: np.ndarray) -> tuple[int, int, float, np.ndarray]:
    """Where the star really is on this corner: ``(dy, dx, score, delta)`` —
    the shift from the shipped shape's place, the match score (−1…1) and
    the brightness the star adds over the inpainted background."""
    import cv2

    g = _gray(region)
    delta = g - _background(g)
    tpl, ty, tx = _template()
    th, tw = tpl.shape
    y0, x0 = max(ty - MAX_SHIFT, 0), max(tx - MAX_SHIFT, 0)
    y1, x1 = min(ty + th + MAX_SHIFT, g.shape[0]), min(tx + tw + MAX_SHIFT, g.shape[1])
    win = np.ascontiguousarray(delta[y0:y1, x0:x1])
    res = cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED)
    _mn, score, _mnl, (bx, by) = cv2.minMaxLoc(res)
    return by + y0 - ty, bx + x0 - tx, float(score), delta


def shifted_shape(dy: int, dx: int) -> np.ndarray:
    s = shape_map()
    out = np.zeros_like(s)
    h, w = s.shape
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[yd, xd] = s[ys, xs]
    return out


def has_mark(arr: np.ndarray) -> bool:
    """True when the star is there: its shape matches the corner's extra
    brightness and that brightness is more than noise."""
    sl = _corner(arr)
    if sl is None:
        return False
    region = arr[sl]
    g = _gray(region)
    core = shape_map() > 0.75
    # A near-white background hides the star (nothing to remove either way).
    if np.median(g) > 248:
        return False
    dy, dx, score, delta = locate(region)
    shape = shifted_shape(dy, dx)
    lift = float(np.median(delta[shape > 0.75]))
    return score >= DETECT_MIN_SCORE and lift >= DETECT_MIN_DELTA and estimate_alpha(region, shape, raw=True) >= MIN_ALPHA


def estimate_alpha(region: np.ndarray, shape: Optional[np.ndarray] = None, *, raw: bool = False) -> float:
    """The stamp's opacity on this image: on each solid-core pixel the star
    adds ``a · (255 − background)``; the median over them is ``a``."""
    g = _gray(region)
    bg = _background(g)
    s = shape_map() if shape is None else shape
    core = s > 0.75
    room = np.maximum(255.0 - bg[core], 1.0)
    # Each core pixel carries a · shape; dividing by its shape gives the peak a.
    a = float(np.median((g[core] - bg[core]) / room / s[core]))
    return a if raw else float(np.clip(a, MIN_ALPHA, MAX_ALPHA))


def unblend(arr: np.ndarray) -> np.ndarray:
    """``arr`` (H×W×C uint8) with the star inverted out of its corner and
    its rim inpainted."""
    import cv2

    sl = _corner(arr)
    if sl is None:
        return arr
    out = arr.copy()
    region = out[sl]
    dy, dx, _score, _delta = locate(region)
    shape = shifted_shape(dy, dx)
    k = estimate_alpha(region, shape, raw=True)
    if k < MIN_ALPHA:  # nothing (left) to take out: a second pass must not darken the corner
        return arr
    k = min(k, MAX_ALPHA)
    a = (k * shape)[:, :, None] if out.ndim == 3 else k * shape
    restored = (region.astype(np.float32) - a * 255.0) / (1.0 - a)
    fixed = np.clip(np.rint(restored), 0, 255).astype(np.uint8)
    rim = ((shape > EDGE_LOW) & (shape < EDGE_HIGH)).astype(np.uint8) * 255
    if fixed.ndim == 3 and fixed.shape[2] >= 3:
        fixed[:, :, :3] = cv2.inpaint(np.ascontiguousarray(fixed[:, :, :3]), rim, 2, cv2.INPAINT_TELEA)
    out[sl] = fixed
    return out


def remove_from_file(path: Path, *, force: bool = False) -> bool:
    """Strip the stamp from an image file in place. Returns True when the
    file was changed; False when it has no stamp, is too small or is not
    an image we re-encode (GIF…)."""
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED or not path.is_file():
        return False
    try:
        with Image.open(path) as im:
            fmt = im.format
            mode = "RGBA" if im.mode in ("RGBA", "LA", "P") and fmt in ("PNG", "WEBP") else "RGB"
            img = im.convert(mode)
            info = {k: v for k, v in im.info.items() if k in ("icc_profile", "exif", "dpi")}
    except Exception as exc:  # noqa: BLE001 — a broken file is simply left alone
        logger.warning("watermark: cannot open %s: %s", path.name, exc)
        return False
    arr = np.asarray(img)
    rgb = arr[:, :, :3]
    if not force and not has_mark(rgb):
        return False
    cleaned = arr.copy()
    cleaned[:, :, :3] = unblend(rgb)
    out = Image.fromarray(cleaned, mode)
    save_kwargs: dict = {}
    if fmt == "JPEG":
        save_kwargs.update(quality=95, subsampling=0, optimize=True)
    elif fmt == "WEBP":
        save_kwargs.update(quality=95, method=4)
    tmp = path.with_name(path.stem + ".clean-tmp" + path.suffix)
    out.save(tmp, format=fmt, **save_kwargs, **info)
    tmp.replace(path)
    return True


# ── the switch and the batch run ───────────────────────────────────────────

SETTING_KEY = "clean_gemini_mark"


def enabled() -> bool:
    """On unless the user turned it off (AppSetting ``clean_gemini_mark``)."""
    from flowboard.db import get_session, has_engine
    from flowboard.db.models import AppSetting

    if not has_engine():
        return True
    with get_session() as s:
        row = s.get(AppSetting, SETTING_KEY)
    return row is None or row.value != "0"


def set_enabled(value: bool) -> None:
    from flowboard.db import get_session
    from flowboard.db.models import AppSetting

    with get_session() as s:
        row = s.get(AppSetting, SETTING_KEY)
        if row is None:
            s.add(AppSetting(key=SETTING_KEY, value="1" if value else "0"))
        else:
            row.value = "1" if value else "0"
            s.add(row)
        s.commit()


def clean_if_generated(path: Path, kind: Optional[str], mime: Optional[str]) -> bool:
    """The hook for media landing in the cache: generated images only
    (uploads come in through another door), and only while the switch is on."""
    if not (mime or "").startswith("image/") or kind not in (None, "", "image"):
        return False
    try:
        if not enabled():
            return False
        return remove_from_file(path)
    except Exception as exc:  # noqa: BLE001 — never let the stamp break serving the image
        logger.warning("watermark: cleaning %s failed: %s", Path(path).name, exc)
        return False


def cached_image_files() -> list[Path]:
    """Generated images that are on this machine (Asset kind image with a file)."""
    from sqlmodel import select

    from flowboard.db import get_session
    from flowboard.db.models import Asset

    out: list[Path] = []
    with get_session() as s:
        for row in s.exec(select(Asset).where(Asset.kind == "image")).all():
            if row.local_path and Path(row.local_path).is_file() and Path(row.local_path).suffix.lower() in SUPPORTED:
                out.append(Path(row.local_path))
    return out


def clean_cached_images() -> dict[str, int]:
    """Strip the stamp from every cached generated image that still has it."""
    checked = cleaned = 0
    for p in cached_image_files():
        checked += 1
        try:
            if remove_from_file(p):
                cleaned += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("watermark: %s skipped: %s", p.name, exc)
    return {"checked": checked, "cleaned": cleaned}
