"""Read-only diagnostics for a Flow video operation.

``GET /api/flow/operations/{operation_id}/lookup`` runs the two calls the
worker's poll makes — the operation status and the project-listing window —
and returns what each answered, so a clip that keeps polling as "[5]" can be
told apart from a lookup that cannot read the listing. Spends no credits.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from flowboard.services import flow_batch as fb
from flowboard.services.flow_client import flow_client
from flowboard.services.flow_project import effective_project_id

router = APIRouter(prefix="/api/flow/operations", tags=["flow-debug"])


@router.get("/media/{media_id}/urls")
async def media_urls(media_id: str) -> dict:
    """What the media record (as29s) answers for one media id."""
    res = await flow_client.batch_rpc(fb.RPC_MEDIA, fb.media_request(media_id), timeout=60.0)
    out: dict = {"media_id": media_id, "status": res.get("status"), "error": res.get("error"),
                 "body": str(res.get("data") or "")[:800]}
    try:
        urls = fb.read_media_urls(fb.first_payload(res.get("data") or "", fb.RPC_MEDIA), media_id)
        out["urls"] = {"video": urls.video, "image": urls.image}
    except Exception as exc:  # noqa: BLE001
        out["parse_error"] = f"{type(exc).__name__}: {exc}"
    return out


@router.get("/inflight")
async def inflight() -> dict:
    """Operations the SDK is (or was) polling this process: id → project, rounds."""
    from flowboard.services.flow_sdk import get_flow_sdk

    sdk = get_flow_sdk()
    return {
        "operations": {op: {"project_id": pid,
                            "rounds": sdk._operation_polls.get(op, 0),
                            "media_id": sdk._operation_media.get(op)}
                       for op, pid in sdk._operation_projects.items()},
    }


@router.get("/listing")
async def listing(project_id: Optional[str] = Query(None), head: int = Query(3000, le=20000)) -> dict:
    """The raw project listing (Zzl0ze), unfiltered, for shape inspection."""
    pid = project_id or effective_project_id()
    res = await flow_client.batch_rpc(fb.RPC_PROJECT_MEDIA, fb.project_media_request(pid), timeout=120.0)
    raw = str(res.get("data") or "")
    return {"project_id": pid, "status": res.get("status"), "error": res.get("error"),
            "length": len(raw), "video_urls": raw.count("/video/"), "image_urls": raw.count("/image/"),
            "head": raw[:head], "tail": raw[-1500:]}


@router.get("/{operation_id}/lookup")
async def lookup_operation(operation_id: str, project_id: Optional[str] = Query(None)) -> dict:
    pid = project_id or effective_project_id()
    out: dict = {"operation_id": operation_id, "project_id": pid}

    poll = await flow_client.batch_rpc(
        fb.RPC_OPERATION, fb.operation_request(operation_id), timeout=60.0
    )
    out["poll"] = {"status": poll.get("status"), "error": poll.get("error"),
                   "body": str(poll.get("data") or "")[:600]}
    try:
        op = fb.read_operation(fb.first_payload(poll.get("data") or "", fb.RPC_OPERATION))
        out["poll"]["parsed"] = {"done": op.done, "error": op.error,
                                 "project_id": op.project_id, "complained": op.complained}
    except Exception as exc:  # noqa: BLE001 — diagnostics report, never raise
        out["poll"]["parse_error"] = f"{type(exc).__name__}: {exc}"

    if pid:
        listing = await flow_client.batch_rpc(
            fb.RPC_PROJECT_MEDIA, fb.project_media_request(pid),
            match=operation_id, timeout=120.0,
        )
        raw = str(listing.get("data") or "")
        out["listing"] = {
            "status": listing.get("status"), "error": listing.get("error"),
            "matched": listing.get("matched"), "window_len": len(raw),
            "window": raw[:1200],
            "media_id": fb.find_media_id_in_text(raw, operation_id),
        }
    return out
