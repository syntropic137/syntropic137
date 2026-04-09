"""Deduplication filter for event collection.

Prevents duplicate events using an in-memory LRU cache.
Events are identified by their deterministic event_id.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict

logger = logging.getLogger(__name__)


class DeduplicationFilter:
    """In-memory deduplication using bounded LRU cache.

    Provides fast O(1) lookup for duplicate detection with
    bounded memory usage. Older entries are evicted when
    the cache reaches capacity.

    Thread-safe for concurrent access from async handlers.

    Attributes:
        max_size: Maximum number of event IDs to track
    """

    def __init__(self, max_size: int = 100_000) -> None:
        """Initialize the deduplication filter.

        Args:
            max_size: Maximum event IDs to cache (default 100K)
        """
        self._seen: OrderedDict[str, bool] = OrderedDict()
        self._max_size = max_size
        self._lock = threading.Lock()
        self._stats = {
            "checks": 0,
            "hits": 0,
            "evictions": 0,
        }

    def is_duplicate(self, event_id: str) -> bool:
        """Check if event has been seen before.

        If not seen, marks the event as seen.

        Args:
            event_id: Deterministic event identifier

        Returns:
            True if event was already seen
        """
        with self._lock:
            self._stats["checks"] += 1

            if event_id in self._seen:
                self._stats["hits"] += 1
                # Move to end (most recently seen)
                self._seen.move_to_end(event_id)
                return True

            # Add to cache
            self._seen[event_id] = True

            # Evict oldest if over capacity
            while len(self._seen) > self._max_size:
                self._seen.popitem(last=False)
                self._stats["evictions"] += 1

            return False

    def mark_seen(self, event_id: str) -> None:
        """Explicitly mark an event as seen.

        Useful for pre-loading known events.

        Args:
            event_id: Event identifier to mark
        """
        with self._lock:
            if event_id not in self._seen:
                self._seen[event_id] = True

                while len(self._seen) > self._max_size:
                    self._seen.popitem(last=False)
                    self._stats["evictions"] += 1

    def is_seen(self, event_id: str) -> bool:
        """Check if event is seen without marking it.

        Tracks stats (checks/hits) like is_duplicate() but does NOT mark the
        event as seen.  Use with mark_seen() for write-after-confirm dedup.

        Args:
            event_id: Event identifier to check

        Returns:
            True if event was seen
        """
        with self._lock:
            self._stats["checks"] += 1
            if event_id in self._seen:
                self._stats["hits"] += 1
                self._seen.move_to_end(event_id)
                return True
            return False

    def clear(self) -> None:
        """Clear all tracked events."""
        with self._lock:
            self._seen.clear()

    @property
    def size(self) -> int:
        """Current number of tracked events."""
        with self._lock:
            return len(self._seen)

    @property
    def stats(self) -> dict[str, int]:
        """Get deduplication statistics.

        Returns:
            Dict with checks, hits, evictions counts
        """
        with self._lock:
            return {
                **self._stats,
                "size": len(self._seen),
                "max_size": self._max_size,
            }

    def hit_rate(self) -> float:
        """Calculate duplicate hit rate.

        Returns:
            Percentage of checks that were duplicates (0-100)
        """
        with self._lock:
            if self._stats["checks"] == 0:
                return 0.0
            return (self._stats["hits"] / self._stats["checks"]) * 100
