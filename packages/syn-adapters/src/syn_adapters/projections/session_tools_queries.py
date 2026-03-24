"""Query functions for SessionToolsProjection.

Extracted from session_tools_converters.py to reduce module complexity.
row_to_operation is in session_tools_dispatch.py.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_adapters.projections.session_tools_dispatch import row_to_operation as row_to_operation

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
        _logger.error("Failed to query tool operations: %s", e)
        return []
