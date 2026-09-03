"""Handler for GetSystemActivityQuery.

Lazy handler: queries workflow executions filtered by system repo
membership via correlation and in-memory projections.
"""

from event_sourcing import ProjectionReadStore

from syn_domain.contexts.organization._shared.projection_names import (
    REPO_CORRELATION,
    WORKFLOW_EXECUTIONS,
)
from syn_domain.contexts.organization.domain.queries.get_system_activity import (
    GetSystemActivityQuery,
)
from syn_domain.contexts.organization.domain.read_models.repo_activity import (
    RepoActivityEntry,
)
from syn_domain.contexts.organization.slices.list_repos.projection import (
    RepoProjection,
)
from syn_shared.display import resolve_duration_seconds


class GetSystemActivityHandler:
    """Query handler: get a system's execution timeline across all repos."""

    def __init__(
        self,
        store: ProjectionReadStore,
        repo_projection: RepoProjection,
    ) -> None:
        self._store = store
        self._repo_projection = repo_projection

    async def _get_execution_ids_for_system(self, system_id: str) -> set[str]:
        """Look up execution IDs for all repos in a system."""
        repos = await self._repo_projection.list_all(system_id=system_id)
        repo_names = {r.full_name for r in repos}

        correlations = await self._store.get_all(REPO_CORRELATION)
        return {c["execution_id"] for c in correlations if c.get("repo_full_name") in repo_names}

    async def handle(self, query: GetSystemActivityQuery) -> list[RepoActivityEntry]:
        """Handle GetSystemActivityQuery."""
        execution_ids = await self._get_execution_ids_for_system(query.system_id)
        if not execution_ids:
            return []

        all_executions = await self._store.get_all(WORKFLOW_EXECUTIONS)

        entries = []
        for ex in all_executions:
            ex_id = ex.get("workflow_execution_id", "")
            if ex_id not in execution_ids:
                continue
            # `or ""`, not a dict default: a running execution stores
            # completed_at as None, and str(None) is the string "None" -- an
            # unparseable timestamp rather than an absent one.
            started_at = str(ex.get("started_at") or "")
            completed_at = str(ex.get("completed_at") or "")
            entries.append(
                RepoActivityEntry(
                    execution_id=ex_id,
                    workflow_id=ex.get("workflow_id", ""),
                    workflow_name=ex.get("workflow_name", ""),
                    status=ex.get("status", ""),
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_seconds=resolve_duration_seconds(
                        ex.get("status", ""),
                        started_at=started_at,
                        ended_at=completed_at,
                    ),
                    trigger_source="",
                )
            )

        entries.sort(key=lambda e: e.started_at, reverse=True)
        return entries[query.offset : query.offset + query.limit]
