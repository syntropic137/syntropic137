"""Base class for TimescaleDB-backed observability projections.

Unlike event-sourced projections that subscribe to domain events,
observability projections query TimescaleDB directly for high-volume
telemetry data (tool calls, token usage, etc.).

This follows the CQRS pattern where:
- Commands → Event Store (domain events)
- Queries → TimescaleDB (observability events)

See ADR-026: TimescaleDB for Observability Storage
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ObservabilityProjection[T](ABC):
    """Base class for projections that query TimescaleDB observability data.

    Subclasses implement specific query patterns for different read models:
    - SessionToolsProjection: Tool operations for a session
    - SessionCostProjection: Cost metrics for a session
    - ExecutionMetricsProjection: Aggregate metrics for an execution

    Usage:
        class SessionToolsProjection(ObservabilityProjection[list[ToolOperation]]):
            async def get(self, session_id: str) -> list[ToolOperation]:
                ...
    """

    def __init__(self, pool: Any | None = None) -> None:
        """Initialize with optional connection pool.

        Args:
            pool: asyncpg connection pool from ObservabilityWriter
        """
        self._pool = pool

    @property
    def pool(self) -> Any | None:
        """Get the connection pool."""
        return self._pool

    @abstractmethod
    async def get(self, id: str) -> T | None:
        """Get a single read model by ID.

        Args:
            id: The primary identifier (e.g., session_id)

        Returns:
            The read model or None if not found
        """
        ...

    async def query(self, **_filters: Any) -> list[Any]:
        """Query read models with filters.

        Override in subclasses that support filtering.

        Args:
            **_filters: Query filters (e.g., execution_id, phase_id)

        Returns:
            List of matching read models
        """
        return []
