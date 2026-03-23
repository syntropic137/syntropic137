"""Handler for GetGlobalOverviewQuery.

Lazy handler: aggregates health and cost across all systems from
in-memory projections and projection stores.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.organization._shared.projection_names import (
    REPO_COST,
    REPO_HEALTH,
)
from syn_domain.contexts.organization.domain.read_models.global_overview import (
    GlobalOverview,
    SystemOverviewEntry,
)
from syn_domain.contexts.organization.domain.read_models.repo_cost import RepoCost
from syn_domain.contexts.organization.domain.read_models.repo_health import RepoHealth

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
    from syn_domain.contexts.organization.domain.queries.get_global_overview import (
        GetGlobalOverviewQuery,
    )
    from syn_domain.contexts.organization.domain.read_models.repo_summary import RepoSummary
    from syn_domain.contexts.organization.slices.list_repos.projection import RepoProjection
    from syn_domain.contexts.organization.slices.list_systems.projection import SystemProjection


def _build_index(
    records: list[dict[str, Any]],
    key_field: str,
    model_class: type[RepoCost] | type[RepoHealth],
) -> dict[str, RepoCost | RepoHealth]:
    """Build a lookup dict from projection store records."""
    result: dict[str, Any] = {}
    for record in records:
        name = record.get(key_field, "")
        if name:
            result[name] = model_class.from_dict(record)
    return result


def _determine_system_status(failing: int, total: int) -> str:
    """Classify a system's overall status from repo health counts."""
    if total > 0 and failing > total / 2:
        return "failing"
    if failing > 0:
        return "degraded"
    return "healthy"


def _compute_system_entry(
    system: Any,
    repos: list[RepoSummary],
    cost_by_repo: dict[str, RepoCost],
    health_by_repo: dict[str, RepoHealth],
) -> SystemOverviewEntry:
    """Build a SystemOverviewEntry for one system from its repos."""
    sys_cost = Decimal("0")
    failing = 0

    for repo in repos:
        rc = cost_by_repo.get(repo.full_name)
        if rc:
            sys_cost += rc.total_cost_usd

        rh = health_by_repo.get(repo.full_name)
        if rh and rh.total_executions > 0 and rh.success_rate < 0.5:
            failing += 1

    return SystemOverviewEntry(
        system_id=system.system_id,
        system_name=system.name,
        organization_id=system.organization_id,
        repo_count=len(repos),
        overall_status=_determine_system_status(failing, len(repos)),
        active_executions=0,
        total_cost_usd=sys_cost,
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

        cost_by_repo = _build_index(await self._store.get_all(REPO_COST), "repo_full_name", RepoCost)
        health_by_repo = _build_index(
            await self._store.get_all(REPO_HEALTH), "repo_full_name", RepoHealth
        )

        repos_by_system: dict[str, list[RepoSummary]] = {}
        for repo in all_repos:
            repos_by_system.setdefault(repo.system_id or "", []).append(repo)

        entries = [
            _compute_system_entry(system, repos_by_system.get(system.system_id, []), cost_by_repo, health_by_repo)  # type: ignore[arg-type]
            for system in systems
        ]

        return GlobalOverview(
            total_systems=len(systems),
            total_repos=len(all_repos),
            unassigned_repos=len(unassigned),
            total_active_executions=0,
            total_cost_usd=sum((e.total_cost_usd for e in entries), Decimal("0")),
            systems=entries,
        )
