"""Helper functions for SessionToolsProjection row conversion and queries.

Extracted from session_tools.py to reduce module complexity.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    import asyncpg

    from syn_adapters.projections.session_tools import SessionToolsProjection

from syn_shared.events import (
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

logger = logging.getLogger(__name__)

_SUBAGENT_EVENT_TYPES = (SUBAGENT_STARTED, SUBAGENT_STOPPED)


def _extract_agent_label(data: dict[str, Any]) -> str:
    """Extract a display name for a subagent from tool input data."""
    from syn_adapters.projections.session_tools_converters import extract_agent_label

    return extract_agent_label(data)


def _row_to_subagent_operation(row: Any, data: dict[str, Any], event_type: str) -> Any:
    """Convert a tool event row for an Agent/Task tool into a subagent operation."""
    from syn_adapters.projections.session_tools_converters import row_to_subagent_operation

    return row_to_subagent_operation(row, data, event_type)


def _row_to_git_operation(row: Any, data: dict[str, Any], event_type: str) -> Any:
    """Convert a git event row into a ToolOperation."""
    from syn_adapters.projections.session_tools_converters import row_to_git_operation

    return row_to_git_operation(row, data, event_type)


def row_to_operation(
    row: Any,
    subagent_tool_names: set[str],
    git_event_types: tuple[str, ...],
) -> Any | None:
    """Convert a database row to a ToolOperation.

    Dispatches to specialized handlers based on event type.
    Returns None if the row should be skipped.
    """
    from syn_adapters.projections.session_tools import ToolOperation

    data = row["data"]
    if isinstance(data, str):
        data = json.loads(data)

    event_type = row["event_type"]

    # TODO(#175): Flip dedup direction when Claude Code's SubagentStart hook
    # includes prompt/description data. Currently native subagent events are
    # sparse (no prompt), so we drop them and relabel Agent/Task tool events
    # as subagent operations instead.
    if event_type in _SUBAGENT_EVENT_TYPES:
        return None

    # Relabel Agent/Task tool events as subagent operations
    if event_type in (TOOL_EXECUTION_STARTED, TOOL_EXECUTION_COMPLETED):
        tool_name = data.get("tool_name") or (data.get("context") or {}).get("tool_name", "")
        if tool_name in subagent_tool_names:
            return _row_to_subagent_operation(row, data, event_type)

    if event_type in git_event_types:
        return _row_to_git_operation(row, data, event_type)

    # Standard tool/other event
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


def get_pool(proj: SessionToolsProjection) -> asyncpg.Pool | None:
    """Get the database pool, lazily loading from event store if needed."""
    if proj._pool is not None:
        logger.debug("Using cached pool")
        return proj._pool

    # Try to get pool from initialized event store
    try:
        from syn_adapters.events import get_event_store

        store = get_event_store()
        logger.debug("Got event store, pool is %s", "available" if store.pool else "None")
        if store.pool is not None:
            proj._pool = store.pool
            logger.info("SessionToolsProjection: Acquired pool from event store")
            return proj._pool
    except Exception as e:
        logger.warning("Could not get pool from event store: %s", e)

    logger.debug("No pool available for SessionToolsProjection")
    return None


async def get_session_tools(
    proj: SessionToolsProjection,
    session_id: str,
    timeline_exclude: tuple[str, ...],
    tool_execution_started: str,
    tool_execution_completed: str,
    subagent_tool_names: set[str],
    git_event_types: tuple[str, ...],
) -> list[Any]:
    """Get all tool operations for a session.

    Args:
        proj: The projection instance.
        session_id: The session ID to query.
        timeline_exclude: Event types to exclude from the timeline.
        tool_execution_started: The tool_execution_started event type constant.
        tool_execution_completed: The tool_execution_completed event type constant.
        subagent_tool_names: Set of tool names that identify subagent operations.
        git_event_types: Tuple of git event type constants.

    Returns:
        List of tool operations ordered by timestamp.
    """
    pool = get_pool(proj)
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
                tool_execution_started,
                tool_execution_completed,
                list(timeline_exclude),
            )

            logger.info("SessionToolsProjection.get(%s): found %d rows", session_id, len(rows))
            return [
                op
                for row in rows
                if (op := row_to_operation(row, subagent_tool_names, git_event_types)) is not None
            ]
    except Exception as e:
        logger.error("Failed to query tool operations for %s: %s", session_id, e)
        return []


async def query_session_tools(
    proj: SessionToolsProjection,
    timeline_exclude: tuple[str, ...],
    subagent_tool_names: set[str],
    git_event_types: tuple[str, ...],
    execution_id: str | None = None,
    phase_id: str | None = None,
    tool_name: str | None = None,
    limit: int = 1000,
) -> list[Any]:
    """Query tool operations with filters.

    Args:
        proj: The projection instance.
        timeline_exclude: Event types to exclude.
        subagent_tool_names: Set of tool names that identify subagent operations.
        git_event_types: Tuple of git event type constants.
        execution_id: Filter by execution ID.
        phase_id: Filter by phase ID.
        tool_name: Filter by tool name.
        limit: Maximum results to return.

    Returns:
        List of matching tool operations.
    """
    pool = get_pool(proj)
    if pool is None:
        return []

    # Exclude high-volume, non-activity events (same logic as get())
    conditions = [f"event_type != ALL(${1})"]
    params: list[Any] = [list(timeline_exclude)]
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

    sql_query = f"""
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
            rows = await conn.fetch(sql_query, *params)
            return [
                op
                for row in rows
                if (op := row_to_operation(row, subagent_tool_names, git_event_types)) is not None
            ]
    except Exception as e:
        logger.error("Failed to query tool operations: %s", e)
        return []
