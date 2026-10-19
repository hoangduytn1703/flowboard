"""Cut a rendered Storyboard composite into one image per tile.

A Storyboard node holds ONE image: a rows×cols grid of tiles separated by
white margins, with a small number label in each tile and a one-line
caption printed in the white margin below it (the prompt that asks Flow
for that layout lives in ``frontend/src/lib/storyboardPrompt.ts``). The
grid is only *roughly* regular — Flow does not honour pixel-exact cell
sizes — so each cell is cut at the ideal grid line and then trimmed to
its picture area:

* a grayscale copy is thresholded at ``WHITE_LUMA`` → "ink" mask;
* per-row / per-column ink fraction is the mean of that mask along the
  other axis (a BOX resize to a 1-pixel strip gives that in one call);
* the picture is the longest contiguous run of rows (then columns, inside
  those rows) whose ink fraction exceeds ``INK_FRACTION``. Margins are
  all white (0 %), and a line of caption or label text only inks a few
  percent of its row, so both fall under the threshold and are dropped.
  Tiny dips inside the picture (a white stripe in the content) are
  bridged by ``GAP_FRACTION``.

If the run found is implausibly small (< ``MIN_PICTURE_FRACTION`` of the
cell on either axis — an almost-white picture, or a composite without
margins at all) the cell is used as-is with a small inset instead, so the
caller always gets ``rows * cols`` panels back.

Pure: no DB, no network — only Pillow and the file on disk.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

from PIL import Image

# Luma at or above this counts as "white" (margin / paper).
WHITE_LUMA = 235
# A row / column belongs to the picture when at least this fraction of
# its pixels is ink. Text rows sit well below it; picture rows well above.
INK_FRACTION = 0.35
# A detected run shorter than this fraction of the cell is not trusted.
MIN_PICTURE_FRACTION = 0.40
# Inset applied to the plain cell when detection is not trusted.
FALLBACK_INSET = 0.03
# Sub-threshold stretches up to this fraction of the axis are bridged so a
# thin white detail inside the picture does not cut the run in two.
GAP_FRACTION = 0.015


def _ink_profile(mask: Image.Image, axis: str) -> list[float]:
    """Mean ink (0..1) per row (``axis="rows"``) or per column of ``mask``.

    ``mask`` is mode ``L`` with 255 = ink, 0 = white. A BOX resize to a
    1-pixel-wide (or -tall) strip averages every row (column) exactly.
    """
    w, h = mask.size
    if axis == "rows":
        strip = mask.resize((1, h), Image.Resampling.BOX)
    else:
        strip = mask.resize((w, 1), Image.Resampling.BOX)
    return [v / 255.0 for v in strip.tobytes()]  # mode L: one byte per pixel


def _longest_run(
    fractions: list[float], threshold: float, max_gap: int
) -> Optional[tuple[int, int]]:
    """``(start, end)`` of the longest stretch with ``fraction > threshold``,
    where gaps of at most ``max_gap`` consecutive below-threshold entries
    are absorbed. ``end`` is exclusive. ``None`` when nothing is above."""
    best: Optional[tuple[int, int]] = None
    start: Optional[int] = None
    last_on = -1
    for i, f in enumerate(fractions):
        on = f > threshold
        if on:
            if start is None:
                start = i
            last_on = i
        elif start is not None and i - last_on > max_gap:
            if best is None or last_on + 1 - start > best[1] - best[0]:
                best = (start, last_on + 1)
            start = None
    if start is not None and (best is None or last_on + 1 - start > best[1] - best[0]):
        best = (start, last_on + 1)
    return best


def picture_box(cell: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box (left, top, right, bottom) of the picture inside one
    grid cell, in cell coordinates. Falls back to the inset cell."""
    w, h = cell.size
    gray = cell.convert("L")
    # Ink mask: 255 where the pixel is darker than paper, else 0.
    mask = gray.point(lambda v: 255 if v < WHITE_LUMA else 0)

    rows = _longest_run(_ink_profile(mask, "rows"), INK_FRACTION, max(1, round(h * GAP_FRACTION)))
    box: Optional[tuple[int, int, int, int]] = None
    if rows is not None and rows[1] - rows[0] >= h * MIN_PICTURE_FRACTION:
        # Columns are profiled inside the picture rows only, so the caption
        # below (which may span the whole cell width) cannot widen them.
        band = mask.crop((0, rows[0], w, rows[1]))
        cols = _longest_run(_ink_profile(band, "cols"), INK_FRACTION, max(1, round(w * GAP_FRACTION)))
        if cols is not None and cols[1] - cols[0] >= w * MIN_PICTURE_FRACTION:
            box = (cols[0], rows[0], cols[1], rows[1])

    if box is None:
        ix, iy = round(w * FALLBACK_INSET), round(h * FALLBACK_INSET)
        box = (ix, iy, w - ix, h - iy)
    return box


def split_composite(path: Path | str, rows: int, cols: int) -> list[bytes]:
    """PNG bytes for every tile of the composite at ``path``, in reading
    order (left → right, top → bottom). Always ``rows * cols`` items."""
    if rows < 1 or cols < 1:
        raise ValueError("rows and cols must be >= 1")
    with Image.open(path) as im:
        # Flatten alpha onto white so a transparent margin still reads as
        # paper; palette / grayscale sources become plain RGB.
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            image = flat
        else:
            image = im.convert("RGB")

    W, H = image.size
    out: list[bytes] = []
    for r in range(rows):
        for c in range(cols):
            # Ideal grid lines; the last cell absorbs the rounding remainder.
            x0, x1 = round(c * W / cols), round((c + 1) * W / cols)
            y0, y1 = round(r * H / rows), round((r + 1) * H / rows)
            cell = image.crop((x0, y0, x1, y1))
            l, t, rt, b = picture_box(cell)
            panel = cell.crop((l, t, rt, b))
            buf = io.BytesIO()
            panel.save(buf, format="PNG")
            out.append(buf.getvalue())
    return out
