"""Session tools projection for querying tool operations from TimescaleDB.

This projection provides a clean interface for querying tool operations
(tool_started, tool_completed) for a given session.

See ADR-029: Simplified Event System
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from syn_shared.events import TOOL_COMPLETED, TOOL_STARTED

if TYPE_CHECKING:
    from datetime import datetime

    import asyncpg

logger = logging.getLogger(__name__)

# Use constants for type safety
_TOOL_EVENT_TYPES = (TOOL_STARTED, TOOL_COMPLETED)


@dataclass
class ToolOperation:
    """Read model for a tool operation from TimescaleDB.

    Represents either a tool_started or tool_completed event.
    """

    observation_id: str
    tool_name: str
    tool_use_id: str | None
    operation_type: str  # "tool_started" or "tool_completed"
    timestamp: datetime
    success: bool | None  # Only for tool_execution_completed
    input_preview: str | None  # Truncated input for display
    output_preview: str | None  # Truncated output for display
    duration_ms: int | None  # Only for tool_execution_completed

    @property
    def is_started(self) -> bool:
        """Check if this is a tool_started event."""
        return self.operation_type == TOOL_STARTED

    @property
    def is_completed(self) -> bool:
        """Check if this is a tool_completed event."""
        return self.operation_type == TOOL_COMPLETED


class SessionToolsProjection:
    """Projection for querying tool operations from TimescaleDB.

    Provides efficient queries for tool operations within a session,
    with optional filtering by execution or phase.

    Usage:
        projection = SessionToolsProjection(pool)
        operations = await projection.get("session-123")
    """

    def __init__(self, pool: asyncpg.Pool | None = None) -> None:
        """Initialize with optional connection pool.

        Args:
            pool: asyncpg connection pool for TimescaleDB.
                  If None, will attempt to get pool from event store lazily.
        """
        self._pool = pool

    def _get_pool(self) -> asyncpg.Pool | None:
        """Get the database pool, lazily loading from event store if needed."""
        if self._pool is not None:
            logger.debug("Using cached pool")
            return self._pool

        # Try to get pool from initialized event store
        try:
            from syn_adapters.events import get_event_store

            store = get_event_store()
            logger.debug("Got event store, pool is %s", "available" if store.pool else "None")
            if store.pool is not None:
                self._pool = store.pool
                logger.info("SessionToolsProjection: Acquired pool from event store")
                return self._pool
        except Exception as e:
            logger.warning("Could not get pool from event store: %s", e)

        logger.debug("No pool available for SessionToolsProjection")
        return None

    async def get(self, session_id: str) -> list[ToolOperation]:
        """Get all tool operations for a session.

        Args:
            session_id: The session ID to query

        Returns:
            List of tool operations ordered by timestamp
        """
        pool = self._get_pool()
        if pool is None:
            logger.debug("No pool available, returning empty list")
            return []

        try:
            async with pool.acquire() as conn:
                # Query with LEFT JOIN to get tool_name from started events
                # for completed events that don't have it (Claude PostToolUse
                # hook doesn't receive tool_name, only tool_use_id)
                rows = await conn.fetch(
                    """
                    WITH tool_names AS (
                        -- Get tool_name -> tool_use_id mapping from started events
                        SELECT
                            data->>'tool_use_id' as tool_use_id,
                            data->>'tool_name' as tool_name
                        FROM agent_events
                        WHERE session_id = $1
                          AND event_type = $2
                          AND data->>'tool_name' IS NOT NULL
                    )
                    SELECT
                        e.event_type,
                        e.time,
                        -- Merge tool_name from started event into data for completed
                        CASE
                            WHEN e.event_type = $3 AND e.data->>'tool_name' IS NULL
                            THEN jsonb_set(
                                e.data::jsonb,
                                '{tool_name}',
                                to_jsonb(COALESCE(tn.tool_name, 'unknown'))
                            )
                            ELSE e.data::jsonb
                        END as data
                    FROM agent_events e
                    LEFT JOIN tool_names tn ON tn.tool_use_id = e.data->>'tool_use_id'
                    WHERE e.session_id = $1
                      AND e.event_type = ANY($4)
                    ORDER BY e.time ASC
                    """,
                    session_id,
                    TOOL_STARTED,
                    TOOL_COMPLETED,
                    list(_TOOL_EVENT_TYPES),
                )

                logger.info("SessionToolsProjection.get(%s): found %d rows", session_id, len(rows))
                return [self._row_to_operation(row) for row in rows]
        except Exception as e:
            logger.error("Failed to query tool operations for %s: %s", session_id, e)
            return []

    async def query(
        self,
        execution_id: str | None = None,
        phase_id: str | None = None,
        tool_name: str | None = None,
        limit: int = 1000,
        **_kwargs: Any,
    ) -> list[ToolOperation]:
        """Query tool operations with filters.

        Args:
            execution_id: Filter by execution ID
            phase_id: Filter by phase ID
            tool_name: Filter by tool name
            limit: Maximum results to return

        Returns:
            List of matching tool operations
        """
        pool = self._get_pool()
        if pool is None:
            return []

        # Build dynamic query with type-safe event types
        conditions = [f"event_type = ANY(${1})"]
        params: list[Any] = [list(_TOOL_EVENT_TYPES)]
        param_idx = 2

        if execution_id:
            conditions.append(f"execution_id = ${param_idx}")
            params.append(execution_id)
            param_idx += 1

        if phase_id:
            conditions.append(f"phase_id = ${param_idx}")
            params.append(phase_id)
            param_idx += 1

        if tool_name:
            conditions.append(f"data->>'tool_name' = ${param_idx}")
            params.append(tool_name)
            param_idx += 1

        params.append(limit)

        query = f"""
            SELECT
                event_type,
                time,
                data
            FROM agent_events
            WHERE {" AND ".join(conditions)}
            ORDER BY time ASC
            LIMIT ${param_idx}
        """

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                return [self._row_to_operation(row) for row in rows]
        except Exception as e:
            logger.error("Failed to query tool operations: %s", e)
            return []

    def _row_to_operation(self, row: Any) -> ToolOperation:
        """Convert a database row to a ToolOperation.

        Args:
            row: Database row with event data

        Returns:
            ToolOperation read model
        """
        # Parse JSON data field
        data = row["data"]
        if isinstance(data, str):
            data = json.loads(data)

        event_type = row["event_type"]
        is_completed = event_type == TOOL_COMPLETED

        # Generate a unique ID from the row data
        tool_use_id = data.get("tool_use_id", "")
        obs_id = data.get("observation_id") or f"{tool_use_id}-{row['time'].isoformat()}"

        return ToolOperation(
            observation_id=obs_id or str(uuid4()),
            tool_name=data.get("tool_name", "unknown"),
            tool_use_id=data.get("tool_use_id"),
            operation_type=event_type,
            timestamp=row["time"],
            success=data.get("success") if is_completed else None,
            input_preview=data.get("input_preview"),
            output_preview=data.get("output_preview") if is_completed else None,
            duration_ms=data.get("duration_ms") if is_completed else None,
        )
