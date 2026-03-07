"""Handler for GetRepoFailuresQuery.

Lazy handler: queries the WorkflowExecutionList projection for failed
executions filtered by repo-execution correlation.
"""

from typing import Any

from syn_domain.contexts.organization.domain.queries.get_repo_failures import (
    GetRepoFailuresQuery,
)
from syn_domain.contexts.organization.domain.read_models.repo_failure import (
    RepoFailure,
)


class GetRepoFailuresHandler:
    """Query handler: get a repo's recent failures."""

    def __init__(self, store: Any) -> None:
        """Initialize with the shared ProjectionStore."""
        self._store = store

    async def _get_execution_ids_for_repo(self, repo_id: str) -> set[str]:
        """Look up execution IDs correlated with a repo."""
        correlations = await self._store.get_all("repo_correlation")
        return {
            c["execution_id"]
            for c in correlations
            if c.get("repo_full_name") == repo_id
        }

    async def handle(self, query: GetRepoFailuresQuery) -> list[RepoFailure]:
        """Handle GetRepoFailuresQuery."""
        execution_ids = await self._get_execution_ids_for_repo(query.repo_id)
        if not execution_ids:
            return []

        all_executions = await self._store.get_all("workflow_executions")

        failures = []
        for ex in all_executions:
            ex_id = ex.get("workflow_execution_id", "")
            status = ex.get("status", "")
            if ex_id not in execution_ids or status != "failed":
                continue
            failures.append(
                RepoFailure(
                    execution_id=ex_id,
                    workflow_id=ex.get("workflow_id", ""),
                    workflow_name=ex.get("workflow_name", ""),
                    failed_at=str(ex.get("completed_at", "")),
                    error_message=ex.get("error_message", "") or "",
                    error_type="",
                    phase_name="",
                )
            )

        # Sort by failed_at descending, apply pagination
        failures.sort(key=lambda f: f.failed_at, reverse=True)
        return failures[query.offset : query.offset + query.limit]
