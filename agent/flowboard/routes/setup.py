"""First-run guide: what is ready, look again, open Flow. See services/setup_status.py."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from flowboard.services import setup_status

router = APIRouter(prefix="/api/setup", tags=["setup"])


class CheckBody(BaseModel):
    #: Pin the project the Flow tab has open even when another one is pinned.
    use_tab_project: bool = False
    #: The tab's account does not own the pinned project: pin that account's project instead.
    use_account_project: bool = False
    #: … or let that account use the pinned project (the warning was wrong).
    keep_project: bool = False


@router.get("/status")
def get_status() -> dict:
    return setup_status.status()


@router.post("/check")
async def check(body: Optional[CheckBody] = None) -> dict:
    body = body or CheckBody()
    return await setup_status.check(use_tab_project=body.use_tab_project,
                                    use_account_project=body.use_account_project, keep_project=body.keep_project)


@router.post("/open-flow")
async def open_flow() -> dict:
    return {"ok": await setup_status.open_flow()}
