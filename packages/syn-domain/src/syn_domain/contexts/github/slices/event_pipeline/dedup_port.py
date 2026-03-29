"""DedupPort — protocol for event deduplication."""

from __future__ import annotations

from typing import Protocol


class DedupPort(Protocol):
    """Port for event deduplication.

    Implementations must provide atomic check-and-mark semantics:
    ``is_duplicate`` checks whether a key has been seen and, if not,
    marks it as seen in one atomic operation.
    """

    async def is_duplicate(self, dedup_key: str) -> bool:
        """Check if this key has been seen before.

        If the key is new, atomically marks it as seen and returns ``False``.
        If the key was already present, returns ``True`` (duplicate).
        """
        ...

    async def mark_seen(self, dedup_key: str) -> None:
        """Explicitly mark a key as seen.

        Useful for events that bypass the normal ``is_duplicate`` path.
        """
        ...
