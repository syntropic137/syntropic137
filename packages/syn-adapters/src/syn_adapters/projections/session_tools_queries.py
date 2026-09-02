"""Query functions for SessionToolsProjection.

Extracted from session_tools_converters.py to reduce module complexity.
row_to_operation is in session_tools_dispatch.py.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_adapters.projections.session_tools_dispatch import row_to_operation as row_to_operation
from syn_shared.events import TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from syn_adapters.projections.session_tools import SessionToolsProjection

_logger = logging.getLogger(__name__)


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
    from syn_adapters.projections.session_tools_helpers import get_pool

    pool = get_pool(proj)
    if pool is None:
        return []

    # Exclude high-volume, non-activity events (same logic as get())
    conditions = [f"e.event_type != ALL(${1})"]
    params: list[Any] = [list(timeline_exclude)]
    param_idx = 2

    if execution_id:
        conditions.append(f"e.execution_id = ${param_idx}")
        params.append(execution_id)
        param_idx += 1

    if phase_id:
        conditions.append(f"e.phase_id = ${param_idx}")
        params.append(phase_id)
        param_idx += 1

    if tool_name:
        conditions.append(f"e.data->>'tool_name' = ${param_idx}")
        params.append(tool_name)
        param_idx += 1

    # Pair completed rows with their started row's timestamp to derive
    # duration_ms (issue #1064 — no writer populates it directly). A
    # completed row with no matching started row (truncated Codex stream,
    # see CodexStreamProcessor.py:579) or an out-of-order timestamp yields
    # NULL, never a fabricated 0. Not scoped by execution/phase filters:
    # tool_use_id is unique per tool call, so cross-scope collisions do not
    # occur in practice.
    started_idx = param_idx
    params.append(TOOL_EXECUTION_STARTED)
    param_idx += 1

    completed_idx = param_idx
    params.append(TOOL_EXECUTION_COMPLETED)
    param_idx += 1

    limit_idx = param_idx
    params.append(limit)

    sql_query = f"""
        WITH tool_starts AS (
            SELECT
                data->>'tool_use_id' as tool_use_id,
                time as started_time
            FROM agent_events
            WHERE event_type = ${started_idx}
              AND data->>'tool_use_id' IS NOT NULL
        )
        SELECT
            e.event_type,
            e.time,
            CASE
                WHEN e.event_type = ${completed_idx} THEN
                    jsonb_set(
                        e.data::jsonb,
                        '{{duration_ms}}',
                        CASE
                            WHEN ts.started_time IS NOT NULL
                                 AND e.time >= ts.started_time
                            THEN to_jsonb(round((
                                EXTRACT(EPOCH FROM (e.time - ts.started_time)) * 1000
                            )::numeric)::bigint)
                            ELSE 'null'::jsonb
                        END
                    )
                ELSE e.data::jsonb
            END as data
        FROM agent_events e
        LEFT JOIN tool_starts ts ON ts.tool_use_id = e.data->>'tool_use_id'
        WHERE {" AND ".join(conditions)}
        ORDER BY e.time ASC
        LIMIT ${limit_idx}
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
        _logger.error("Failed to query tool operations: %s", e)
        return []
