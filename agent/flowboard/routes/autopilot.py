"""🤖 Tự động đăng — fixed posting schedules for a Facebook Page (services/autopilot).

  GET    /api/autopilot/plans?channel_id=       the plans, each with its next slots and latest runs
  POST   /api/autopilot/plans                   {channel_id, name?, days, times, lead_minutes?, brief, series?,
                                                 product_mode?, product_ids?, ai?, fb_story?, enabled?}
  GET    /api/autopilot/plans/{id}
  PATCH  /api/autopilot/plans/{id}              any of the fields above (enabled: false = pause, cancels what is queued)
  DELETE /api/autopilot/plans/{id}
  POST   /api/autopilot/plans/{id}/prepare      write the next free slot's post now ("⚡ Soạn ngay bài kế tiếp")
  GET    /api/autopilot/runs?plan_id=&limit=    what each slot got (post, posted / skipped / error)
  GET    /api/autopilot/status                  which AIs can write here
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from flowboard.services import autopilot

router = APIRouter(prefix="/api/autopilot", tags=["autopilot"])


def _bad(exc: autopilot.AutopilotError) -> HTTPException:
    return HTTPException(400, str(exc))


@router.get("/status")
async def status() -> dict[str, Any]:
    from flowboard.services import claude_cli
    from flowboard.services.llm import gemini_api

    try:
        claude = bool(await claude_cli.is_available())
    except Exception:  # noqa: BLE001
        claude = False
    return {"ai": {"claude": claude, "gemini": gemini_api.configured()}, "lead_minutes": autopilot.LEAD_DEFAULT,
            "max_times": autopilot.MAX_TIMES}


@router.get("/plans")
def list_plans(channel_id: Optional[int] = Query(None)) -> list[dict[str, Any]]:
    return autopilot.list_plans(channel_id)


@router.post("/plans", status_code=201)
def create_plan(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return autopilot.create_plan(body)
    except autopilot.AutopilotError as exc:
        raise _bad(exc)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int) -> dict[str, Any]:
    try:
        return autopilot.get_plan(plan_id)
    except autopilot.AutopilotError as exc:
        raise HTTPException(404, str(exc))


@router.patch("/plans/{plan_id}")
def update_plan(plan_id: int, body: dict[str, Any]) -> dict[str, Any]:
    try:
        return autopilot.update_plan(plan_id, body)
    except autopilot.AutopilotError as exc:
        raise _bad(exc)


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int) -> dict[str, bool]:
    if not autopilot.delete_plan(plan_id):
        raise HTTPException(404, "Không thấy lịch tự động này.")
    return {"ok": True}


@router.post("/plans/{plan_id}/prepare")
async def prepare(plan_id: int) -> dict[str, Any]:
    try:
        return autopilot.prepare_next(plan_id)
    except autopilot.AutopilotError as exc:
        raise _bad(exc)


@router.get("/runs")
def runs(plan_id: Optional[int] = Query(None), limit: int = Query(30)) -> list[dict[str, Any]]:
    return autopilot.list_runs(plan_id, limit)
