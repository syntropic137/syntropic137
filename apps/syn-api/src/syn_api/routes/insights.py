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
from syn_api.types import (
    ContributionHeatmapResponse,
    GlobalCostResponse,
    GlobalOverviewResponse,
    HeatmapDayBucketResponse,
    SystemOverviewEntryResponse,
)

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
    """Get global cost breakdown across all executions.

    Uses ExecutionCostQueryService (TimescaleDB) for reads. See #532/#542.
    """
    from decimal import Decimal

    from syn_api._wiring import get_execution_cost_query

    await ensure_connected()

    query_svc = get_execution_cost_query()
    all_costs = await query_svc.list_all()

    total_cost = Decimal("0")
    total_input = 0
    total_output = 0
    cost_by_workflow: dict[str, Decimal] = {}
    cost_by_model: dict[str, Decimal] = {}

    for c in all_costs:
        total_cost += c.total_cost_usd
        total_input += c.input_tokens
        total_output += c.output_tokens

        if c.workflow_id:
            cost_by_workflow[c.workflow_id] = (
                cost_by_workflow.get(c.workflow_id, Decimal("0")) + c.total_cost_usd
            )
        for model, model_cost in c.cost_by_model.items():
            cost_by_model[model] = cost_by_model.get(model, Decimal("0")) + model_cost

    return {
        "system_id": "",
        "system_name": "global",
        "organization_id": "",
        "total_cost_usd": str(total_cost),
        "total_tokens": total_input + total_output,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "cost_by_repo": {},
        "cost_by_workflow": {k: str(v) for k, v in cost_by_workflow.items()},
        "cost_by_model": {k: str(v) for k, v in cost_by_model.items()},
        "execution_count": len(all_costs),
    }


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


@router.get("/overview", response_model=GlobalOverviewResponse)
async def get_global_overview_endpoint() -> GlobalOverviewResponse:
    """Get global overview of all systems and repos."""
    data = await get_global_overview()
    systems_raw = data.get("systems", [])
    return GlobalOverviewResponse(
        total_systems=data.get("total_systems", 0),
        total_repos=data.get("total_repos", 0),
        unassigned_repos=data.get("unassigned_repos", 0),
        total_active_executions=data.get("total_active_executions", 0),
        total_cost_usd=str(data.get("total_cost_usd", "0")),
        systems=[
            SystemOverviewEntryResponse(
                system_id=s.get("system_id", ""),
                system_name=s.get("system_name", ""),
                organization_id=s.get("organization_id", ""),
                organization_name=s.get("organization_name", ""),
                repo_count=s.get("repo_count", 0),
                overall_status=s.get("overall_status", "healthy"),
                active_executions=s.get("active_executions", 0),
                total_cost_usd=str(s.get("total_cost_usd", "0")),
            )
            for s in systems_raw
        ],
    )


@router.get("/cost", response_model=GlobalCostResponse)
async def get_global_cost_endpoint() -> GlobalCostResponse:
    """Get global cost breakdown across all repos."""
    data = await get_global_cost()
    return GlobalCostResponse(
        system_id=data.get("system_id", ""),
        system_name=data.get("system_name", ""),
        organization_id=data.get("organization_id", ""),
        total_cost_usd=str(data.get("total_cost_usd", "0")),
        total_tokens=data.get("total_tokens", 0),
        total_input_tokens=data.get("total_input_tokens", 0),
        total_output_tokens=data.get("total_output_tokens", 0),
        cost_by_repo=data.get("cost_by_repo", {}),
        cost_by_workflow=data.get("cost_by_workflow", {}),
        cost_by_model=data.get("cost_by_model", {}),
        execution_count=data.get("execution_count", 0),
    )


@router.get("/contribution-heatmap", response_model=ContributionHeatmapResponse)
async def get_contribution_heatmap_endpoint(
    organization_id: str | None = Query(None),
    system_id: str | None = Query(None),
    repo_id: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    metric: str = Query("sessions"),
) -> ContributionHeatmapResponse | JSONResponse:
    """Get daily contribution heatmap data."""
    try:
        data = await get_contribution_heatmap(
            organization_id=organization_id,
            system_id=system_id,
            repo_id=repo_id,
            start_date=start_date,
            end_date=end_date,
            metric=metric,
        )
        days_raw = data.get("days", [])
        return ContributionHeatmapResponse(
            metric=data.get("metric", "sessions"),
            start_date=data.get("start_date", ""),
            end_date=data.get("end_date", ""),
            total=data.get("total", 0.0),
            days=[
                HeatmapDayBucketResponse(
                    date=d.get("date", ""),
                    count=d.get("count", 0.0),
                    breakdown=d.get("breakdown", {}),
                )
                for d in days_raw
            ],
            filter=data.get("filter", {}),
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
