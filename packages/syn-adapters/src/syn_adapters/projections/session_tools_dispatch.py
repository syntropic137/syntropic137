"""Row-to-operation dispatcher for session tools projection.

Extracted from session_tools_queries.py to reduce module complexity.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence
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

# The two rows a single call produces. Subagent types are here because the
# converters relabel an Agent/Task tool's rows to them before anyone downstream
# sees them - the call is still one call, and it still has a duration.
_CALL_STARTED_TYPES = (TOOL_EXECUTION_STARTED, SUBAGENT_STARTED)
_CALL_COMPLETED_TYPES = (TOOL_EXECUTION_COMPLETED, SUBAGENT_STOPPED)


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


def _elapsed_ms(started: datetime, completed: datetime) -> int | None:
    """Milliseconds from `started` to `completed`, or None if that is backwards.

    Rows are read in `time` order, so a negative gap means the pairing was
    wrong (a recycled id, a clock step), and no number is better than a
    nonsense one.
    """
    elapsed = (completed - started).total_seconds() * 1000
    return round(elapsed) if elapsed >= 0 else None


def resolve_durations(operations: list[ToolOperation]) -> list[ToolOperation]:
    """Fill in each completion's `duration_ms` from its own start row (#1064).

    A tool call's duration is a property of the PAIR of rows, not of either
    one: nothing in a harness stream carries a per-item timestamp, so the only
    record of how long a call took is the gap between when its start was
    observed and when its completion was. That is why this runs over the whole
    result set instead of inside the per-row converters - a converter sees one
    row and can never answer the question.

    A `duration_ms` the producer measured itself wins: the collector's hook
    path (`collector.client_events.send_tool_completed`) times the call at the
    source, which is closer to the truth than the gap between two writes. This
    only supplies the value for the producers that record none.

    One start pairs with ONE completion, and is consumed by it. Delivery here
    is at-least-once and `agent_events` has no uniqueness constraint, so the
    same completion can be stored twice; the second copy is re-stamped with
    `datetime.now(UTC)` when it is re-recorded (`store_helpers.record_observation`),
    so it lands later than the first. Paired against the start that is still
    open, it reported the whole gap from the call's start to its own
    redelivery - a call that took 1.5s shown as having taken 30s, with nothing
    to mark the number as an artefact of delivery. Consuming the start leaves
    the repeat with nothing to measure from, so it reports `None`: the same
    answer a completion whose start never arrived already gets, and the same
    rule this projection applies everywhere - a duration is reported only
    where two rows genuinely bracket the call.

    A duplicate START needs no such handling and gets none. Redelivered with
    its own timestamp it is identical to the first and last-wins is a no-op;
    re-stamped at a new time it is indistinguishable from a genuine retry of
    the same id, which is the case last-wins exists to serve.

    Operations must arrive in `time` order, which both query paths guarantee
    with `ORDER BY time ASC`.
    """
    open_starts: dict[str, datetime] = {}

    for op in operations:
        if op.tool_use_id is None:
            continue
        if op.operation_type in _CALL_STARTED_TYPES:
            # Last start wins: a retried id measures from the attempt that is
            # actually still open, not the one that already finished.
            open_starts[op.tool_use_id] = op.timestamp
        elif op.operation_type in _CALL_COMPLETED_TYPES and op.duration_ms is None:
            started = open_starts.pop(op.tool_use_id, None)
            if started is not None:
                op.duration_ms = _elapsed_ms(started, op.timestamp)

    return operations


def rows_to_operations(
    rows: Sequence[asyncpg.Record],
    subagent_tool_names: set[str],
    git_event_types: tuple[str, ...],
) -> list[ToolOperation]:
    """Convert a session's rows, in time order, into the timeline read model.

    The whole result set is the unit of conversion rather than the row,
    because `duration_ms` is only knowable across a pair of rows. Callers get
    one answer for a set of rows and do not have to know which fields needed
    more than one row to produce.
    """
    converted = [
        op
        for row in rows
        if (op := row_to_operation(row, subagent_tool_names, git_event_types)) is not None
    ]
    return resolve_durations(converted)
