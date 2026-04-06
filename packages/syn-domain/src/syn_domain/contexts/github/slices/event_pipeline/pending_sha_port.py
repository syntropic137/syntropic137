"""Port for tracking commit SHAs awaiting check-run completion (#602).

When a pull_request event arrives, the CheckRunPoller registers the head SHA
as pending. The poller then polls the Checks API for each pending SHA until
all check runs complete, synthesizing check_run.completed events for failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PendingSHA:
    """A commit SHA awaiting check-run completion."""

    repository: str
    """Full repository name, e.g. ``"owner/repo"``."""

    sha: str
    """Git commit SHA (head of the PR)."""

    pr_number: int
    """Pull request number."""

    branch: str
    """Head branch ref name."""

    installation_id: str
    """GitHub App installation ID for API authentication."""

    registered_at: datetime
    """When this SHA was registered for polling."""


class PendingSHAStore(Protocol):
    """Port: tracks commit SHAs whose check runs need polling.

    In-memory by default. SHAs are ephemeral — a restart just means a
    brief gap until the next PR event re-registers the SHA.
    """

    async def register(self, pending: PendingSHA) -> None:
        """Register a SHA for check-run polling. No-op if already registered."""
        ...

    async def list_pending(self) -> list[PendingSHA]:
        """Return all pending SHAs."""
        ...

    async def remove(self, repository: str, sha: str) -> None:
        """Remove a SHA after all check runs have completed."""
        ...

    async def cleanup_stale(self, max_age: timedelta) -> int:
        """Remove SHAs older than *max_age*. Returns count removed."""
        ...
