"""In-memory LRU dedup adapter for tests and Redis-unavailable fallback."""

from __future__ import annotations

import time
from collections import OrderedDict

_DEFAULT_MAX_SIZE = 10_000


class InMemoryDedupAdapter:
    """In-memory LRU dedup adapter.

    Implements :class:`~syn_domain.contexts.github.slices.event_pipeline.dedup_port.DedupPort`.

    Uses :class:`OrderedDict` for O(1) LRU eviction. Suitable for
    tests, offline mode, and as a fallback when Redis is unavailable.
    """

    def __init__(self, max_size: int = _DEFAULT_MAX_SIZE) -> None:
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._max_size = max_size

    async def is_duplicate(self, dedup_key: str) -> bool:
        """Return ``True`` if this key was already seen (duplicate)."""
        if dedup_key in self._seen:
            self._seen.move_to_end(dedup_key)
            return True
        self._seen[dedup_key] = time.monotonic()
        self._evict_if_needed()
        return False

    async def mark_seen(self, dedup_key: str) -> None:
        """Explicitly mark a key as seen."""
        self._seen[dedup_key] = time.monotonic()
        self._seen.move_to_end(dedup_key)
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        while len(self._seen) > self._max_size:
            self._seen.popitem(last=False)
