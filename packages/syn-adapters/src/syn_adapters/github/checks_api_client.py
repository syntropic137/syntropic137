"""GitHub Checks API client for polling check-run results (#602).

Wraps ``GET /repos/{owner}/{repo}/commits/{ref}/check-runs`` to fetch
CI check-run status for a specific commit SHA. Used by CheckRunPoller
to detect CI failures for poll-based self-healing.

See: https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_adapters.github.client import GitHubAppClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CheckRunsResponse:
    """Response from the Checks API for a single commit ref."""

    check_runs: list[dict[str, Any]]
    """List of check-run objects."""

    total_count: int
    """Total number of check runs for this ref."""


class GitHubChecksAPIClient:
    """Client for GitHub's Checks API.

    Fetches check-run results for a commit SHA. Unlike the Events API client,
    this does not use ETag caching — each request returns the current state.

    See: https://docs.github.com/en/rest/checks/runs
    """

    def __init__(self, github_client: GitHubAppClient) -> None:
        self._client = github_client

    async def get_check_runs_for_ref(
        self,
        owner: str,
        repo: str,
        ref: str,
        installation_id: str,
    ) -> CheckRunsResponse:
        """Fetch check runs for a commit SHA.

        Args:
            owner: Repository owner.
            repo: Repository name.
            ref: Git reference (commit SHA).
            installation_id: GitHub App installation ID.

        Returns:
            CheckRunsResponse with check-run objects and total count.

        Raises:
            GitHubRateLimitError: If rate limited (caller should back off).
            GitHubAppError: On other API errors.
        """
        path = f"/repos/{owner}/{repo}/commits/{ref}/check-runs"
        data = await self._client.api_get(path, installation_id=installation_id)

        check_runs: list[dict[str, Any]] = data.get("check_runs", [])
        total_count: int = data.get("total_count", len(check_runs))

        logger.debug(
            "Checks API: %s/%s@%s — %d/%d check runs",
            owner,
            repo,
            ref[:8],
            len(check_runs),
            total_count,
        )

        return CheckRunsResponse(check_runs=check_runs, total_count=total_count)
