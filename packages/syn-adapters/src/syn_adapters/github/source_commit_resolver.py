"""GitHub adapter for ``SourceCommitResolverPort`` (#1457).

Reads ``GET /repos/{owner}/{repo}/commits/HEAD`` through the App installation
that covers the repository. Total, as the port requires: every failure - an
unconfigured App, a repository no installation covers, a rate limit, a network
error - is logged and becomes None, recorded as "commit unknown".
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from syn_domain.contexts.orchestration.ports.SourceCommitResolverPort import (
    SourceCommitResolverPort,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_adapters.github.client import GitHubAppClient
    from syn_domain.contexts._shared.repository_ref import RepositoryRef

logger = logging.getLogger(__name__)


class GitHubSourceCommitResolver(SourceCommitResolverPort):
    """Reads a repository's default-branch HEAD sha from GitHub.

    Takes a client FACTORY, not a client: ``get_github_client`` raises on an
    unconfigured App, and an install without one must still start executions.
    """

    def __init__(self, client_factory: Callable[[], GitHubAppClient]) -> None:
        self._client_factory = client_factory

    async def head_sha(self, repo: RepositoryRef) -> str | None:
        """The default-branch HEAD sha, or None when GitHub cannot say."""
        from syn_adapters.github.client import GitHubAppError

        try:
            client = self._client_factory()
            installation_id = await client.get_installation_for_repo(repo.slug)
            body = await client.api_get(f"/repos/{repo.slug}/commits/HEAD", installation_id)
        except (GitHubAppError, httpx.HTTPError, ValueError) as exc:
            logger.warning("Could not read the source commit of %s: %s", repo.slug, exc)
            return None
        sha = body.get("sha")
        return sha if isinstance(sha, str) and sha else None
