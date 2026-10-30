"""A picture for "📲 Thêm vào tin" when the post is words only.

The Facebook app makes text stories (words on a coloured background), but the
Page Stories API takes a photo or a video only — so a post with no picture
gets one drawn here: 1080×1920, a soft two-colour gradient like Facebook's
text stories, the opening of the post in big white letters, the Page's name
small at the bottom. Emoji are left out (the system fonts draw them as boxes).
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
MAX_CHARS = 220          # a story is read in a few seconds: the opening of the post only
ENOUGH_CHARS = 60        # paragraphs are taken from the top until there is at least this much to read
SIDE = 110               # left / right margin
TEXT_TOP, TEXT_BOTTOM = 260, 1600
SIZES = (88, 80, 72, 66, 60, 54, 48, 44)

# (top, bottom) colours — the kind of backgrounds Facebook offers for text stories
GRADIENTS = (
    ((52, 88, 235), (155, 70, 225)),     # blue → violet
    ((255, 112, 67), (233, 30, 99)),     # orange → pink
    ((0, 150, 136), (46, 125, 50)),      # teal → green
    ((40, 44, 58), (17, 19, 26)),        # night
    ((233, 30, 99), (103, 58, 183)),     # pink → purple
    ((255, 152, 0), (230, 81, 0)),       # amber → deep orange
)

_FONT_FILES = (
    "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
)
_SMALL_FONT_FILES = (
    "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
)

_HASHTAG = re.compile(r"(?<!\w)#[^\s#]+")
_URL = re.compile(r"https?://\S+|www\.\S+")


def _font_file(files: tuple[str, ...]) -> Optional[str]:
    own = os.environ.get("FLOWBOARD_STORY_FONT", "").strip()
    for f in ((own,) if own else ()) + files:
        if f and Path(f).is_file():
            return f
    return None


def _font(size: int, *, small: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    f = _font_file(_SMALL_FONT_FILES if small else _FONT_FILES)
    return ImageFont.truetype(f, size) if f else ImageFont.load_default(size)


def _drawable(ch: str) -> str:
    """Latin (Vietnamese included) and common punctuation; emoji, symbols and joiners go."""
    o = ord(ch)
    if o < 0x2000:
        return ch
    if o <= 0x200A:
        return " "
    if 0x2010 <= o <= 0x2027 or 0x2030 <= o <= 0x205E:
        return ch
    return ""


def card_text(message: str) -> str:
    """The opening paragraph(s) of the post — enough to read (:data:`ENOUGH_CHARS`) — without hashtags, links and
    emoji, cut at a word near :data:`MAX_CHARS`."""
    text = _URL.sub("", _HASHTAG.sub("", message or ""))
    text = "".join(_drawable(c) for c in text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    paras: list[str] = []
    for ln in lines:
        if ln:
            paras.append(ln)
        elif paras and paras[-1] != "":
            if sum(len(x) for x in paras) >= ENOUGH_CHARS:
                break
            paras.append("")
    out = "\n".join(paras).strip()
    if len(out) > MAX_CHARS:
        cut = out[:MAX_CHARS]
        cut = cut[: max(cut.rfind(" "), cut.rfind("\n"), MAX_CHARS // 2)].rstrip(" ,;:-–—\n")
        out = cut + "…"
    return out


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        line = ""
        for word in para.split(" "):
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def render(message: str, out: Path, *, page_name: str = "") -> Path:
    """Draw the card for ``message`` into ``out`` (JPEG) and return it."""
    text = card_text(message)
    if not text:
        raise ValueError("Bài không có chữ để làm ảnh tin.")
    top, bottom = GRADIENTS[int(hashlib.md5(text.encode()).hexdigest(), 16) % len(GRADIENTS)]
    img = Image.new("RGB", (W, H))
    px = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        px.line([(0, y), (W, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))

    draw = ImageDraw.Draw(img)
    shadow = tuple(round((a + b) / 2 * 0.55) for a, b in zip(top, bottom))
    width = W - 2 * SIDE
    for size in SIZES:
        font = _font(size)
        lines = _wrap(draw, text, font, width)
        line_h = round(size * 1.38)
        block = sum(line_h if ln else line_h // 2 for ln in lines)
        if block <= TEXT_BOTTOM - TEXT_TOP:
            break
    y = TEXT_TOP + max(0, (TEXT_BOTTOM - TEXT_TOP - block) // 2)
    for ln in lines:
        if ln:
            w = draw.textlength(ln, font=font)
            x = (W - w) / 2
            draw.text((x + 2, y + 3), ln, font=font, fill=shadow)   # a soft shadow keeps light gradients readable
            draw.text((x, y), ln, font=font, fill=(255, 255, 255))
            y += line_h
        else:
            y += line_h // 2

    name = "".join(_drawable(c) for c in (page_name or "")).strip()
    if name:
        small = _font(40, small=True)
        w = draw.textlength(name, font=small)
        draw.text(((W - w) / 2, H - 190), name, font=small, fill=(255, 255, 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=90)
    return out


def render_temp(message: str, *, page_name: str = "") -> Path:
    """:func:`render` into a fresh temp folder (the caller posts it once)."""
    return render(message, Path(tempfile.mkdtemp(prefix="story-card-")) / "tin.jpg", page_name=page_name)
