"""Session tools projection for querying tool operations from TimescaleDB.

This projection provides a clean interface for querying tool operations
(tool_started, tool_completed) for a given session.

See ADR-029: Simplified Event System
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agentic_events.types import ClaudeToolName

from syn_shared.events import (
    COST_RECORDED,
    GIT_BRANCH_CHANGED,
    GIT_CHECKOUT,
    GIT_COMMIT,
    GIT_MERGE,
    GIT_OPERATION,
    GIT_PUSH,
    GIT_REWRITE,
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)
from syn_adapters.projections.session_tools_helpers import (
    row_to_operation as _row_to_operation_impl,
)

if TYPE_CHECKING:
    from datetime import datetime

    import asyncpg

logger = logging.getLogger(__name__)

# Exclude high-volume, non-activity events from the session timeline.
# All other event types — including any new ones added to agentic-primitives —
# appear automatically without requiring changes here.
_TIMELINE_EXCLUDE = (TOKEN_USAGE, COST_RECORDED, SESSION_SUMMARY)

_SUBAGENT_TOOL_NAMES = {str(ClaudeToolName.SUBAGENT), str(ClaudeToolName.SUBAGENT_LEGACY)}
_GIT_EVENT_TYPES = (
    GIT_COMMIT,
    GIT_PUSH,
    GIT_BRANCH_CHANGED,
    GIT_OPERATION,
    GIT_MERGE,
    GIT_REWRITE,
    GIT_CHECKOUT,
)


@dataclass
class ToolOperation:
    """Read model for a session timeline event from TimescaleDB.

    Covers tool executions, git operations, subagent lifecycle, and other
    observability events recorded during a session.
    """

    observation_id: str
    tool_name: str
    tool_use_id: str | None
    operation_type: str  # e.g. "tool_started", "git_commit", "subagent_started"
    timestamp: datetime
    success: bool | None  # Only for tool_execution_completed
    input_preview: str | None  # Truncated input for display
    output_preview: str | None  # Truncated output for display
    duration_ms: int | None  # Only for tool_execution_completed
    # Git-specific fields (populated for git_* event types)
    git_sha: str | None = None
    git_message: str | None = None
    git_branch: str | None = None
    git_repo: str | None = None

    @property
    def is_started(self) -> bool:
        """Check if this is a tool_started event."""
        return self.operation_type == TOOL_EXECUTION_STARTED

    @property
    def is_completed(self) -> bool:
        """Check if this is a tool_completed event."""
        return self.operation_type == TOOL_EXECUTION_COMPLETED


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
                      AND e.event_type != ALL($4)
                    ORDER BY e.time ASC
                    """,
                    session_id,
                    TOOL_EXECUTION_STARTED,
                    TOOL_EXECUTION_COMPLETED,
                    list(_TIMELINE_EXCLUDE),
                )

                logger.info("SessionToolsProjection.get(%s): found %d rows", session_id, len(rows))
                return [op for row in rows if (op := self._row_to_operation(row)) is not None]
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

        # Exclude high-volume, non-activity events (same logic as get())
        conditions = [f"event_type != ALL(${1})"]
        params: list[Any] = [list(_TIMELINE_EXCLUDE)]
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
                return [op for row in rows if (op := self._row_to_operation(row)) is not None]
        except Exception as e:
            logger.error("Failed to query tool operations: %s", e)
            return []

    def _row_to_operation(self, row: Any) -> ToolOperation | None:
        """Convert a database row to a ToolOperation.

        Dispatches to specialized handlers based on event type.
        Returns None if the row should be skipped.
        """
        return _row_to_operation_impl(row, _SUBAGENT_TOOL_NAMES, _GIT_EVENT_TYPES)
