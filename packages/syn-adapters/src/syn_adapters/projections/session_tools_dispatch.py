"""Row-to-operation dispatcher for session tools projection.

Extracted from session_tools_queries.py to reduce module complexity.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    import asyncpg

    from syn_adapters.projections.session_tools import ToolOperation

from syn_adapters.projections.session_tools_converters import (
    to_git_operation,
    to_subagent_operation,
)
from syn_adapters.projections.session_tools_verdict import observation_id, read_verdict
from syn_shared.events import (
    SESSION_COMPLETED,
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

_SUBAGENT_EVENT_TYPES = (SUBAGENT_STARTED, SUBAGENT_STOPPED)

#: Row types that report a FINISHED subject, and so are the ones whose
#: `output_preview` and `duration_ms` mean anything. This was spelled
#: `event_type == TOOL_EXECUTION_COMPLETED`, which made `is_completed` narrower
#: than its own name: `session_completed` carries the phase's wall-clock
#: duration and was having it dropped one hop after the writer computed it.
_COMPLETION_EVENT_TYPES: frozenset[str] = frozenset(
    {TOOL_EXECUTION_COMPLETED, SESSION_COMPLETED},
)


def _parse_row_data(row: asyncpg.Record) -> dict[str, Any]:
    """Extract and decode the data field from a database row."""
    data = row["data"]
    if isinstance(data, str):
        return json.loads(data)
    return data


def _is_subagent_tool_event(event_type: str, tool_name: str, subagent_tool_names: set[str]) -> bool:
    """Check if a tool execution event is actually a subagent operation."""
    if event_type not in (TOOL_EXECUTION_STARTED, TOOL_EXECUTION_COMPLETED):
        return False
    return tool_name in subagent_tool_names


def build_standard_operation(
    when: datetime, data: dict[str, Any], event_type: str
) -> ToolOperation:
    """Build a ToolOperation for a standard tool event.

    "Standard" is everything the subagent and git converters do not claim, so
    this is the converter that handles `session_error` - and every other
    session- and phase-level row, which is why the verdict is read here from a
    rule keyed on the event type rather than special-cased for one of them.
    """
    from syn_adapters.projections.session_tools import ToolOperation

    is_completed = event_type in _COMPLETION_EVENT_TYPES
    verdict = read_verdict(event_type, data)
    # `event_type` is always present, so this is never empty. The old
    # `or str(uuid4())` tail could therefore never fire either - and a uuid
    # here would have broken the determinism `_accumulate_tool_stats` relies
    # on, so the dead branch is gone rather than kept "just in case".
    obs_id = data.get("observation_id") or observation_id(
        event_type, data.get("tool_use_id"), when.isoformat()
    )

    return ToolOperation(
        observation_id=obs_id,
        tool_name=data.get("tool_name", ""),
        tool_use_id=data.get("tool_use_id"),
        operation_type=event_type,
        timestamp=when,
        success=verdict.success,
        error_message=verdict.error_message,
        input_preview=data.get("input_preview"),
        output_preview=data.get("output_preview") if is_completed else None,
        duration_ms=data.get("duration_ms") if is_completed else None,
    )


def to_operation(
    when: datetime,
    data: dict[str, Any],
    event_type: str,
    subagent_tool_names: set[str],
    git_event_types: tuple[str, ...],
) -> ToolOperation | None:
    """Convert one recorded observation to a ToolOperation.

    Takes the three things an observation IS rather than the row it arrived
    in, so the same dispatch serves the TimescaleDB reader and the in-memory
    timeline. A timeline that converts its own way is a timeline that can pass
    a test production would fail (#1034).

    Returns None if the observation should not appear on the timeline.
    """
    tool_name = data.get("tool_name") or (data.get("context") or {}).get("tool_name", "")

    # TODO(#175): Flip dedup direction when Claude Code's SubagentStart hook
    # includes prompt/description data. Currently native subagent events are
    # sparse (no prompt), so we drop them and relabel Agent/Task tool events
    # as subagent operations instead.
    if event_type in _SUBAGENT_EVENT_TYPES:
        return None

    if _is_subagent_tool_event(event_type, tool_name, subagent_tool_names):
        return to_subagent_operation(when, data, event_type)

    if event_type in git_event_types:
        return to_git_operation(when, data, event_type)

    return build_standard_operation(when, data, event_type)


def row_to_operation(
    row: asyncpg.Record,
    subagent_tool_names: set[str],
    git_event_types: tuple[str, ...],
) -> ToolOperation | None:
    """Unpack a TimescaleDB row and convert it. Row shape stops here."""
    return to_operation(
        row["time"],
        _parse_row_data(row),
        row["event_type"],
        subagent_tool_names,
        git_event_types,
    )
