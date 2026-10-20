"""Tiny CLI run with **pyvideotrans' own interpreter**, never flowboard's:
it imports ``vi_dub_erase`` (RapidOCR + LaMa, torch) from the pyvideotrans
checkout and talks to the agent through stdout lines.

    python video_clean_runner.py detect <src>
        → ``BANDS {"bands": [{"y0": 0.82, "y1": 0.9, "hits": 31}], "info": "…"}``
    python video_clean_runner.py erase <src> <dst> <bands-json>
        → ``PROGRESS <0-100>`` lines, then ``DONE``

``bands-json`` is the ``bands`` list above (fractions of the frame height).
The pyvideotrans root comes from ``FLOWBOARD_ERASE_ROOT`` (else the cwd);
it is put on ``sys.path`` and also holds ``models/lama/big-lama.pt``.
Exit code 0 on success, 2 on bad arguments, 1 on failure (message on stderr).
"""
from __future__ import annotations

import json
import os
import sys


def _root() -> str:
    return os.environ.get("FLOWBOARD_ERASE_ROOT") or os.getcwd()


def _load_erase(root: str):
    if root not in sys.path:
        sys.path.insert(0, root)
    import vi_dub_erase  # noqa: WPS433 — pyvideotrans module, torch inside

    return vi_dub_erase


def bands_to_fractions(bands: list) -> list[dict]:
    """pyvideotrans ``{top, size}`` (% of height) → ``{y0, y1}`` fractions."""
    out = []
    for b in bands or []:
        top, size = float(b.get("top", 0)), float(b.get("size", 0))
        y0 = max(0.0, min(1.0, top / 100.0))
        y1 = max(y0, min(1.0, (top + size) / 100.0))
        if y1 > y0:
            out.append({"y0": round(y0, 4), "y1": round(y1, 4), "hits": int(b.get("hits", 0) or 0)})
    return out


def bands_to_percent(bands: list) -> list[dict]:
    """``{y0, y1}`` fractions → pyvideotrans ``{top, size}`` percent."""
    out = []
    for b in bands or []:
        y0, y1 = float(b["y0"]), float(b["y1"])
        if not (0 <= y0 < y1 <= 1):
            raise ValueError(f"bad band {b!r}")
        out.append({"top": y0 * 100.0, "size": (y1 - y0) * 100.0})
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: video_clean_runner.py detect <src> | erase <src> <dst> <bands-json>", file=sys.stderr)
        return 2
    cmd, args = argv[0], argv[1:]
    root = _root()
    if cmd == "detect":
        if len(args) != 1:
            print("usage: detect <src>", file=sys.stderr)
            return 2
        erase = _load_erase(root)
        bands, info = erase.find_sub_bands(args[0])
        print("BANDS " + json.dumps({"bands": bands_to_fractions(bands), "info": info}, ensure_ascii=False), flush=True)
        return 0
    if cmd == "erase":
        if len(args) != 3:
            print("usage: erase <src> <dst> <bands-json>", file=sys.stderr)
            return 2
        src, dst, raw = args
        try:
            bands = bands_to_percent(json.loads(raw))
        except (ValueError, KeyError, TypeError) as exc:
            print(f"bad bands json: {exc}", file=sys.stderr)
            return 2
        if not bands:
            print("no bands", file=sys.stderr)
            return 2
        erase = _load_erase(root)
        last = -1
        for frac in erase.erase_video(src, dst, bands, root):
            pct = int(frac * 100)
            if pct != last:
                print(f"PROGRESS {pct}", flush=True)
                last = pct
        print("DONE", flush=True)
        return 0
    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001 — the agent reads stderr's tail
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
