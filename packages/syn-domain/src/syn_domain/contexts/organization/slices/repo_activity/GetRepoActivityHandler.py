"""Handler for GetRepoActivityQuery.

Lazy handler: queries the WorkflowExecutionList projection
filtered by repo-execution correlation. No eager projection needed.
"""

from event_sourcing import ProjectionReadStore

from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION
from syn_domain.contexts.organization.domain.queries.get_repo_activity import (
    GetRepoActivityQuery,
)
from syn_domain.contexts.organization.domain.read_models.repo_activity import (
    RepoActivityEntry,
)


class GetRepoActivityHandler:
    """Query handler: get a repo's execution timeline."""

    def __init__(self, store: ProjectionReadStore) -> None:
        """Initialize with the shared ProjectionStore."""
        self._store = store

    async def _get_execution_ids_for_repo(self, repo_id: str) -> list[str]:
        """Look up execution IDs correlated with a repo."""
        correlations = await self._store.get_all(REPO_CORRELATION)
        return [c["execution_id"] for c in correlations if c.get("repo_full_name") == repo_id]

    async def handle(self, query: GetRepoActivityQuery) -> list[RepoActivityEntry]:
        """Handle GetRepoActivityQuery."""
        execution_ids = await self._get_execution_ids_for_repo(query.repo_id)
        if not execution_ids:
            return []

        execution_id_set = set(execution_ids)
        all_executions = await self._store.get_all("workflow_executions")

        entries = [
            RepoActivityEntry.from_execution_row(ex)
            for ex in all_executions
            if ex.get("workflow_execution_id", "") in execution_id_set
        ]

        # Sort by started_at descending, apply pagination. An execution with no
        # recorded start sorts last rather than crashing the comparison.
        entries.sort(key=lambda e: e.started_at or "", reverse=True)
        return entries[query.offset : query.offset + query.limit]
