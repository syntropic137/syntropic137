"""Row-to-operation dispatcher for session tools projection.

Extracted from session_tools_queries.py to reduce module complexity.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    import asyncpg

    from syn_adapters.projections.session_tools import ToolOperation

from syn_adapters.projections.session_tools_converters import (
    row_to_git_operation,
    row_to_subagent_operation,
)
from syn_shared.events import (
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

_SUBAGENT_EVENT_TYPES = (SUBAGENT_STARTED, SUBAGENT_STOPPED)


def _parse_row_data(row: asyncpg.Record) -> dict[str, Any]:
    """Extract and decode the data field from a database row."""
    data = row["data"]
    if isinstance(data, str):
        return json.loads(data)
    return data


def _is_subagent_tool_event(
    event_type: str, data: dict[str, Any], subagent_tool_names: set[str]
) -> bool:
    """Check if a tool execution event is actually a subagent operation."""
    if event_type not in (TOOL_EXECUTION_STARTED, TOOL_EXECUTION_COMPLETED):
        return False
    tool_name = data.get("tool_name") or (data.get("context") or {}).get("tool_name", "")
    return tool_name in subagent_tool_names


def _build_standard_operation(
    row: asyncpg.Record, data: dict[str, Any], event_type: str
) -> ToolOperation:
    """Build a ToolOperation for a standard tool event."""
    from syn_adapters.projections.session_tools import ToolOperation

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


def row_to_operation(
    row: asyncpg.Record,
    subagent_tool_names: set[str],
    git_event_types: tuple[str, ...],
) -> ToolOperation | None:
    """Convert a database row to a ToolOperation.

    Dispatches to specialized handlers based on event type.
    Returns None if the row should be skipped.
    """
    data = _parse_row_data(row)
    event_type = row["event_type"]

    # TODO(#175): Flip dedup direction when Claude Code's SubagentStart hook
    # includes prompt/description data. Currently native subagent events are
    # sparse (no prompt), so we drop them and relabel Agent/Task tool events
    # as subagent operations instead.
    if event_type in _SUBAGENT_EVENT_TYPES:
        return None

    if _is_subagent_tool_event(event_type, data, subagent_tool_names):
        return row_to_subagent_operation(row, data, event_type)

    if event_type in git_event_types:
        return row_to_git_operation(row, data, event_type)

    return _build_standard_operation(row, data, event_type)
