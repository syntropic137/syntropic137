"""Handler for GetSystemStatusQuery.

Lazy handler: aggregates repo health snapshots from the repo_health
store, using in-memory projections for system→repo membership.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from syn_domain.contexts.organization._shared.projection_names import REPO_HEALTH
from syn_domain.contexts.organization.domain.read_models.repo_health import RepoHealth
from syn_domain.contexts.organization.domain.read_models.system_status import (
    RepoStatusEntry,
    SystemStatus,
)

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
    from syn_domain.contexts.organization.domain.queries.get_system_status import (
        GetSystemStatusQuery,
    )
    from syn_domain.contexts.organization.domain.read_models.repo_summary import RepoSummary
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


def _build_health_index(all_health_data: list[dict[str, Any]]) -> dict[str, RepoHealth]:
    """Build repo_full_name → RepoHealth lookup from raw store data."""
    result: dict[str, RepoHealth] = {}
    for hd in all_health_data:
        name = hd.get("repo_full_name", "")
        if name:
            result[name] = RepoHealth.from_dict(hd)
    return result


def _build_repo_entry(
    repo: RepoSummary,
    health_by_repo: dict[str, RepoHealth],
) -> RepoStatusEntry:
    """Build a RepoStatusEntry for one repo."""
    health = health_by_repo.get(repo.full_name, RepoHealth())
    return RepoStatusEntry(
        repo_id=repo.repo_id,
        repo_full_name=repo.full_name,
        status=_repo_status(health),
        success_rate=health.success_rate,
        last_execution_at=health.last_execution_at,
    )


def _count_statuses(entries: list[RepoStatusEntry]) -> dict[str, int]:
    """Count occurrences of each status in repo entries."""
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    return counts


def _determine_overall_status(counts: dict[str, int]) -> str:
    """Determine overall system status from status counts."""
    total = sum(counts.values())
    failing = counts.get("failing", 0)
    degraded = counts.get("degraded", 0)
    if total == 0:
        return "healthy"
    if failing > total / 2:
        return "failing"
    if failing > 0 or degraded > 0:
        return "degraded"
    return "healthy"


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
        system = await self._system_projection.get(query.system_id)
        system_name = system.name if system else ""
        organization_id = system.organization_id if system else ""

        repos = await self._repo_projection.list_all(system_id=query.system_id)
        health_by_repo = _build_health_index(await self._store.get_all(REPO_HEALTH))

        repo_entries = [_build_repo_entry(repo, health_by_repo) for repo in repos]
        counts = _count_statuses(repo_entries)

        return SystemStatus(
            system_id=query.system_id,
            system_name=system_name,
            organization_id=organization_id,
            overall_status=_determine_overall_status(counts),
            total_repos=len(repo_entries),
            healthy_repos=counts.get("healthy", 0),
            degraded_repos=counts.get("degraded", 0),
            failing_repos=counts.get("failing", 0),
            repos=repo_entries,
        )
