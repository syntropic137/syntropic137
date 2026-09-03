"""Protocol for projection storage adapters.

This module re-exports ESP's ProjectionStore and ProjectionReadStore protocols,
and defines ProjectionStoreProtocol as an extension with syntropic137-specific
methods. Domain code should import directly from event_sourcing; adapter code
can use ProjectionStoreProtocol for the extended interface.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from event_sourcing import ProjectionReadStore, ProjectionStore

__all__ = ["ProjectionReadStore", "ProjectionStore", "ProjectionStoreProtocol"]


@runtime_checkable
class ProjectionStoreProtocol(ProjectionStore, Protocol):
    """Extended projection store with syntropic137-specific methods.

    Extends ESP's ProjectionStore with get_last_updated() for metadata
    queries, and get_position/set_position for legacy subscription
    position tracking (deprecated - use ProjectionCheckpointStore for
    new code). Domain code should depend on the base ProjectionStore
    or ProjectionReadStore protocols; only adapter code should reference
    this extended protocol.
    """

    async def count(self, projection: str, filters: dict[str, str] | None = None) -> int:
        """How many records a projection holds, optionally filtered.

        Exists so a paginated endpoint can report the size of the COLLECTION
        rather than the size of the page it just built (#1119). Counting by
        fetching everything and taking `len` would reintroduce exactly the
        per-row cost #1114 removed, so it is a store-level count.

        `filters` uses the same equality semantics as `query`, so a count and
        the query it describes cannot disagree about what they are counting.
        """
        ...

    async def get_last_updated(self, projection: str) -> datetime | None:
        """Get the last update timestamp for a projection."""
        ...

    async def get_position(self, projection: str) -> int | None:
        """Get saved subscription position (deprecated - use ProjectionCheckpointStore)."""
        ...

    async def set_position(self, projection: str, position: int) -> None:
        """Save subscription position (deprecated - use ProjectionCheckpointStore)."""
        ...
