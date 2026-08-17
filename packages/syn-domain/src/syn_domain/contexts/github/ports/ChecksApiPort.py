"""GitHubChecksAPIPort - domain-owned contract for the GitHub Checks API.

Used by ``CheckRunIngestionService`` to fetch check-run status for pending
SHAs. Like ``GitHubEventsAPIPort``, the port is total: rate-limit errors
become a result field, not an exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ChecksAPIResult:
    """Response from the Checks API for a single commit ref."""

    check_runs: list[dict[str, Any]]
    """Raw check-run payloads (the synthesizer maps them to NormalizedEvent)."""

    total_count: int
    """Total number of check runs reported by GitHub for this ref."""

    rate_limited: bool = False
    """``True`` if GitHub returned a rate-limit error."""

    retry_after_seconds: float = 0.0
    """When ``rate_limited=True``, seconds the caller should wait before retry."""


class GitHubChecksAPIPort(Protocol):
    """Port: fetches check-run results for a commit SHA."""

    async def fetch_check_runs(
        self,
        owner: str,
        repo: str,
        ref: str,
        installation_id: str,
    ) -> ChecksAPIResult:
        """Fetch check runs for a commit SHA.

        On rate-limit, returns ``ChecksAPIResult(rate_limited=True,
        retry_after_seconds=N, check_runs=[], total_count=0)``. The adapter
        does NOT raise.
        """
        ...
