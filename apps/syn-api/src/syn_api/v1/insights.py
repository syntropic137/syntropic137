"""Insight operations — global overview and cost queries."""

from __future__ import annotations

from typing import Any

from syn_api._wiring import ensure_connected


async def get_global_overview() -> dict[str, Any]:
    """Get global overview of all systems and repos."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.organization.domain.queries.get_global_overview import (
        GetGlobalOverviewQuery,
    )
    from syn_domain.contexts.organization.slices.global_overview.handler import (
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
    from syn_domain.contexts.organization.slices.global_cost.handler import (
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
