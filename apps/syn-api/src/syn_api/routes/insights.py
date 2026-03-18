"""Global insight API endpoints — thin wrapper over v1."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import date

from fastapi import APIRouter, Query
from starlette.responses import JSONResponse

import syn_api.v1.insights as insight_ops

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/overview")
async def get_global_overview() -> dict[str, Any]:
    """Get global overview of all systems and repos."""
    return await insight_ops.get_global_overview()


@router.get("/cost")
async def get_global_cost() -> dict[str, Any]:
    """Get global cost breakdown across all repos."""
    return await insight_ops.get_global_cost()


@router.get("/contribution-heatmap")
async def get_contribution_heatmap(
    organization_id: str | None = Query(None),
    system_id: str | None = Query(None),
    repo_id: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    metric: str = Query("sessions"),
) -> dict[str, Any]:
    """Get daily contribution heatmap data."""
    try:
        return await insight_ops.get_contribution_heatmap(
            organization_id=organization_id,
            system_id=system_id,
            repo_id=repo_id,
            start_date=start_date,
            end_date=end_date,
            metric=metric,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
