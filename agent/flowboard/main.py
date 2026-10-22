import asyncio
import os
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Request as FastAPIRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from flowboard.config import EXTENSION_WS_PORT, WS_HOST
from flowboard.db import get_session, init_db
from flowboard.db.models import Node, Request
from flowboard.routes import activity, auth, boards, chat, edges, flow_debug, flow_projects, llm, media, nodes, plans, projects, prompt, templates, upload, vision
from flowboard.routes import provider_jobs as provider_jobs_route
from flowboard.routes import drama as drama_route
from flowboard.routes import export_extras as export_extras_route
from flowboard.routes import account as account_route
from flowboard.routes import cloud as cloud_route
from flowboard import accounts
from flowboard.routes import history as history_route
from flowboard.routes import prompt_library as prompt_library_route
from flowboard.routes import video_clean as video_clean_route
from flowboard.routes import image_providers as image_providers_route
from flowboard.routes import products as products_route
from flowboard.routes import reference_video as reference_video_route
from flowboard.routes import references as references_route
from flowboard.routes import requests as requests_route
from flowboard.routes import storyboard as storyboard_route
from flowboard.services.flow_client import flow_client
from flowboard.services.ws_server import run_ws_server
from flowboard.worker.processor import get_worker

# Guard rail: the dedicated WS server is unauthenticated and would expose the
# callback secret to any process that can reach it. Refuse to boot if someone
# overrode WS_HOST to a non-loopback address.
if WS_HOST not in ("127.0.0.1", "localhost", "::1"):
    raise RuntimeError(
        f"FLOWBOARD_WS_HOST must be loopback (got {WS_HOST!r}); the extension WS "
        "is unauthenticated by design and must not be network-reachable."
    )

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def _recover_orphan_running_requests() -> int:
    """Fail every request a restart orphaned, so nothing is left to poll.

    Both in-flight statuses are orphaned by a restart, for different
    reasons. A `running` row lost the handler that was driving it. A
    `queued` row lost its *consumer*: the worker's queue is an in-process
    ``asyncio.Queue`` filled only by ``enqueue()`` at dispatch time, and
    nothing replays it at boot — so a queued row that survives a restart
    has no path to ever being picked up. `ACTIVE_REQUEST_STATUSES` in
    routes/boards.py counts both as in-flight, which means a reloaded
    board would hand those dead rows to the browser and spin on them
    forever.

    Deliberately NOT re-enqueued. Every generation type here dispatches a
    paid Flow job, and we cannot tell from the row whether the dispatch
    already went out before the process died; replaying it risks
    double-firing. Failing loud and letting the user re-run is the safe
    direction.

    The two get distinct `error` strings so the activity feed can tell
    "never started" from "died mid-run" — only the latter may have burned
    credits upstream.
    """
    from datetime import datetime, timezone
    from sqlmodel import select as _select

    touched = 0
    with get_session() as s:
        rows = s.exec(
            _select(Request).where(Request.status.in_(("queued", "running")))
        ).all()
        node_ids = set()
        for r in rows:
            r.error = (
                "agent_restart_never_started"
                if r.status == "queued"
                else "agent_restart_lost"
            )
            r.status = "failed"
            r.finished_at = datetime.now(timezone.utc)
            s.add(r)
            if r.node_id is not None:
                node_ids.add(r.node_id)
            touched += 1
        # The worker stamps Node.status='running' at dispatch so a reloaded
        # board still renders the card as busy. Nobody is going to finish
        # these now, so clear that stamp in the same pass — otherwise the
        # node spins forever with no in-flight request left to poll.
        if node_ids:
            for n in s.exec(_select(Node).where(Node.id.in_(node_ids))).all():
                if n.status in ("queued", "running"):
                    n.status = "error"
                    s.add(n)
        if touched:
            s.commit()
    return touched


def _prepare_account_data() -> None:
    """Runs on the data store of the account that just became active (and
    once at start-up when login is off): orphan jobs, media bookkeeping,
    sample prompts."""
    recovered = _recover_orphan_running_requests()
    if recovered:
        logger.info("recovered %d orphan in-flight request(s) → failed", recovered)
    # Media generated before per-project bookkeeping existed would otherwise
    # be re-uploaded into the project it already lives in on first reuse.
    from flowboard.services.media_project_sync import backfill_identity_mappings
    backfill_identity_mappings()
    # Sample prompts for "Prompt đã lưu", once per seeds version.
    from flowboard.services.prompt_seeds import seed_on_start
    try:
        seed_on_start()
    except Exception as exc:  # noqa: BLE001 — samples are a nicety, never block start-up
        logger.warning("prompt seeds skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Login + per-account data: with FLOWBOARD_AUTH=off this opens the
    # default DB right away; otherwise the data store opens at first login.
    if _prepare_account_data not in accounts.after_activate:
        accounts.after_activate.append(_prepare_account_data)
    accounts.startup()
    from flowboard.services import file_store
    file_store.install_hooks()
    if not accounts.auth_enabled():
        file_store.reconcile_in_background()
    worker = get_worker()
    ws_task = asyncio.create_task(run_ws_server(), name="ext-ws-server")
    worker_task = asyncio.create_task(worker.start(), name="request-worker")
    logger.info("flowboard agent started (ws:%d + worker)", EXTENSION_WS_PORT)
    try:
        yield
    finally:
        worker.request_shutdown()
        try:
            await asyncio.wait_for(worker.drain(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("worker drain timed out")
        for t in (ws_task, worker_task):
            t.cancel()
        await asyncio.gather(ws_task, worker_task, return_exceptions=True)
        logger.info("flowboard agent stopped")


app = FastAPI(title="Flowboard Agent", version="0.0.2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#: Reachable without a login: logging in itself, health, and the extension's
#: callback (authenticated by its own secret).
OPEN_PATHS = {"/api/account/login", "/api/account/me", "/api/account/register", "/api/health", "/api/ext/callback"}


@app.middleware("http")
async def _require_login(request: FastAPIRequest, call_next):
    path = request.url.path
    if accounts.auth_enabled() and (path.startswith("/api/") or path.startswith("/media/")) and path not in OPEN_PATHS:
        user = accounts.user_from_request(request)
        if user is None:
            return JSONResponse({"detail": "Chưa đăng nhập"}, status_code=401)
        try:
            await asyncio.to_thread(accounts.activate, user)
        except accounts.AccountBusy as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409)
    return await call_next(request)


app.include_router(account_route.router)
app.include_router(cloud_route.router)
app.include_router(boards.router)
app.include_router(templates.router)
app.include_router(nodes.router)
app.include_router(storyboard_route.router)
app.include_router(edges.router)
app.include_router(chat.router)
app.include_router(projects.router)
app.include_router(flow_projects.router)
app.include_router(flow_debug.router)
app.include_router(references_route.router)
app.include_router(products_route.router)
# Drama clips are parked (FLOWBOARD_DRAMA=1 re-enables the API and the UI card).
if os.getenv("FLOWBOARD_DRAMA") == "1":
    app.include_router(drama_route.router)
app.include_router(reference_video_route.router)
app.include_router(export_extras_route.router)
app.include_router(requests_route.router)
app.include_router(media.bytes_router)
app.include_router(media.api_router)
app.include_router(upload.router)
app.include_router(plans.router)
app.include_router(vision.router)
app.include_router(prompt.router)
app.include_router(auth.router)
app.include_router(llm.router)
app.include_router(image_providers_route.router)
app.include_router(history_route.router)
app.include_router(prompt_library_route.router)
app.include_router(video_clean_route.router)
app.include_router(activity.router)
app.include_router(provider_jobs_route.router)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "extension_connected": flow_client.connected,
        "ws_stats": flow_client.ws_stats,
    }


@app.post("/api/ext/callback")
async def ext_callback(
    body: FastAPIRequest,
    x_callback_secret: str | None = Header(default=None, alias="X-Callback-Secret"),
) -> dict:
    """HTTP callback for the extension to deliver API responses."""
    if not x_callback_secret or not hmac.compare_digest(
        x_callback_secret, flow_client.callback_secret
    ):
        raise HTTPException(status_code=401, detail="invalid callback secret")

    try:
        payload = await body.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json body")

    if not isinstance(payload, dict) or "id" not in payload:
        raise HTTPException(status_code=400, detail="missing id")

    matched = flow_client.resolve_callback(payload)
    return {"ok": matched}
