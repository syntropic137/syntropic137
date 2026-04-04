"""Protocol for projection storage adapters.

This module defines the abstract interface for storing and retrieving
projection read models. Implementations can be swapped for different
storage backends (PostgreSQL, in-memory, etc.).
"""

from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ProjectionStoreProtocol(Protocol):
    """Abstract storage interface for projection read models.

    Projections use this protocol to persist their read models,
    allowing the storage backend to be swapped without changing
    the projection logic.

    Key features:
    - Per-projection namespacing (projection name as prefix)
    - Position tracking for catch-up subscriptions
    - Simple key-value style operations
    """

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        """Save or update a projection record.

        Args:
            projection: Name of the projection (e.g., "workflow_summaries")
            key: Unique identifier for the record (usually aggregate ID)
            data: Dictionary of field values to store
        """
        ...

    async def get(self, projection: str, key: str) -> dict[str, Any] | None:
        """Get a single projection record by key.

        Args:
            projection: Name of the projection
            key: Unique identifier for the record

        Returns:
            Dictionary of field values, or None if not found
        """
        ...

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        """Get all records for a projection.

        Args:
            projection: Name of the projection

        Returns:
            List of dictionaries, one per record
        """
        ...

    async def delete(self, projection: str, key: str) -> None:
        """Delete a projection record.

        Args:
            projection: Name of the projection
            key: Unique identifier for the record
        """
        ...

    async def query(
        self,
        projection: str,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query projection records with optional filtering.

        Args:
            projection: Name of the projection
            filters: Dictionary of field=value filters (exact match)
            order_by: Field name to sort by (prefix with - for descending)
            limit: Maximum number of records to return
            offset: Number of records to skip

        Returns:
            List of matching dictionaries
        """
        ...

    async def get_position(self, projection: str) -> int | None:
        """Get the last processed event position for a projection.

        Used for catch-up subscriptions to resume from where
        the projection left off.

        Args:
            projection: Name of the projection

        Returns:
            Last processed event position, or None if never processed
        """
        ...

    async def set_position(self, projection: str, position: int) -> None:
        """Update the last processed event position for a projection.

        Args:
            projection: Name of the projection
            position: Event position that was just processed
        """
        ...

    async def get_by_prefix(self, projection: str, prefix: str) -> list[tuple[str, dict[str, Any]]]:
        """Get all records whose key starts with the given prefix.

        Used for partial-ID resolution: the caller provides a short prefix
        and this method returns up to 10 matching (key, data) pairs.

        Args:
            projection: Name of the projection
            prefix: The key prefix to match against

        Returns:
            List of (key, data) tuples for matching records (max 10)
        """
        ...

    async def get_last_updated(self, projection: str) -> datetime | None:
        """Get the last update timestamp for a projection.

        Args:
            projection: Name of the projection

        Returns:
            Timestamp of last update, or None if never updated
        """
        ...
