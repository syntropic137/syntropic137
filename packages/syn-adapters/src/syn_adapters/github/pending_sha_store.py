"""In-memory PendingSHAStore implementation (#602).

Tracks commit SHAs whose check runs need polling. Ephemeral -- SHAs are
lost on restart, but the next PR event re-registers them.

NOTE: This store intentionally does NOT inherit from InMemoryAdapter.
It is allowed in production because loss on restart has no correctness
impact -- only a delayed check-run poll until the next PR event.
See ADR-060 section 6 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import PendingSHA


class InMemoryPendingSHAStore:
    """In-memory implementation of the PendingSHAStore protocol.

    Keyed by ``(repository, sha)`` — a SHA is registered at most once.
    Thread-safe in asyncio context (single-threaded event loop).
    """

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], PendingSHA] = {}

    async def register(self, pending: PendingSHA) -> None:
        """Register a SHA for check-run polling. No-op if already registered."""
        key = (pending.repository, pending.sha)
        if key not in self._pending:
            self._pending[key] = pending

    async def list_pending(self) -> list[PendingSHA]:
        """Return all pending SHAs."""
        return list(self._pending.values())

    async def remove(self, repository: str, sha: str) -> None:
        """Remove a SHA after all check runs have completed."""
        self._pending.pop((repository, sha), None)

    async def cleanup_stale(self, max_age: timedelta) -> int:
        """Remove SHAs older than *max_age*. Returns count removed."""
        cutoff = datetime.now(UTC) - max_age
        stale = [k for k, v in self._pending.items() if v.registered_at < cutoff]
        for k in stale:
            del self._pending[k]
        return len(stale)
