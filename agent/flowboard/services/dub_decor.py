"""Frame and dancing mascot for a dubbed video (the "khung" and "nhân vật
nhún nhảy" of the subtitle editor on ``/tools/dub``).

Both live in the job's ``layout`` next to the subtitle position and the blur
band, and are burned in the same ffmpeg pass (``dub.video_filter``):

    source → frame (shrink onto a blurred / coloured background, optional
    border) → blur band → mascot (bouncing / swaying sticker) → subtitles

so every position the editor shows (blur band, subtitles, mascot) is a
fraction of the *output* frame. The mascot is prepared once with Pillow
(square crop from the top, circle mask + white ring, or the image as is):
per-frame masking in ffmpeg would cost minutes on a long video. An animated
GIF is used as is (no circle) and loops.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

FRAME_BG = ("blur", "color", "image")
MASCOT_MOTIONS = ("dance", "bounce", "sway", "none")
MASCOT_SHAPES = ("circle", "plain")
DEFAULT_FRAME: dict[str, Any] = {"scale": 0.84, "bg": "blur", "color": "#111111", "border": 0.006, "border_color": "#ffd814",
                                 "bg_image": ""}
DEFAULT_MASCOT: dict[str, Any] = {"media_id": "", "x": 0.83, "y": 0.9, "size": 0.26, "motion": "dance", "shape": "circle"}
#: Mascot sticker frame rate (a looped still) — smooth enough, cheap to overlay.
MASCOT_FPS = 30


def _num(raw: dict, key: str, lo: float, hi: float, default: float) -> float:
    try:
        v = raw.get(key)
        return round(min(hi, max(lo, float(v))), 4) if v is not None else default
    except (TypeError, ValueError):
        return default


def _hex(value: Any, default: str) -> str:
    v = str(value or "").strip()
    if len(v) == 7 and v.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in v[1:]):
        return v.lower()
    return default


def normalize_frame(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict) or not raw:
        return None
    d = DEFAULT_FRAME
    bg_image = str(raw.get("bg_image") or "").strip()[:64]
    bg = raw.get("bg") if raw.get("bg") in FRAME_BG else d["bg"]
    if bg == "image" and not bg_image:
        bg = "blur"  # no picture yet: the blurred video stands in
    return {
        "scale": _num(raw, "scale", 0.6, 1.0, d["scale"]),
        "bg": bg,
        "bg_image": bg_image,
        "color": _hex(raw.get("color"), d["color"]),
        "border": _num(raw, "border", 0.0, 0.03, d["border"]),
        "border_color": _hex(raw.get("border_color"), d["border_color"]),
    }


def normalize_mascot(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict) or not str(raw.get("media_id") or "").strip():
        return None
    d = DEFAULT_MASCOT
    return {
        "media_id": str(raw["media_id"]).strip()[:64],
        "x": _num(raw, "x", 0.05, 0.95, d["x"]),
        "y": _num(raw, "y", 0.15, 1.0, d["y"]),
        "size": _num(raw, "size", 0.08, 0.6, d["size"]),
        "motion": raw.get("motion") if raw.get("motion") in MASCOT_MOTIONS else d["motion"],
        "shape": raw.get("shape") if raw.get("shape") in MASCOT_SHAPES else d["shape"],
    }


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def frame_filter(frame: Optional[dict], width: int, height: int, src: str = "[0:v]", out: str = "[vf]",
                 bg_index: Optional[int] = None) -> str:
    """Shrink ``src`` onto a background the size of the frame. Empty when off.
    ``bg_index``: the input holding the background picture (``bg == "image"``)."""
    if not frame:
        return ""
    s = frame["scale"]
    fw, fh = _even(width * s), _even(height * s)
    b = int(round(height * frame["border"])) // 2 * 2
    if frame["bg"] == "image" and bg_index is not None:
        # the picture fills the frame (cover); [fr_a] is unused but must be consumed
        bg = (f"[{bg_index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,format=yuv420p[fr_img];"
              f"[fr_a]nullsink;[fr_img]copy[fr_bg]")
    elif frame["bg"] == "blur" or frame["bg"] == "image":
        bg = f"[fr_a]scale={width}:{height},boxblur={max(4, min(width, height) // 30)}:3[fr_bg]"
    else:
        bg = f"[fr_a]drawbox=x=0:y=0:w=iw:h=ih:color={frame['color']}@1:t=fill[fr_bg]"
    fg = f"[fr_b]scale={fw}:{fh},setsar=1"
    if b > 0:
        fg += f",pad={fw + 2 * b}:{fh + 2 * b}:{b}:{b}:color={frame['border_color']}"
    shortest = ":shortest=1" if frame["bg"] == "image" and bg_index is not None else ""
    return f"{src}split[fr_a][fr_b];{bg};{fg}[fr_fg];[fr_bg][fr_fg]overlay=(W-w)/2:(H-h)/2{shortest}{out}"


def local_media(media_id: str) -> Optional[Path]:
    """The file of ``media_id`` on this machine, fetched first when it is not
    (a picture Flow just drew, or one made on the other machine). Runs from
    the render thread, which has no event loop of its own."""
    import asyncio

    from flowboard.services import media as media_service

    if not media_id:
        return None
    try:
        p = media_service.cached_path(media_id)
        if not p or not Path(p).is_file():
            fetched = asyncio.run(media_service.fetch_and_cache(media_id))
            p = fetched[2] if fetched else None
    except Exception as exc:  # noqa: BLE001 — decorations are optional
        logger.warning("dub: media %s unavailable: %s", media_id, exc)
        return None
    return Path(p) if p and Path(p).is_file() else None


def frame_bg_path(frame: Optional[dict]) -> Optional[Path]:
    """The background picture's file on this machine (``bg == "image"``), else None."""
    if not frame or frame.get("bg") != "image" or not frame.get("bg_image"):
        return None
    return local_media(frame["bg_image"])  # None → the blurred video stands in


def cutout(src: Path, dst: Path, tolerance: int = 38) -> Path:
    """The sticker without its plain background: every pixel connected to the
    border whose colour is within ``tolerance`` of the border's colour turns
    transparent (AI stickers are asked for on plain white), edges feathered.
    A picture without a plain border comes back unchanged (as PNG)."""
    from PIL import Image, ImageFilter

    img = Image.open(src).convert("RGBA")
    w, h = img.size
    px = img.load()
    border = [px[x, 0] for x in range(0, w, max(1, w // 40))] + [px[x, h - 1] for x in range(0, w, max(1, w // 40))] + \
             [px[0, y] for y in range(0, h, max(1, h // 40))] + [px[w - 1, y] for y in range(0, h, max(1, h // 40))]
    ref = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))  # median border colour
    near = [c for c in border if sum(abs(c[i] - ref[i]) for i in range(3)) <= tolerance]
    if len(near) < len(border) * 0.6:  # not a plain background: leave the picture alone
        img.save(dst)
        return dst
    # flood fill from every border pixel over "close to the background" pixels
    from collections import deque

    seen = bytearray(w * h)
    q: deque[tuple[int, int]] = deque()
    for x in range(w):
        q.append((x, 0)); q.append((x, h - 1))
    for y in range(h):
        q.append((0, y)); q.append((w - 1, y))
    mask = Image.new("L", (w, h), 255)
    mp = mask.load()
    while q:
        x, y = q.popleft()
        i = y * w + x
        if seen[i]:
            continue
        seen[i] = 1
        c = px[x, y]
        if sum(abs(c[k] - ref[k]) for k in range(3)) > tolerance:
            continue
        mp[x, y] = 0
        if x > 0: q.append((x - 1, y))
        if x < w - 1: q.append((x + 1, y))
        if y > 0: q.append((x, y - 1))
        if y < h - 1: q.append((x, y + 1))
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    img.putalpha(mask)
    bbox = mask.point(lambda v: 255 if v > 24 else 0).getbbox()
    if bbox:
        img = img.crop(bbox)
    img.save(dst)
    return dst


def mascot_px(mascot: dict, height: int) -> int:
    return _even(height * mascot["size"])


def prepare_mascot(mascot: Optional[dict], height: int, work: Path) -> Optional[tuple[Path, bool]]:
    """``(file, animated)`` for the overlay: a PNG with alpha sized for the
    video (circle-cropped when asked), or the GIF itself. None when off or
    unreadable (the render goes on without it)."""
    if not mascot:
        return None
    from PIL import Image, ImageDraw, ImageOps

    src = local_media(mascot["media_id"])
    if src is None:
        logger.warning("dub: mascot %s not available; skipped", mascot["media_id"])
        return None
    px = mascot_px(mascot, height)
    try:
        img = Image.open(src)
        if getattr(img, "is_animated", False) and mascot["shape"] == "plain":
            return src, True  # an animated GIF loops as is; ffmpeg scales it
        img = ImageOps.exif_transpose(img.convert("RGBA"))
        if mascot["shape"] == "circle":
            side = min(img.width, img.height)
            # faces sit high in portraits: crop the square from the top, centred
            img = img.crop(((img.width - side) // 2, 0, (img.width - side) // 2 + side, side)).resize((px, px), Image.LANCZOS)
            big = px * 4  # supersampled mask for a smooth edge
            mask = Image.new("L", (big, big), 0)
            ring = max(3, px // 28) * 4
            ImageDraw.Draw(mask).ellipse((2, 2, big - 3, big - 3), fill=255)
            mask = mask.resize((px, px), Image.LANCZOS)
            out = Image.new("RGBA", (px, px), (0, 0, 0, 0))
            out.paste(img, (0, 0), mask)
            rim = Image.new("L", (big, big), 0)
            d = ImageDraw.Draw(rim)
            d.ellipse((2, 2, big - 3, big - 3), fill=255)
            d.ellipse((2 + ring, 2 + ring, big - 3 - ring, big - 3 - ring), fill=0)
            out.paste(Image.new("RGBA", (px, px), (255, 255, 255, 255)), (0, 0), rim.resize((px, px), Image.LANCZOS))
        else:
            w = max(2, round(img.width * px / img.height))
            out = img.resize((w, px), Image.LANCZOS)
        dst = work / "mascot.png"
        out.save(dst)
        return dst, False
    except Exception as exc:  # noqa: BLE001 — a bad image must not fail the render
        logger.warning("dub: mascot %s unusable: %s", mascot["media_id"], exc)
        return None


def mascot_input_args(path: Path, animated: bool) -> list[str]:
    return ["-ignore_loop", "0", "-i", str(path)] if animated else ["-loop", "1", "-framerate", str(MASCOT_FPS), "-i", str(path)]


def mascot_filter(mascot: dict, index: int, width: int, height: int, src: str, out: str = "[vm]", animated: bool = False) -> str:
    """Overlay input ``index`` (the prepared sticker) on ``src`` with its motion.
    Position: (x, y) = bottom-centre of the sticker, fractions of the frame."""
    px = mascot_px(mascot, height)
    m = f"[{index}:v]"
    chain = [f"scale=-2:{px}"] if animated else []
    chain.append("format=rgba")
    motion = mascot["motion"]
    if motion in ("dance", "sway"):
        amp, hz = (0.13, 0.9) if motion == "dance" else (0.09, 0.6)
        chain.append(f"rotate=a='{amp}*sin(2*PI*{hz}*t)':c=none:ow='hypot(iw,ih)':oh=ow")
    m += ",".join(chain) + "[mst]"
    bx, by = mascot["x"] * width, mascot["y"] * height
    x = f"{bx:.1f}-w/2"
    y = f"{by:.1f}-h"
    if motion == "dance":
        x += f"+{px * 0.05:.1f}*sin(2*PI*0.9*t)"
        y += f"-{px * 0.10:.1f}*abs(sin(2*PI*1.1*t))"
    elif motion == "bounce":
        y += f"-{px * 0.12:.1f}*abs(sin(2*PI*1.0*t))"
    return f"{m};{src}[mst]overlay=x='{x}':y='{y}':eval=frame:shortest=1:format=auto{out}"
