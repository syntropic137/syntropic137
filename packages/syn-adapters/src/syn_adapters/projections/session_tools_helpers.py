"""Helper functions for SessionToolsProjection — pool and session query.

Extracted from session_tools.py to reduce module complexity.
row_to_operation and query_session_tools have been moved to session_tools_converters.py.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg

    from syn_adapters.projections.session_tools import SessionToolsProjection

from syn_adapters.projections.session_tools_converters import (
    query_session_tools,
    row_to_operation,
)
from syn_shared.events import (
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
)

logger = logging.getLogger(__name__)

_SUBAGENT_EVENT_TYPES = (SUBAGENT_STARTED, SUBAGENT_STOPPED)

__all__ = ["get_pool", "get_session_tools", "row_to_operation", "query_session_tools"]


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
