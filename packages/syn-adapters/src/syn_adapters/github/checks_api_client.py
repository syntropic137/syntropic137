"""GitHub Checks API adapter -- implements ``GitHubChecksAPIPort``.

Wraps ``GET /repos/{owner}/{repo}/commits/{ref}/check-runs`` for
``CheckRunIngestionService``. Total port: rate-limit errors are
translated into ``rate_limited=True`` rather than raised, so the
domain never imports adapter exception types.

See ADR-060 Section 10 (hexagonal layout).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.github.ports.checks_api_port import (
    ChecksAPIResult,
    GitHubChecksAPIPort,
)

if TYPE_CHECKING:
    from syn_adapters.github.client import GitHubAppClient

logger = logging.getLogger(__name__)

_DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 60.0


class GitHubChecksAPIClient(GitHubChecksAPIPort):
    """Stateless adapter implementing ``GitHubChecksAPIPort``.

    Subclasses the Protocol explicitly so the ``test_port_adoption`` fitness
    check can verify implementation at CI time.
    """

    def __init__(self, github_client: GitHubAppClient) -> None:
        self._client = github_client

    async def fetch_check_runs(
        self,
        owner: str,
        repo: str,
        ref: str,
        installation_id: str,
    ) -> ChecksAPIResult:
        from syn_adapters.github.client import GitHubRateLimitError

        path = f"/repos/{owner}/{repo}/commits/{ref}/check-runs"
        try:
            data = await self._client.api_get(path, installation_id=installation_id)
        except GitHubRateLimitError as exc:
            wait = _DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
            if exc.reset_at is not None:
                wait = max((exc.reset_at - datetime.now(UTC)).total_seconds(), 0.0)
            return ChecksAPIResult(
                check_runs=[],
                total_count=0,
                rate_limited=True,
                retry_after_seconds=wait,
            )

        check_runs: list[dict[str, Any]] = data.get("check_runs", [])
        total_count: int = data.get("total_count", len(check_runs))

        logger.debug(
            "Checks API: %s/%s@%s -- %d/%d check runs",
            owner,
            repo,
            ref[:8],
            len(check_runs),
            total_count,
        )

        return ChecksAPIResult(check_runs=check_runs, total_count=total_count)
