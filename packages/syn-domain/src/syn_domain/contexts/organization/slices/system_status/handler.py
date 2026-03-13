"""Handler for GetSystemStatusQuery.

Lazy handler: aggregates repo health snapshots from the repo_health
store, using in-memory projections for system→repo membership.
"""

from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
from syn_domain.contexts.organization._shared.projection_names import REPO_HEALTH
from syn_domain.contexts.organization.domain.queries.get_system_status import (
    GetSystemStatusQuery,
)
from syn_domain.contexts.organization.domain.read_models.repo_health import RepoHealth
from syn_domain.contexts.organization.domain.read_models.system_status import (
    RepoStatusEntry,
    SystemStatus,
)
from syn_domain.contexts.organization.slices.list_repos.projection import (
    RepoProjection,
)
from syn_domain.contexts.organization.slices.list_systems.projection import (
    SystemProjection,
)


def _repo_status(health: RepoHealth) -> str:
    """Derive status string from a repo's health metrics."""
    if health.total_executions == 0:
        return "inactive"
    if health.success_rate >= 0.9:
        return "healthy"
    if health.success_rate >= 0.5:
        return "degraded"
    return "failing"


class GetSystemStatusHandler:
    """Query handler: get a system's cross-repo health overview."""

    def __init__(
        self,
        store: ProjectionStoreProtocol,
        system_projection: SystemProjection,
        repo_projection: RepoProjection,
    ) -> None:
        self._store = store
        self._system_projection = system_projection
        self._repo_projection = repo_projection

    async def handle(self, query: GetSystemStatusQuery) -> SystemStatus:
        """Handle GetSystemStatusQuery."""
        system = self._system_projection.get(query.system_id)
        system_name = system.name if system else ""
        organization_id = system.organization_id if system else ""

        repos = self._repo_projection.list_all(system_id=query.system_id)

        # Batch-load all health data — avoid N+1
        all_health_data = await self._store.get_all(REPO_HEALTH)
        health_by_repo: dict[str, RepoHealth] = {}
        for hd in all_health_data:
            name = hd.get("repo_full_name", "")
            if name:
                health_by_repo[name] = RepoHealth.from_dict(hd)

        repo_entries: list[RepoStatusEntry] = []
        healthy = 0
        degraded = 0
        failing = 0

        for repo in repos:
            health = health_by_repo.get(repo.full_name, RepoHealth())
            status = _repo_status(health)

            if status == "healthy":
                healthy += 1
            elif status == "degraded":
                degraded += 1
            elif status == "failing":
                failing += 1

            repo_entries.append(
                RepoStatusEntry(
                    repo_id=repo.repo_id,
                    repo_full_name=repo.full_name,
                    status=status,
                    success_rate=health.success_rate,
                    last_execution_at=health.last_execution_at,
                )
            )

        total = len(repo_entries)
        if total == 0:
            overall = "healthy"
        elif failing > total / 2:
            overall = "failing"
        elif failing > 0 or degraded > 0:
            overall = "degraded"
        else:
            overall = "healthy"

        return SystemStatus(
            system_id=query.system_id,
            system_name=system_name,
            organization_id=organization_id,
            overall_status=overall,
            total_repos=total,
            healthy_repos=healthy,
            degraded_repos=degraded,
            failing_repos=failing,
            repos=repo_entries,
        )
