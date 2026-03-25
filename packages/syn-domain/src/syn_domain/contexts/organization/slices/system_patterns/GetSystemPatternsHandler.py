"""Handler for GetSystemPatternsQuery.

Lazy handler: analyzes workflow executions for failure patterns and
repo costs for cost outliers within a system.
"""

from decimal import Decimal
from statistics import median
from typing import Any

from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
from syn_domain.contexts.organization._shared.projection_names import (
    REPO_CORRELATION,
    REPO_COST,
    WORKFLOW_EXECUTIONS,
)
from syn_domain.contexts.organization.domain.queries.get_system_patterns import (
    GetSystemPatternsQuery,
)
from syn_domain.contexts.organization.domain.read_models.repo_cost import RepoCost
from syn_domain.contexts.organization.domain.read_models.system_patterns import (
    CostOutlier,
    FailurePattern,
    SystemPatterns,
)
from syn_domain.contexts.organization.slices.list_repos.projection import (
    RepoProjection,
)
from syn_domain.contexts.organization.slices.list_systems.projection import (
    SystemProjection,
)


def _accumulate_failure(
    groups: dict[tuple[str, str], dict[str, Any]],
    execution: dict[str, Any],
    repo_name: str,
) -> None:
    """Accumulate one failed execution into failure groups."""
    error_type = execution.get("error_type", "") or ""
    error_message = execution.get("error_message", "") or ""
    key = (error_type, error_message)
    timestamp = str(execution.get("completed_at", ""))

    if key not in groups:
        groups[key] = {
            "error_type": error_type,
            "error_message": error_message,
            "count": 0,
            "repos": set(),
            "first_seen": timestamp,
            "last_seen": timestamp,
        }

    g = groups[key]
    g["count"] += 1
    if repo_name:
        g["repos"].add(repo_name)
    if timestamp and (not g["first_seen"] or timestamp < g["first_seen"]):
        g["first_seen"] = timestamp
    if timestamp and timestamp > g["last_seen"]:
        g["last_seen"] = timestamp


def _groups_to_patterns(
    groups: dict[tuple[str, str], dict[str, Any]],
) -> list[FailurePattern]:
    """Convert failure groups to sorted FailurePattern list."""
    return [
        FailurePattern(
            error_type=g["error_type"],
            error_message=g["error_message"],
            occurrence_count=g["count"],
            affected_repos=sorted(g["repos"]),
            first_seen=g["first_seen"],
            last_seen=g["last_seen"],
        )
        for g in sorted(groups.values(), key=lambda x: x["count"], reverse=True)
    ]


class GetSystemPatternsHandler:
    """Query handler: get recurring failure and cost patterns for a system."""

    def __init__(
        self,
        store: ProjectionStoreProtocol,
        system_projection: SystemProjection,
        repo_projection: RepoProjection,
    ) -> None:
        self._store = store
        self._system_projection = system_projection
        self._repo_projection = repo_projection

    async def _get_execution_ids_for_system(self, system_id: str) -> dict[str, str]:
        """Map execution_id → repo_full_name for all repos in a system."""
        repos = await self._repo_projection.list_all(system_id=system_id)
        repo_names = {r.full_name for r in repos}

        correlations = await self._store.get_all(REPO_CORRELATION)
        return {
            c["execution_id"]: c["repo_full_name"]
            for c in correlations
            if c.get("repo_full_name") in repo_names
        }

    async def _find_failure_patterns(self, exec_to_repo: dict[str, str]) -> list[FailurePattern]:
        """Group failed executions by error type + message."""
        if not exec_to_repo:
            return []

        all_executions = await self._store.get_all(WORKFLOW_EXECUTIONS)
        execution_ids = set(exec_to_repo.keys())

        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for ex in all_executions:
            ex_id = ex.get("workflow_execution_id", "")
            if ex_id not in execution_ids or ex.get("status") != "failed":
                continue
            _accumulate_failure(groups, ex, exec_to_repo.get(ex_id, ""))

        return _groups_to_patterns(groups)

    @staticmethod
    def _detect_outliers(
        costs: list[tuple[str, Decimal]],
    ) -> list[CostOutlier]:
        """Return repos whose cost exceeds 3x the median."""
        if len(costs) < 2:
            return []

        cost_values = [c for _, c in costs]
        med = Decimal(str(median(cost_values)))
        if med <= 0:
            return []

        outliers = [
            CostOutlier(
                repo_full_name=repo_name,
                cost_usd=cost,
                median_cost_usd=med,
                deviation_factor=float(cost / med),
            )
            for repo_name, cost in costs
            if float(cost / med) > 3.0
        ]
        return sorted(outliers, key=lambda o: o.deviation_factor, reverse=True)

    async def _find_cost_outliers(self, system_id: str) -> list[CostOutlier]:
        """Find repos with cost > 3x median."""
        repos = await self._repo_projection.list_all(system_id=system_id)
        costs: list[tuple[str, Decimal]] = []

        for repo in repos:
            cost_data = await self._store.get(REPO_COST, repo.full_name)
            if not cost_data:
                continue
            rc = RepoCost.from_dict(cost_data)
            if rc.total_cost_usd > 0:
                costs.append((repo.full_name, rc.total_cost_usd))

        return self._detect_outliers(costs)

    async def handle(self, query: GetSystemPatternsQuery) -> SystemPatterns:
        """Handle GetSystemPatternsQuery."""
        # TODO(#200): Implement time-window filtering
        system = await self._system_projection.get(query.system_id)
        system_name = system.name if system else ""

        exec_to_repo = await self._get_execution_ids_for_system(query.system_id)
        failure_patterns = await self._find_failure_patterns(exec_to_repo)
        cost_outliers = await self._find_cost_outliers(query.system_id)

        return SystemPatterns(
            system_id=query.system_id,
            system_name=system_name,
            failure_patterns=failure_patterns,
            cost_outliers=cost_outliers,
            analysis_window_hours=query.window_hours,
        )
