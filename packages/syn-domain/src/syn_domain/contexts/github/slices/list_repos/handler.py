"""List Accessible Repos query handler.

Maps raw GitHub API responses to AccessibleRepository read models.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.github.domain.queries.list_accessible_repos import (
    ListAccessibleReposQuery,
)
from syn_domain.contexts.github.domain.read_models.accessible_repository import (
    AccessibleRepository,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class GitHubRepoClient(Protocol):
    """Protocol for the subset of GitHubAppClient we need."""

    async def list_accessible_repos(
        self, installation_id: str | None = None
    ) -> list[dict]: ...


def _map_repo(raw: dict, installation_id: str) -> AccessibleRepository | None:
    """Map a raw GitHub API repo dict to an AccessibleRepository.

    Returns None if required fields are missing.
    """
    github_id = raw.get("id")
    name = raw.get("name")
    full_name = raw.get("full_name")

    if github_id is None or name is None or full_name is None:
        logger.warning("Skipping malformed repo entry: missing required fields in %s", raw.get("full_name", raw.get("id", "unknown")))
        return None

    return AccessibleRepository(
        id=int(github_id),
        name=str(name),
        full_name=str(full_name),
        private=bool(raw.get("private", False)),
        default_branch=str(raw.get("default_branch", "main")),
        installation_id=installation_id,
    )


class ListAccessibleReposHandler:
    """Handles ListAccessibleReposQuery by calling the GitHub API."""

    def __init__(self, client: GitHubRepoClient) -> None:
        self._client = client

    async def handle(self, query: ListAccessibleReposQuery) -> list[AccessibleRepository]:
        """Execute the query and return accessible repositories.

        Args:
            query: The query with installation_id and filter options.

        Returns:
            List of AccessibleRepository read models.
        """
        raw_repos = await self._client.list_accessible_repos(
            installation_id=query.installation_id
        )

        repos: list[AccessibleRepository] = []
        for raw in raw_repos:
            repo = _map_repo(raw, query.installation_id)
            if repo is None:
                continue
            if not query.include_private and repo.private:
                continue
            repos.append(repo)

        return repos
