"""Handler for GetSystemStatusQuery.

Lazy handler: aggregates repo health snapshots from the repo_health
store, using in-memory projections for system→repo membership.
"""

from typing import Any

from syn_domain.contexts.organization.domain.queries.get_system_status import (
    GetSystemStatusQuery,
)
from syn_domain.contexts.organization.domain.read_models.repo_health import RepoHealth
from syn_domain.contexts.organization.domain.read_models.system_status import (
    RepoStatusEntry,
    SystemStatus,
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
        store: Any,
        system_projection: Any,
        repo_projection: Any,
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

        repo_entries: list[RepoStatusEntry] = []
        healthy = 0
        degraded = 0
        failing = 0

        for repo in repos:
            health_data = await self._store.get("repo_health", repo.full_name)
            health = RepoHealth.from_dict(health_data) if health_data else RepoHealth()
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
