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
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
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
_SUBAGENT_EVENT_TYPES = (SUBAGENT_STARTED, SUBAGENT_STOPPED)
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

        Args:
            row: Database row with event data

        Returns:
            ToolOperation read model, or None if the row should be skipped
        """
        # Parse JSON data field
        data = row["data"]
        if isinstance(data, str):
            data = json.loads(data)

        event_type = row["event_type"]

        # TODO(#175): Flip dedup direction when Claude Code's SubagentStart hook
        # includes prompt/description data. Currently native subagent events are
        # sparse (no prompt), so we drop them and relabel Agent/Task tool events
        # as subagent operations instead. This matches what event_parser.py does
        # in the Docker pipeline. When the hook is enriched, prefer native events
        # and drop the tool events.
        if event_type in _SUBAGENT_EVENT_TYPES:
            return None

        # Relabel Agent/Task tool events as subagent operations so the prompt
        # is visible in the expandable details.
        if event_type in (TOOL_EXECUTION_STARTED, TOOL_EXECUTION_COMPLETED):
            tool_name = data.get("tool_name") or (data.get("context") or {}).get("tool_name", "")
            if tool_name in _SUBAGENT_TOOL_NAMES:
                tool_use_id = data.get("tool_use_id", "")
                is_started = event_type == TOOL_EXECUTION_STARTED
                subagent_op = SUBAGENT_STARTED if is_started else SUBAGENT_STOPPED
                # Extract a display name from the tool input
                tool_input = data.get("input_preview") or data.get("tool_input")
                if isinstance(tool_input, str):
                    try:
                        tool_input = json.loads(tool_input)
                    except (json.JSONDecodeError, TypeError):
                        tool_input = None
                if isinstance(tool_input, dict):
                    agent_label = (
                        tool_input.get("description")
                        or tool_input.get("subagent_type")
                        or tool_name
                    )
                else:
                    agent_label = tool_name
                obs_id = f"subagent-{subagent_op}-{tool_use_id}-{row['time'].isoformat()}"
                return ToolOperation(
                    observation_id=obs_id,
                    tool_name=str(agent_label),
                    tool_use_id=tool_use_id or None,
                    operation_type=subagent_op,
                    timestamp=row["time"],
                    success=data.get("success") if not is_started else None,
                    input_preview=data.get("input_preview") or json.dumps(data),
                    output_preview=data.get("output_preview") if not is_started else None,
                    duration_ms=data.get("duration_ms") if not is_started else None,
                )

        is_git = event_type in _GIT_EVENT_TYPES
        if is_git:
            obs_id = f"git-{event_type}-{row['time'].isoformat()}"

            # Extract the operation subcommand for display in the timeline title
            git_subcmd = data.get("operation", "")
            git_branch = data.get("branch") or data.get("to_branch") or None
            if not git_branch and event_type == "git_operation":
                # Parse branch from "git checkout -b <branch>" or "git checkout <branch>"
                cmd = data.get("command", "")
                import re as _re

                _m = _re.search(r"git\s+checkout\s+(?:-b\s+)?(\S+)", cmd)
                if _m:
                    git_branch = _m.group(1)

            # For git_rewrite, use the rewrite type (rebase/amend) as the subcommand
            if event_type == GIT_REWRITE and not git_subcmd:
                git_subcmd = data.get("operation", "rebase")

            return ToolOperation(
                observation_id=obs_id,
                tool_name=git_subcmd,
                tool_use_id=None,
                operation_type=event_type,
                timestamp=row["time"],
                success=True,
                input_preview=None,
                output_preview=None,
                duration_ms=None,
                git_sha=data.get("sha") or data.get("commit_hash") or data.get("merge_sha") or None,
                git_message=data.get("message")
                or data.get("message_preview")
                or data.get("commit_message")
                or None,
                git_branch=git_branch,
                git_repo=data.get("repo") or None,
            )

        # Generate a unique ID from the row data
        is_completed = event_type == TOOL_EXECUTION_COMPLETED
        tool_use_id = data.get("tool_use_id", "")
        obs_id = data.get("observation_id") or f"{tool_use_id}-{row['time'].isoformat()}"

        return ToolOperation(
            observation_id=obs_id or str(uuid4()),
            tool_name=data.get("tool_name", ""),
            tool_use_id=data.get("tool_use_id"),
            operation_type=event_type,
            timestamp=row["time"],
            success=data.get("success") if is_completed else None,
            input_preview=data.get("input_preview"),
            output_preview=data.get("output_preview") if is_completed else None,
            duration_ms=data.get("duration_ms") if is_completed else None,
        )
