"""Session tools projection for querying tool operations from TimescaleDB.

This projection provides a clean interface for querying tool operations
(tool_started, tool_completed) for a given session.

See ADR-029: Simplified Event System
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

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
# Public because the lane has a second implementation - the in-memory
# timeline used in test and offline runs - and a timeline that answers a
# different set of event types than production's is not a stand-in for it.
# All other event types — including any new ones added to agentic-workspace —
# appear automatically without requiring changes here.
TIMELINE_EXCLUDE = (TOKEN_USAGE, COST_RECORDED, SESSION_SUMMARY)

SUBAGENT_TOOL_NAMES = {str(ClaudeToolName.SUBAGENT), str(ClaudeToolName.SUBAGENT_LEGACY)}
GIT_EVENT_TYPES = (
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
    success: bool | None  # None means this row carries no verdict, NOT success
    input_preview: str | None  # Truncated input for display
    output_preview: str | None  # Truncated output for display
    duration_ms: int | None  # Only for tool_execution_completed
    error_message: str | None = None
    """Why this row's subject went wrong, for the rows that record a failure.

    Set by `session_tools_verdict.read_verdict` alongside `success`, because
    they are one decision: an observation that reports a failure has to be able
    to say what failed. `session_error` recorded the reason in its payload all
    along and every reader dropped it (#1196) - the same one-hop loss as #891.
    """
    # Git-specific fields (populated for git_* event types)
    git_sha: str | None = None
    git_message: str | None = None
    git_branch: str | None = None
    git_repo: str | None = None
    # Full structured git payload from v2 events (see agentic_events.payloads)
    git_data: dict[str, object] | None = None

    @property
    def is_started(self) -> bool:
        """Check if this is a tool_started event."""
        return self.operation_type == TOOL_EXECUTION_STARTED

    @property
    def is_completed(self) -> bool:
        """Check if this is a tool_completed event."""
        return self.operation_type == TOOL_EXECUTION_COMPLETED


class TimelineRow(Protocol):
    """A timeline observation, as anything reading one needs to see it.

    TWO models carry these facts: the dataclass above, which the TimescaleDB
    reader builds, and `syn_api.types.ToolOperation`, its Pydantic mirror that
    the read path validates into one hop later and serves. A rule written
    against either concrete model can only be applied on one side of that hop,
    so it gets copied to the other - and a copied rule is a rule that drifts.

    Read-only, and deliberately only the four fields the shared rules need.
    Widening it to mirror a model would make it the model again.
    """

    @property
    def observation_id(self) -> str: ...

    @property
    def tool_use_id(self) -> str | None: ...

    @property
    def operation_type(self) -> str: ...

    @property
    def timestamp(self) -> datetime | None: ...


def call_identity(row: TimelineRow) -> str:
    """The logical call `row` belongs to, so calls can be counted, not rows.

    A tool call is TWO rows - a start and a completion - so anything counting
    rows reports twice the work that happened (#1061), and anything counting
    only starts misses both the completion-only rows a truncated stream leaves
    behind and the subagent rows the converters relabel (#1063). Folding both
    rows of a call onto one value is what makes a count of calls a count of
    calls.

    `tool_use_id` is the harness's own id and is the real identity.
    `observation_id` is the fallback for rows carrying none - git rows never
    carry one, by construction - and it is derived deterministically from row
    content, never from `uuid4()`, so a row delivered twice folds onto itself
    rather than counting twice. Its cost is that two distinct no-id calls
    landing in the same timestamp bucket collapse into one.

    Both callers are read paths that count a phase's work:
    `syn_api.routes.events._accumulate_tool_stats`, whose docstring weighs this
    rule against the alternatives that were tried, and the phase activity
    summary that tells a timed-out phase from a stalled one (#1262).
    """
    return row.tool_use_id or row.observation_id


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

    async def get(self, session_id: str) -> list[ToolOperation] | None:
        """Get all tool operations for a session.

        Args:
            session_id: The session ID to query

        Returns:
            Tool operations ordered by timestamp, ``[]`` for a session with
            none recorded, or ``None`` when the timeline could not be read -
            no database, or the query failed.

            THE THIRD ANSWER IS THE POINT. A reader that only lists rows can
            write ``or []`` and lose nothing; a reader that counts a phase's
            work cannot, because zero operations is how a stalled phase looks
            and an unreadable timeline is not evidence of one (#1332).
        """
        return await _get_session_tools_impl(
            self,
            session_id,
            TIMELINE_EXCLUDE,
            TOOL_EXECUTION_STARTED,
            TOOL_EXECUTION_COMPLETED,
            SUBAGENT_TOOL_NAMES,
            GIT_EVENT_TYPES,
        )

    async def query(
        self,
        execution_id: str | None = None,
        phase_id: str | None = None,
        tool_name: str | None = None,
        limit: int = 1000,
        **_kwargs: Any,  # noqa: ANN401
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
            TIMELINE_EXCLUDE,
            SUBAGENT_TOOL_NAMES,
            GIT_EVENT_TYPES,
            execution_id=execution_id,
            phase_id=phase_id,
            tool_name=tool_name,
            limit=limit,
        )

    def _row_to_operation(self, row: asyncpg.Record) -> ToolOperation | None:
        """Convert a database row to a ToolOperation.

        Dispatches to specialized handlers based on event type.
        Returns None if the row should be skipped.
        """
        return _row_to_operation_impl(row, SUBAGENT_TOOL_NAMES, GIT_EVENT_TYPES)
