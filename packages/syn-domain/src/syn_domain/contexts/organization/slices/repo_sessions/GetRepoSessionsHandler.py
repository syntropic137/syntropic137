"""Handler for GetRepoSessionsQuery.

Lazy handler: queries the SessionList projection for sessions
whose execution_id matches executions correlated with a repo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.organization._shared.execution_correlation import (
    executions_by_repo,
)
from syn_domain.contexts.organization._shared.projection_names import SESSION_SUMMARIES
from syn_domain.contexts.organization.domain.read_models.repo_session import (
    RepoSessionRecord,
)

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

    from syn_domain.contexts.organization.domain.queries.get_repo_sessions import (
        GetRepoSessionsQuery,
    )


class GetRepoSessionsHandler:
    """Query handler: get agent sessions for a repo."""

    def __init__(self, store: ProjectionStore) -> None:
        """Initialize with the shared ProjectionStore."""
        self._store = store

    async def _get_execution_ids_for_repo(self, repo_id: str, repo_full_name: str = "") -> set[str]:
        """Look up execution IDs correlated with a repo."""
        match_key = repo_full_name or repo_id
        return set(await executions_by_repo(self._store, [match_key]))

    async def handle(self, query: GetRepoSessionsQuery) -> list[RepoSessionRecord]:
        """Handle GetRepoSessionsQuery.

        Returns session records from the session_list projection,
        filtered to sessions whose execution_id is correlated with the repo.
        """
        execution_ids = await self._get_execution_ids_for_repo(query.repo_id, query.repo_full_name)
        if not execution_ids:
            return []

        all_sessions = await self._store.get_all(SESSION_SUMMARIES)

        matched = [
            RepoSessionRecord.from_dict(s)
            for s in all_sessions
            if s.get("execution_id") in execution_ids
        ]

        # Sort by started_at descending, apply pagination
        matched.sort(key=lambda s: str(s.started_at or ""), reverse=True)
        return matched[query.offset : query.offset + query.limit]
