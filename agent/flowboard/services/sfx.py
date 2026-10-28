"""Short sound effects for the key moments of a dubbed video ("✨ Nhấn chữ
quan trọng"): a built-in set synthesised once with ffmpeg (no files in the
repo), or the sounds learned from the user's own CapCut (``capcut_auto``).

``pieces(points, set)`` hands the dubbing renderer ``[(at, wav, seconds)]``,
the sounds taken in turn so two alike never follow each other.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from flowboard import config

BUILTIN_SET = "builtin"
CAPCUT_SET = "capcut"
#: name → (lavfi source, seconds): small, dry, mono 48 kHz
_BUILTIN: dict[str, tuple[str, float]] = {
    "pop": ("aevalsrc='0.9*sin(2*PI*t*(1400-5000*t))*exp(-t*30)':s=48000:d=0.18", 0.18),
    "whoosh": ("anoisesrc=d=0.45:c=pink:r=48000:a=1,highpass=f=500,lowpass=f=3000,volume=14dB,alimiter=limit=0.85,"
               "afade=t=in:d=0.12,afade=t=out:st=0.2:d=0.25", 0.45),
    "ding": ("aevalsrc='0.6*(sin(2*PI*1568*t)+0.5*sin(2*PI*3136*t))*exp(-t*5)':s=48000:d=0.9", 0.9),
    "click": ("aevalsrc='0.9*sin(2*PI*t*2600)*exp(-t*90)':s=48000:d=0.08", 0.08),
}
MAX_DUR_S = 2.5


def _dir() -> Path:
    return Path(config.STORAGE_DIR) / "sfx"


def builtin_sounds() -> list[dict[str, Any]]:
    """The built-in set, synthesised on first use: ``[{id, label, path, duration}]``."""
    ffmpeg = shutil.which("ffmpeg")
    out = []
    for name, (src, dur) in _BUILTIN.items():
        path = _dir() / f"{name}.wav"
        if not path.is_file() and ffmpeg:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", src, "-ac", "1", "-ar", "48000",
                                "-c:a", "pcm_s16le", str(path)], capture_output=True, timeout=60, check=False)
            except (OSError, subprocess.SubprocessError):
                continue
        if path.is_file():
            out.append({"id": f"{BUILTIN_SET}:{name}", "label": name, "path": path, "duration": dur})
    return out


def capcut_sounds() -> list[dict[str, Any]]:
    """The sound effects learned from the user's CapCut (files in its cache), when any."""
    try:
        from flowboard.services import capcut_auto

        kho = capcut_auto.load_styles() or {}
    except Exception:  # noqa: BLE001 — CapCut is optional
        return []
    out = []
    for sid, e in (kho.get("sounds") or {}).items():
        try:
            path = Path(e["tpl"]["material"][1]["path"])
        except (KeyError, TypeError, IndexError):
            continue
        if path.is_file():
            out.append({"id": f"{CAPCUT_SET}:{sid}", "label": str(e.get("label") or path.stem)[:40], "path": path,
                        "duration": float(e.get("duration") or 1.0)})
    return out


def sets() -> list[dict[str, Any]]:
    """What the UI can offer: ``[{key, label, count}]``."""
    out = [{"key": BUILTIN_SET, "label": "Tiếng có sẵn (pop, whoosh, ding, click)", "count": len(builtin_sounds())}]
    cc = capcut_sounds()
    if cc:
        out.append({"key": CAPCUT_SET, "label": f"Tiếng đã học từ CapCut ({len(cc)})", "count": len(cc)})
    return out


def sounds_of(set_key: Optional[str]) -> list[dict[str, Any]]:
    if set_key == CAPCUT_SET:
        cc = capcut_sounds()
        if cc:
            return cc
    return builtin_sounds()


def pieces(points: list[dict[str, Any]], set_key: Optional[str]) -> list[tuple[float, Path, float]]:
    """One sound per point, in turn, never the same one twice running; long sounds are cut to MAX_DUR_S."""
    snd = sounds_of(set_key)
    if not snd:
        return []
    out: list[tuple[float, Path, float]] = []
    recent: list[int] = []
    for p in points:
        order = sorted(range(len(snd)), key=lambda i: (recent.count(i), i))
        fresh = [i for i in order if i not in recent[-max(1, min(3, len(snd) - 1)):]] if len(snd) > 1 else order
        k = (fresh or order)[0]
        recent.append(k)
        out.append((float(p["at"]), snd[k]["path"], min(MAX_DUR_S, float(snd[k]["duration"]))))
    return out
