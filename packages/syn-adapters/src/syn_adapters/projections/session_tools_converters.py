"""Row conversion helpers for session tools projection.

Extracted from session_tools.py to reduce module complexity.
row_to_operation and query_session_tools moved here from session_tools_helpers.py.
"""

from __future__ import annotations

import json
import logging
import re as _re
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from syn_shared.events import (
    GIT_REWRITE,
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    import asyncpg

    from syn_adapters.projections.session_tools import SessionToolsProjection, ToolOperation

_logger = logging.getLogger(__name__)

_SUBAGENT_EVENT_TYPES = (SUBAGENT_STARTED, SUBAGENT_STOPPED)


def extract_agent_label(data: dict[str, Any]) -> str:
    """Extract a display name for a subagent from tool input data."""
    tool_input = data.get("input_preview") or data.get("tool_input")
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = None
    if isinstance(tool_input, dict):
        return str(
            tool_input.get("description")
            or tool_input.get("subagent_type")
            or data.get("tool_name", "")
        )
    return str(data.get("tool_name", ""))


def row_to_subagent_operation(row: Any, data: dict[str, Any], event_type: str) -> ToolOperation:
    """Convert a tool event row for an Agent/Task tool into a subagent operation."""
    from syn_adapters.projections.session_tools import ToolOperation

    tool_use_id = data.get("tool_use_id", "")
    is_started = event_type == TOOL_EXECUTION_STARTED
    subagent_op = SUBAGENT_STARTED if is_started else SUBAGENT_STOPPED
    agent_label = extract_agent_label(data)
    obs_id = f"subagent-{subagent_op}-{tool_use_id}-{row['time'].isoformat()}"
    return ToolOperation(
        observation_id=obs_id,
        tool_name=agent_label,
        tool_use_id=tool_use_id or None,
        operation_type=subagent_op,
        timestamp=row["time"],
        success=data.get("success") if not is_started else None,
        input_preview=data.get("input_preview") or json.dumps(data),
        output_preview=data.get("output_preview") if not is_started else None,
        duration_ms=data.get("duration_ms") if not is_started else None,
    )


def row_to_git_operation(row: Any, data: dict[str, Any], event_type: str) -> ToolOperation:
    """Convert a git event row into a ToolOperation."""
    from syn_adapters.projections.session_tools import ToolOperation

    obs_id = f"git-{event_type}-{row['time'].isoformat()}"
    git_subcmd = data.get("operation", "")
    git_branch = data.get("branch") or data.get("to_branch") or None

    if not git_branch and event_type == "git_operation":
        cmd = data.get("command", "")
        _m = _re.search(r"git\s+checkout\s+(?:-b\s+)?(\S+)", cmd)
        if _m:
            git_branch = _m.group(1)

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
            return row_to_subagent_operation(row, data, event_type)

    if event_type in git_event_types:
        return row_to_git_operation(row, data, event_type)

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
