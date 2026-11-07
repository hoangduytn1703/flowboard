"""The built web UI, served by the agent itself — the desktop app has no Vite.

``FLOWBOARD_WEB_DIR`` points at a ``vite build`` output (the app passes resources/web; ``frontend/dist``
works from the repo too). Every GET that no API route took gets a file from there, or ``index.html`` so the
React router can draw the page (``/clips/12/export`` after F5). ``/api/*`` and ``/media/*`` never fall
through to it. Mounted last in main.py so it can never shadow a real route.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from flowboard.services import app_env

logger = logging.getLogger(__name__)

#: hashed bundles never change under one name; index.html must always be fresh (it names the bundles)
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
_FRESH = {"Cache-Control": "no-cache"}


def mount(app: FastAPI) -> bool:
    root = app_env.web_dir()
    if root is None:
        return False
    base = root.resolve()
    index = base / "index.html"
    logger.info("web UI served from %s", base)

    async def spa(path: str = "") -> FileResponse:
        if path in ("api", "media") or path.startswith(("api/", "media/")):
            raise HTTPException(404, "Not Found")
        if path:
            target = (base / path).resolve()
            if target.is_file() and base in target.parents:
                return FileResponse(target, headers=_IMMUTABLE if path.startswith("assets/") else _FRESH)
        return FileResponse(index, headers=_FRESH)

    app.add_api_route("/", spa, methods=["GET"], include_in_schema=False)
    app.add_api_route("/{path:path}", spa, methods=["GET"], include_in_schema=False)
    return True
