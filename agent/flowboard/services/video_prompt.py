"""Shared touches applied to every video prompt at dispatch.

Veo leans toward slow motion on its own, and at the 24 fps it renders,
slow motion is what reads as choppy. So unless the prompt asks for it, the
clip is told to play at real-time speed. Lives here (not in the dialog) so
the chat agent, templates and pipeline runs get it too.
"""
from __future__ import annotations

import os
import re

REALTIME_CLAUSE = (
    "Motion plays at natural real-time speed, normal playback rate, "
    "no slow motion."
)

# The user explicitly asked for a speed effect; leave the prompt alone.
_SPEED_REQUEST = re.compile(
    r"slow[\s-]*mo(tion)?\b|slomo|slo-mo|time[\s-]*lapse|"
    r"\d+\s*x\s*speed|speed[\s-]*ramp|in slow",
    re.IGNORECASE,
)


def mentions_speed(prompt: str) -> bool:
    return bool(_SPEED_REQUEST.search(prompt or ""))


def ensure_realtime(prompt: str) -> str:
    """Append the real-time clause unless the prompt already sets a speed.

    ``FLOWBOARD_REALTIME_CLAUSE=0`` turns the clause off (A/B switch while
    diagnosing rejected renders)."""
    text = (prompt or "").strip()
    if not text or mentions_speed(text) or REALTIME_CLAUSE in text:
        return text
    if os.environ.get("FLOWBOARD_REALTIME_CLAUSE", "1").strip().lower() in ("0", "false", "off"):
        return text
    return f"{text}\n\n{REALTIME_CLAUSE}"
