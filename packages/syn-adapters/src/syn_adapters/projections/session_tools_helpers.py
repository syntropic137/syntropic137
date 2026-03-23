"""Helper functions for SessionToolsProjection row conversion.

Extracted from session_tools.py to reduce module complexity.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

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
