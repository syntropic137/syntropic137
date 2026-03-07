"""Handler for GetRepoSessionsQuery.

Lazy handler: queries the SessionList projection for sessions
whose execution_id matches executions correlated with a repo.
"""

from typing import Any

from syn_domain.contexts.organization.domain.queries.get_repo_sessions import (
    GetRepoSessionsQuery,
)


class GetRepoSessionsHandler:
    """Query handler: get agent sessions for a repo."""

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

    async def handle(self, query: GetRepoSessionsQuery) -> list[dict[str, Any]]:
        """Handle GetRepoSessionsQuery.

        Returns session dicts from the session_list projection,
        filtered to sessions whose execution_id is correlated with the repo.
        """
        execution_ids = await self._get_execution_ids_for_repo(query.repo_id)
        if not execution_ids:
            return []

        all_sessions = await self._store.get_all("agent_sessions")

        sessions = [
            s for s in all_sessions
            if s.get("execution_id") in execution_ids
        ]

        # Sort by started_at descending, apply pagination
        sessions.sort(key=lambda s: str(s.get("started_at", "")), reverse=True)
        return sessions[query.offset : query.offset + query.limit]
