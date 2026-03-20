"""Handler for GetGlobalOverviewQuery.

Lazy handler: aggregates health and cost across all systems from
in-memory projections and projection stores.
"""

from decimal import Decimal

from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
from syn_domain.contexts.organization._shared.projection_names import (
    REPO_COST,
    REPO_HEALTH,
)
from syn_domain.contexts.organization.domain.queries.get_global_overview import (
    GetGlobalOverviewQuery,
)
from syn_domain.contexts.organization.domain.read_models.global_overview import (
    GlobalOverview,
    SystemOverviewEntry,
)
from syn_domain.contexts.organization.domain.read_models.repo_cost import RepoCost
from syn_domain.contexts.organization.domain.read_models.repo_health import RepoHealth
from syn_domain.contexts.organization.slices.list_repos.projection import (
    RepoProjection,
)
from syn_domain.contexts.organization.slices.list_systems.projection import (
    SystemProjection,
)


class GetGlobalOverviewHandler:
    """Query handler: get global overview of all systems and repos."""

    def __init__(
        self,
        store: ProjectionStoreProtocol,
        system_projection: SystemProjection,
        repo_projection: RepoProjection,
    ) -> None:
        self._store = store
        self._system_projection = system_projection
        self._repo_projection = repo_projection

    async def handle(self, query: GetGlobalOverviewQuery) -> GlobalOverview:  # noqa: ARG002
        """Handle GetGlobalOverviewQuery."""
        systems = await self._system_projection.list_all()
        all_repos = await self._repo_projection.list_all()
        unassigned = await self._repo_projection.list_all(unassigned=True)

        # Batch-load all cost and health data — avoid N+1
        all_cost_data = await self._store.get_all(REPO_COST)
        all_health_data = await self._store.get_all(REPO_HEALTH)

        cost_by_repo: dict[str, RepoCost] = {}
        for cd in all_cost_data:
            name = cd.get("repo_full_name", "")
            if name:
                cost_by_repo[name] = RepoCost.from_dict(cd)

        health_by_repo: dict[str, RepoHealth] = {}
        for hd in all_health_data:
            name = hd.get("repo_full_name", "")
            if name:
                health_by_repo[name] = RepoHealth.from_dict(hd)

        total_cost = Decimal("0")
        total_active = 0
        entries: list[SystemOverviewEntry] = []

        for system in systems:
            sys_repos = await self._repo_projection.list_all(system_id=system.system_id)
            sys_cost = Decimal("0")
            healthy = 0
            failing = 0

            for repo in sys_repos:
                rc = cost_by_repo.get(repo.full_name)
                if rc:
                    sys_cost += rc.total_cost_usd

                rh = health_by_repo.get(repo.full_name)
                if rh:
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
