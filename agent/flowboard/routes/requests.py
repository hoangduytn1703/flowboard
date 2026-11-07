import threading
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Node, Request
from flowboard.worker.processor import get_worker

router = APIRouter(prefix="/api/requests", tags=["requests"])


class RequestCreate(BaseModel):
    node_id: Optional[int] = None
    type: str = Field(min_length=1, max_length=40)
    params: dict[str, Any] = Field(default_factory=dict)


#: One export at a time per node: a double click on "Ghép" sent two identical exports 80 ms apart and the second
#: redid the whole join (~10 min with 60 fps) while the page waited on it (7/11). The same export asked again while
#: one is queued / running gets that one back.
_ONE_AT_A_TIME = {"export_video"}
_create_lock = threading.Lock()


@router.post("")
def create_request(body: RequestCreate):
    if body.type in _ONE_AT_A_TIME and body.node_id is not None:
        with _create_lock:  # the check and the insert together, or two requests 80 ms apart both pass the check
            return _create(body)
    return _create(body)


def _create(body: RequestCreate):
    with get_session() as s:
        if body.node_id is not None and not s.get(Node, body.node_id):
            raise HTTPException(404, "node not found")
        if body.type in _ONE_AT_A_TIME and body.node_id is not None:
            same = s.exec(
                select(Request).where(Request.node_id == body.node_id, Request.type == body.type,
                                      Request.status.in_(("queued", "running")))  # type: ignore[union-attr]
            ).all()
            for row in same:
                if (row.params or {}) == dict(body.params):
                    return row
        req = Request(
            node_id=body.node_id,
            type=body.type,
            params=dict(body.params),
            status="queued",
        )
        s.add(req)
        s.commit()
        s.refresh(req)
        rid = req.id
        row = req

    assert rid is not None
    get_worker().enqueue(rid)
    return row


@router.get("/{request_id}")
def get_request(request_id: int):
    with get_session() as s:
        req = s.get(Request, request_id)
        if req is None:
            raise HTTPException(404, "request not found")
        return req


@router.post("/{request_id}/cancel")
def cancel_request(request_id: int):
    """Cancel a ``queued`` or ``running`` request.

    Cancellation is cooperative on the running side: we can't abort an
    in-flight HTTP call to Flow, but the long-running handlers (notably
    ``_handle_gen_video``) re-read the row between polls and bail out
    when they see ``status == 'canceled'``. The worker's ``_process_one``
    also re-checks the row before its final stamp, so the canceled
    status is never overwritten by a late-arriving result.
    """
    with get_session() as s:
        req = s.get(Request, request_id)
        if req is None:
            raise HTTPException(404, "request not found")
        if req.status not in ("queued", "running"):
            raise HTTPException(
                409,
                f"only queued or running requests can be canceled (status={req.status})",
            )
        req.status = "canceled"
        req.error = "canceled"
        req.finished_at = datetime.now(timezone.utc)
        s.add(req)
        # Clear the node's in-flight stamp here rather than in the worker.
        # The worker mirrors Node.status on every transition it makes, but
        # it deliberately leaves canceled rows alone (a late-arriving result
        # must not resurrect them), so a cancel is the one transition out of
        # `running` it never sees. Without this the card would sit on the
        # processing UI forever after a reload, with no request left to
        # poll. Mirrors what the frontend poll does on `canceled`: back to
        # idle, keeping whatever the node was showing before.
        if req.node_id is not None:
            node = s.get(Node, req.node_id)
            if node is not None and node.status in ("queued", "running"):
                node.status = "idle"
                s.add(node)
        s.commit()
        s.refresh(req)
        return req
