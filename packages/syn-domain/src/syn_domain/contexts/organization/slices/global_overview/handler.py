"""Handler for GetGlobalOverviewQuery.

Lazy handler: aggregates health and cost across all systems from
in-memory projections and projection stores.
"""

from decimal import Decimal
from typing import Any

from syn_domain.contexts.organization.domain.queries.get_global_overview import (
    GetGlobalOverviewQuery,
)
from syn_domain.contexts.organization.domain.read_models.global_overview import (
    GlobalOverview,
    SystemOverviewEntry,
)
from syn_domain.contexts.organization.domain.read_models.repo_cost import RepoCost
from syn_domain.contexts.organization.domain.read_models.repo_health import RepoHealth


class GetGlobalOverviewHandler:
    """Query handler: get global overview of all systems and repos."""

    def __init__(
        self,
        store: Any,
        system_projection: Any,
        repo_projection: Any,
    ) -> None:
        self._store = store
        self._system_projection = system_projection
        self._repo_projection = repo_projection

    async def handle(self, query: GetGlobalOverviewQuery) -> GlobalOverview:  # noqa: ARG002
        """Handle GetGlobalOverviewQuery."""
        systems = self._system_projection.list_all()
        all_repos = self._repo_projection.list_all()
        unassigned = self._repo_projection.list_all(unassigned=True)

        total_cost = Decimal("0")
        total_active = 0
        entries: list[SystemOverviewEntry] = []

        for system in systems:
            sys_repos = self._repo_projection.list_all(system_id=system.system_id)
            sys_cost = Decimal("0")
            healthy = 0
            failing = 0

            for repo in sys_repos:
                cost_data = await self._store.get("repo_cost", repo.full_name)
                if cost_data:
                    rc = RepoCost.from_dict(cost_data)
                    sys_cost += rc.total_cost_usd

                health_data = await self._store.get("repo_health", repo.full_name)
                if health_data:
                    rh = RepoHealth.from_dict(health_data)
                    if rh.total_executions > 0 and rh.success_rate < 0.5:
                        failing += 1
                    elif rh.total_executions > 0:
                        healthy += 1

            total_cost += sys_cost

            if failing > len(sys_repos) / 2:
                status = "failing"
            elif failing > 0:
                status = "degraded"
            else:
                status = "healthy"

            entries.append(
                SystemOverviewEntry(
                    system_id=system.system_id,
                    system_name=system.name,
                    organization_id=system.organization_id,
                    repo_count=len(sys_repos),
                    overall_status=status,
                    active_executions=0,
                    total_cost_usd=sys_cost,
                )
            )

        return GlobalOverview(
            total_systems=len(systems),
            total_repos=len(all_repos),
            unassigned_repos=len(unassigned),
            total_active_executions=total_active,
            total_cost_usd=total_cost,
            systems=entries,
        )
