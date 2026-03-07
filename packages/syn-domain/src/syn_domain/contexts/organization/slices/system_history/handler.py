"""Handler for GetSystemHistoryQuery.

Lazy handler: queries workflow executions filtered by system repo
membership, sorted chronologically (oldest first).
"""

from datetime import UTC

from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
from syn_domain.contexts.organization.domain.queries.get_system_history import (
    GetSystemHistoryQuery,
)
from syn_domain.contexts.organization.domain.read_models.repo_activity import (
    RepoActivityEntry,
)
from syn_domain.contexts.organization.slices.list_repos.projection import (
    RepoProjection,
)


def _compute_duration(started_at: str, completed_at: str) -> float:
    """Compute duration in seconds from ISO timestamps."""
    if not started_at or not completed_at:
        return 0.0
    try:
        from datetime import datetime

        fmt = "%Y-%m-%dT%H:%M:%S"
        start = datetime.strptime(started_at[:19], fmt).replace(tzinfo=UTC)
        end = datetime.strptime(completed_at[:19], fmt).replace(tzinfo=UTC)
        return max(0.0, (end - start).total_seconds())
    except (ValueError, TypeError):
        return 0.0


class GetSystemHistoryHandler:
    """Query handler: get a system's historical execution timeline."""

    def __init__(
        self,
        store: ProjectionStoreProtocol,
        repo_projection: RepoProjection,
    ) -> None:
        self._store = store
        self._repo_projection = repo_projection

    async def _get_execution_ids_for_system(self, system_id: str) -> set[str]:
        """Look up execution IDs for all repos in a system."""
        repos = self._repo_projection.list_all(system_id=system_id)
        repo_names = {r.full_name for r in repos}

        correlations = await self._store.get_all("repo_correlation")
        return {c["execution_id"] for c in correlations if c.get("repo_full_name") in repo_names}

    async def handle(self, query: GetSystemHistoryQuery) -> list[RepoActivityEntry]:
        """Handle GetSystemHistoryQuery."""
        # TODO(#176): Implement time-window filtering
        execution_ids = await self._get_execution_ids_for_system(query.system_id)
        if not execution_ids:
            return []

        all_executions = await self._store.get_all("workflow_executions")

        entries = []
        for ex in all_executions:
            ex_id = ex.get("workflow_execution_id", "")
            if ex_id not in execution_ids:
                continue
            started_at = str(ex.get("started_at", ""))
            completed_at = str(ex.get("completed_at", ""))
            entries.append(
                RepoActivityEntry(
                    execution_id=ex_id,
                    workflow_id=ex.get("workflow_id", ""),
                    workflow_name=ex.get("workflow_name", ""),
                    status=ex.get("status", ""),
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_seconds=_compute_duration(started_at, completed_at),
                    trigger_source="",
                )
            )

        # Sort chronologically (oldest first)
        entries.sort(key=lambda e: e.started_at)
        return entries[query.offset : query.offset + query.limit]
