"""Derive per-tool duration by pairing started/completed operations.

No producer writes ``duration_ms`` on completion (issue #1064): neither
``EventStreamProcessor`` (Claude) nor ``CodexStreamProcessor`` pass it to
``ObservabilityCollector.record_tool_completed``. Both events carry a
timestamp and share ``tool_use_id`` though, so the duration is derivable
on the read side — retroactively, for sessions already stored — by pairing
each completed row with its matching started row.

A completed row with no matching started row (e.g. a truncated Codex
stream — see CodexStreamProcessor._handle_command_execution_completed,
where item.completed can arrive without a prior item.started) must read
as a missing duration, not a zero one.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_shared.events import (
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    from datetime import datetime

    from syn_adapters.projections.session_tools import ToolOperation

logger = logging.getLogger(__name__)

_START_TYPES = frozenset({TOOL_EXECUTION_STARTED, SUBAGENT_STARTED})
_END_TYPES = frozenset({TOOL_EXECUTION_COMPLETED, SUBAGENT_STOPPED})


def pair_tool_durations(
    operations: list[ToolOperation],
    session_duration_ms: float | None = None,
) -> None:
    """Fill in ``duration_ms`` on completed operations, in place.

    For each end operation (tool_execution_completed / subagent_stopped)
    with a ``tool_use_id``, look up the earliest start operation
    (tool_execution_started / subagent_started) sharing that id within the
    same result set and derive the elapsed time between their timestamps.

    Invariant: a reported duration is always non-negative and never exceeds
    ``session_duration_ms`` (when known). Either violation, or the absence
    of a matching start row, leaves ``duration_ms`` as ``None`` — never 0.

    An operation that already has a producer-supplied ``duration_ms`` is
    left untouched (forward-compatible with a future producer change).
    """
    start_times: dict[str, datetime] = {}
    for op in operations:
        if op.operation_type in _START_TYPES and op.tool_use_id:
            start_times.setdefault(op.tool_use_id, op.timestamp)

    for op in operations:
        if op.operation_type not in _END_TYPES or not op.tool_use_id:
            continue
        if op.duration_ms is not None:
            continue

        start = start_times.get(op.tool_use_id)
        if start is None:
            # Truncated stream: no derivable duration. Leave as None.
            continue

        delta_ms = (op.timestamp - start).total_seconds() * 1000
        if delta_ms < 0:
            logger.warning(
                "Derived negative tool duration for tool_use_id=%s (%.1fms); "
                "dropping rather than reporting a nonsensical value",
                op.tool_use_id,
                delta_ms,
            )
            continue
        if session_duration_ms is not None and delta_ms > session_duration_ms:
            logger.warning(
                "Derived tool duration for tool_use_id=%s (%.1fms) exceeds "
                "session duration (%.1fms); dropping as an implausible pairing",
                op.tool_use_id,
                delta_ms,
                session_duration_ms,
            )
            continue

        op.duration_ms = round(delta_ms)
