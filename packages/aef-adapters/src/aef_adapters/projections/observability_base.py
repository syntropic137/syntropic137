"""Base class for observability projections.

This module is deprecated. New projections should use AgentEventStore directly.
See ADR-029: Simplified Event System.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg


class ObservabilityProjection:
    """Base class for observability projections.

    DEPRECATED: Use AgentEventStore directly for new projections.

    This class provided a common interface for projections that query
    the agent_observations table. With ADR-029, we're moving to
    the agent_events table via AgentEventStore.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Initialize with database connection pool.

        Args:
            pool: asyncpg connection pool
        """
        self._pool = pool
