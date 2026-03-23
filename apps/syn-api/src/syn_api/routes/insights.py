"""Insight API endpoints and service operations.

Provides global overview, cost breakdown, and contribution heatmap queries.
"""

from __future__ import annotations

import logging
from datetime import date  # noqa: TC003 — needed at runtime for FastAPI Query params
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query
from starlette.responses import JSONResponse

from syn_api._wiring import ensure_connected

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights", tags=["insights"])


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def get_global_overview(
    auth: AuthContext | None = None,  # noqa: ARG001
) -> dict[str, Any]:
    """Get global overview of all systems and repos."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.organization.domain.queries.get_global_overview import (
        GetGlobalOverviewQuery,
    )
    from syn_domain.contexts.organization.slices.global_overview.GetGlobalOverviewHandler import (
        GetGlobalOverviewHandler,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import (
        get_repo_projection,
    )
    from syn_domain.contexts.organization.slices.list_systems.projection import (
        get_system_projection,
    )

    await ensure_connected()

    handler = GetGlobalOverviewHandler(
        store=get_projection_store(),
        system_projection=get_system_projection(),
        repo_projection=get_repo_projection(),
    )
    result = await handler.handle(GetGlobalOverviewQuery())
    return dict(result.to_dict())


async def get_global_cost(
    auth: AuthContext | None = None,  # noqa: ARG001
) -> dict[str, Any]:
    """Get global cost breakdown across all repos."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.organization.domain.queries.get_global_cost import (
        GetGlobalCostQuery,
    )
    from syn_domain.contexts.organization.slices.global_cost.GetGlobalCostHandler import (
        GetGlobalCostHandler,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import (
        get_repo_projection,
    )

    await ensure_connected()

    handler = GetGlobalCostHandler(
        store=get_projection_store(),
        repo_projection=get_repo_projection(),
    )
    result = await handler.handle(GetGlobalCostQuery())
    return dict(result.to_dict())


async def get_contribution_heatmap(
    organization_id: str | None = None,
    system_id: str | None = None,
    repo_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    metric: str = "sessions",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> dict[str, Any]:
    """Get daily contribution heatmap data."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_api._wiring import get_event_store_instance
    from syn_domain.contexts.organization.domain.queries.get_contribution_heatmap import (
        GetContributionHeatmapQuery,
    )
    from syn_domain.contexts.organization.slices.contribution_heatmap.GetContributionHeatmapHandler import (
        GetContributionHeatmapHandler,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import (
        get_repo_projection,
    )

    await ensure_connected()

    event_store = get_event_store_instance()
    pool = event_store.pool

    query_kwargs: dict[str, Any] = {
        "organization_id": organization_id,
        "system_id": system_id,
        "repo_id": repo_id,
        "metric": metric,
    }
    if start_date is not None:
        query_kwargs["start_date"] = start_date
    if end_date is not None:
        query_kwargs["end_date"] = end_date

    handler = GetContributionHeatmapHandler(
        pool=pool,
        store=get_projection_store(),
        repo_projection=get_repo_projection(),
    )
    result = await handler.handle(GetContributionHeatmapQuery(**query_kwargs))
    return dict(result.to_dict())


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.get("/overview")
async def get_global_overview_endpoint() -> dict[str, Any]:
    """Get global overview of all systems and repos."""
    return await get_global_overview()


@router.get("/cost")
async def get_global_cost_endpoint() -> dict[str, Any]:
    """Get global cost breakdown across all repos."""
    return await get_global_cost()


@router.get("/contribution-heatmap", response_model=None)
async def get_contribution_heatmap_endpoint(
    organization_id: str | None = Query(None),
    system_id: str | None = Query(None),
    repo_id: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    metric: str = Query("sessions"),
) -> dict[str, Any] | JSONResponse:
    """Get daily contribution heatmap data."""
    try:
        return await get_contribution_heatmap(
            organization_id=organization_id,
            system_id=system_id,
            repo_id=repo_id,
            start_date=start_date,
            end_date=end_date,
            metric=metric,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
