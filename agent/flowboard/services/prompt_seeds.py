"""Sample prompts that ship with the app, put into the prompt library
("Prompt đã lưu") so a new user starts with something to reuse.

The list lives in ``prompt_seeds.json`` (data, not code). On start-up the
seeds are added once per ``version``: a sample the user deleted stays
deleted until the file's version goes up. ``POST /api/prompt-library/samples``
puts every missing sample back on request.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import AppSetting, SavedPrompt

logger = logging.getLogger(__name__)

SEEDS_FILE = Path(__file__).resolve().parent.parent / "prompt_seeds.json"
SETTING_KEY = "prompt_seeds_version"
#: Every sample carries this tag, so the library can tell them apart.
SAMPLE_TAG = "mẫu có sẵn"


@lru_cache(maxsize=1)
def load_seeds() -> dict[str, Any]:
    return json.loads(SEEDS_FILE.read_text(encoding="utf-8"))


def add_missing() -> int:
    """Insert every sample whose (kind, text) is not in the library yet."""
    seeds = load_seeds()["prompts"]
    added = 0
    with get_session() as s:
        have = {(r.kind, r.text) for r in s.exec(select(SavedPrompt)).all()}
        for p in seeds:
            if (p["kind"], p["text"]) in have:
                continue
            tags = [SAMPLE_TAG, *[t for t in p.get("tags", []) if t != SAMPLE_TAG]][:10]
            s.add(SavedPrompt(kind=p["kind"], title=p["title"], text=p["text"], tags=tags))
            added += 1
        s.commit()
    return added


def seed_on_start() -> int:
    """Add the samples once per seeds version. Returns how many were added."""
    version = str(load_seeds().get("version", 1))
    with get_session() as s:
        row = s.get(AppSetting, SETTING_KEY)
        if row is not None and row.value == version:
            return 0
    added = add_missing()
    with get_session() as s:
        row = s.get(AppSetting, SETTING_KEY)
        if row is None:
            s.add(AppSetting(key=SETTING_KEY, value=version))
        else:
            row.value = version
            s.add(row)
        s.commit()
    if added:
        logger.info("prompt library: added %d sample prompt(s) (seeds v%s)", added, version)
    return added
