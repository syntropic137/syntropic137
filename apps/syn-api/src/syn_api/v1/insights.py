"""Insight operations — global overview, cost, and heatmap queries."""

from __future__ import annotations

from datetime import date
from typing import Any

from syn_api._wiring import ensure_connected


async def get_global_overview() -> dict[str, Any]:
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


async def get_global_cost() -> dict[str, Any]:
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
