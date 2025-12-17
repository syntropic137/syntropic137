"""Session tools projection for querying tool operations from TimescaleDB.

This projection provides a clean interface for querying tool operations
(tool_started, tool_completed) for a given session.

See ADR-026: TimescaleDB for Observability Storage
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aef_adapters.projections.observability_base import ObservabilityProjection

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


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
    success: bool | None  # Only for tool_completed
    input_preview: str | None  # Truncated input for display
    output_preview: str | None  # Truncated output for display
    duration_ms: int | None  # Only for tool_completed

    @property
    def is_started(self) -> bool:
        """Check if this is a tool_started event."""
        return self.operation_type == "tool_started"

    @property
    def is_completed(self) -> bool:
        """Check if this is a tool_completed event."""
        return self.operation_type == "tool_completed"


class SessionToolsProjection(ObservabilityProjection[list[ToolOperation]]):
    """Projection for querying tool operations from TimescaleDB.

    Provides efficient queries for tool operations within a session,
    with optional filtering by execution or phase.

    Usage:
        projection = SessionToolsProjection(pool)
        operations = await projection.get("session-123")
    """

    async def get(self, session_id: str) -> list[ToolOperation]:
        """Get all tool operations for a session.

        Args:
            session_id: The session ID to query

        Returns:
            List of tool operations ordered by timestamp
        """
        if self._pool is None:
            logger.debug("No pool available, returning empty list")
            return []

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        observation_id,
                        observation_type,
                        time,
                        data
                    FROM agent_observations
                    WHERE session_id = $1
                      AND observation_type IN ('tool_started', 'tool_completed')
                    ORDER BY time ASC
                    """,
                    session_id,
                )

                return [self._row_to_operation(row) for row in rows]
        except Exception as e:
            logger.error("Failed to query tool operations: %s", e)
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
        if self._pool is None:
            return []

        # Build dynamic query
        conditions = ["observation_type IN ('tool_started', 'tool_completed')"]
        params: list[Any] = []
        param_idx = 1

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
                observation_id,
                observation_type,
                time,
                data
            FROM agent_observations
            WHERE {' AND '.join(conditions)}
            ORDER BY time ASC
            LIMIT ${param_idx}
        """

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                return [self._row_to_operation(row) for row in rows]
        except Exception as e:
            logger.error("Failed to query tool operations: %s", e)
            return []

    def _row_to_operation(self, row: Any) -> ToolOperation:
        """Convert a database row to a ToolOperation.

        Args:
            row: Database row with observation data

        Returns:
            ToolOperation read model
        """
        # Parse JSON data field
        data = row["data"]
        if isinstance(data, str):
            data = json.loads(data)

        observation_type = row["observation_type"]
        is_completed = observation_type == "tool_completed"

        return ToolOperation(
            observation_id=row["observation_id"],
            tool_name=data.get("tool_name", "unknown"),
            tool_use_id=data.get("tool_use_id"),
            operation_type=observation_type,
            timestamp=row["time"],
            success=data.get("success") if is_completed else None,
            input_preview=data.get("input_preview"),
            output_preview=data.get("output_preview") if is_completed else None,
            duration_ms=data.get("duration_ms") if is_completed else None,
        )
