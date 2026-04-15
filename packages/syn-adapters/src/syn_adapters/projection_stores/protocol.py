"""Protocol for projection storage adapters.

This module re-exports ESP's ProjectionStore and ProjectionReadStore protocols,
and defines ProjectionStoreProtocol as an extension with syntropic137-specific
methods (get_last_updated). Domain code should import directly from
event_sourcing; adapter code can use ProjectionStoreProtocol for the
extended interface.

The deprecated get_position/set_position methods have been removed.
Use ProjectionCheckpointStore for position tracking instead.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from event_sourcing import ProjectionReadStore, ProjectionStore

__all__ = ["ProjectionReadStore", "ProjectionStore", "ProjectionStoreProtocol"]


@runtime_checkable
class ProjectionStoreProtocol(ProjectionStore, Protocol):
    """Extended projection store with syntropic137-specific methods.

    Extends ESP's ProjectionStore with get_last_updated() for
    metadata queries. Domain code should depend on the base
    ProjectionStore or ProjectionReadStore protocols; only adapter
    code should reference this extended protocol.
    """

    async def get_last_updated(self, projection: str) -> datetime | None:
        """Get the last update timestamp for a projection.

        Args:
            projection: Name of the projection

        Returns:
            Timestamp of last update, or None if never updated
        """
        ...
