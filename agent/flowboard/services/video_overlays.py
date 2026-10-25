"""Text on the finished clip: product name, price, "Freeship", "👇 Bấm giỏ
hàng" — burned in one pass after the join, with libass (same as subtitles).

An overlay is ``{text, preset, position, start, end}``: ``preset`` picks the
look (see :data:`PRESETS`), ``position`` top / middle / bottom, ``start`` /
``end`` in seconds on the whole clip's timeline (``end`` empty = to the end).
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: preset → (text colour, box colour or None, size as a fraction of the frame
#: height, bold). Colours are ASS ``&HAABBGGRR``.
PRESETS: dict[str, tuple[str, Optional[str], float, bool]] = {
    "title": ("&H00FFFFFF", None, 0.050, True),          # big white, dark outline
    "price": ("&H0000E5FF", "&H202020D8", 0.060, True),   # yellow on a red box
    "badge": ("&H00FFFFFF", "&H20206AFF", 0.036, True),   # white on an orange box
    "cta": ("&H00FFFFFF", "&H40000000", 0.040, True),     # white on a dark box
}
POSITIONS = {"top": 8, "middle": 5, "bottom": 2}
MAX_OVERLAYS = 8
MAX_TEXT = 80


@dataclass
class Overlay:
    text: str
    preset: str = "title"
    position: str = "top"
    start: float = 0.0
    end: Optional[float] = None


def parse_overlays(raw: Any) -> list[Overlay]:
    """Clean overlays from request params; anything malformed is dropped."""
    out: list[Overlay] = []
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict):
            continue
        text = " ".join(str(it.get("text") or "").split())[:MAX_TEXT]
        if not text:
            continue
        try:
            # A negative start counts back from the end (-4 = the last 4 s),
            # so "price at the end" survives cuts and skipped scenes.
            start = max(-60.0, float(it.get("start") or 0))
            end = float(it["end"]) if it.get("end") not in (None, "") else None
        except (TypeError, ValueError):
            continue
        if end is not None and (end <= 0 or (start >= 0 and end <= start)):
            continue
        out.append(Overlay(
            text=text,
            preset=it.get("preset") if it.get("preset") in PRESETS else "title",
            position=it.get("position") if it.get("position") in POSITIONS else "top",
            start=start, end=end,
        ))
        if len(out) >= MAX_OVERLAYS:
            break
    return out


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _escape(text: str) -> str:
    # ASS override blocks start with "{"; a backslash starts a tag.
    return text.replace("\\", "/").replace("{", "(").replace("}", ")")


def write_overlay_ass(overlays: list[Overlay], path: Path, *, width: int, height: int, total_s: float) -> Path:
    styles = []
    for name, (colour, box, size_frac, bold) in PRESETS.items():
        size = max(24, round(height * size_frac))
        if box:
            # BorderStyle 3 = opaque box behind the text, coloured by OutlineColour.
            style = (f"Style: {name},Arial,{size},{colour},&H000000FF,{box},&H00000000,"
                     f"{-1 if bold else 0},0,0,0,100,100,0,0,3,{max(6, size // 5)},0,8,60,60,0,1")
        else:
            style = (f"Style: {name},Arial,{size},{colour},&H000000FF,&H00000000,&H80000000,"
                     f"{-1 if bold else 0},0,0,0,100,100,0,0,1,{max(3, size // 10)},2,8,60,60,0,1")
        styles.append(style)
    header = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles, "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    # Anchor lines clear of the subtitles (bottom ~16 %) and TikTok's own UI
    # at the top. Several overlays at one position stack instead of
    # overlapping: top goes down, bottom goes up, middle goes down.
    anchors = {"top": height * 0.11, "middle": height * 0.5, "bottom": height * 0.73}
    direction = {"top": 1, "middle": 1, "bottom": -1}
    used = {"top": 0.0, "middle": 0.0, "bottom": 0.0}
    events = []
    for i, ov in enumerate(overlays):
        start = max(0.0, total_s + ov.start) if ov.start < 0 else ov.start
        end = ov.end if ov.end is not None else total_s
        end = min(end, total_s) if total_s > 0 else end
        if end <= start:
            continue
        size = max(24, round(height * PRESETS[ov.preset][2]))
        # libass wraps long text; estimate the lines (~0.55 em per glyph)
        # so the next overlay clears all of them.
        lines = max(1, -(-round(len(ov.text) * 0.55 * size) // max(1, width - 120)))
        step = size * 1.25 * lines + size * 0.7
        y = anchors[ov.position] + direction[ov.position] * used[ov.position]
        used[ov.position] += step
        align = POSITIONS[ov.position]
        events.append(f"Dialogue: {2 + i},{_ass_time(start)},{_ass_time(end)},{ov.preset},,0,0,0,,"
                      f"{{\\an{align}\\pos({width // 2},{round(y)})}}{_escape(ov.text)}")
    path.write_text(header + "\n" + "\n".join(events) + "\n", encoding="utf-8")
    return path


def burn_overlays(src: Path, dst: Path, overlays: list[Overlay]) -> Optional[str]:
    """``src`` re-encoded into ``dst`` with ``overlays`` burned in (audio
    copied). Returns an error string, or None."""
    from flowboard.services.video_export import (
        _CLIP_TIMEOUT_S, _encode_args, _filter_path, _run, probe_clip,
    )

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return "ffmpeg_not_found"
    info = probe_clip(src)
    if info is None:
        return "unreadable clip"
    ass = dst.with_suffix(".overlays.ass")
    write_overlay_ass(overlays, ass, width=info.width, height=info.height, total_s=info.duration)
    cmd = [ffmpeg, "-y", "-i", str(src), "-vf", f"subtitles={_filter_path(ass)}",
           *_encode_args(ffmpeg), "-pix_fmt", "yuv420p", "-c:a", "copy",
           "-movflags", "+faststart", str(dst)]
    err = _run(cmd, _CLIP_TIMEOUT_S * 2)
    try:
        ass.unlink()
    except OSError:
        pass
    if err is None and (not dst.is_file() or dst.stat().st_size == 0):
        err = "no output"
    return err
