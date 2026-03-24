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

from syn_adapters.projections.session_tools_helpers import (
    get_pool as _get_pool_impl,
)
from syn_adapters.projections.session_tools_helpers import (
    get_session_tools as _get_session_tools_impl,
)
from syn_adapters.projections.session_tools_helpers import (
    query_session_tools as _query_session_tools_impl,
)
from syn_adapters.projections.session_tools_helpers import (
    row_to_operation as _row_to_operation_impl,
)
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
        return _get_pool_impl(self)

    async def get(self, session_id: str) -> list[ToolOperation]:
        """Get all tool operations for a session.

        Args:
            session_id: The session ID to query

        Returns:
            List of tool operations ordered by timestamp
        """
        return await _get_session_tools_impl(
            self,
            session_id,
            _TIMELINE_EXCLUDE,
            TOOL_EXECUTION_STARTED,
            TOOL_EXECUTION_COMPLETED,
            _SUBAGENT_TOOL_NAMES,
            _GIT_EVENT_TYPES,
        )

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
        return await _query_session_tools_impl(
            self,
            _TIMELINE_EXCLUDE,
            _SUBAGENT_TOOL_NAMES,
            _GIT_EVENT_TYPES,
            execution_id=execution_id,
            phase_id=phase_id,
            tool_name=tool_name,
            limit=limit,
        )

    def _row_to_operation(self, row: Any) -> ToolOperation | None:
        """Convert a database row to a ToolOperation.

        Dispatches to specialized handlers based on event type.
        Returns None if the row should be skipped.
        """
        return _row_to_operation_impl(row, _SUBAGENT_TOOL_NAMES, _GIT_EVENT_TYPES)
