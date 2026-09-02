"""Regression tests for tool call aggregation in events.py.

Covers issue #1061: `_accumulate_tool_stats` counted every observation row
(both `tool_execution_started` and `tool_execution_completed`) toward
`call_count`, double-counting every finished tool call.
"""

from __future__ import annotations

from datetime import datetime, timezone

from syn_adapters.projections.session_tools import ToolOperation
from syn_shared.events import TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

from syn_api.routes.events import _accumulate_tool_stats

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _started(tool_name: str, tool_use_id: str) -> ToolOperation:
    return ToolOperation(
        observation_id=f"{tool_use_id}-started",
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        operation_type=TOOL_EXECUTION_STARTED,
        timestamp=_NOW,
        success=None,
        input_preview=None,
        output_preview=None,
        duration_ms=None,
    )


def _completed(
    tool_name: str, tool_use_id: str, *, success: bool, duration_ms: int
) -> ToolOperation:
    return ToolOperation(
        observation_id=f"{tool_use_id}-completed",
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        operation_type=TOOL_EXECUTION_COMPLETED,
        timestamp=_NOW,
        success=success,
        input_preview=None,
        output_preview=None,
        duration_ms=duration_ms,
    )


def test_one_completed_tool_call_counts_once() -> None:
    """A single real tool call (started row + completed row, same tool_use_id)
    must contribute call_count == 1, not 2.

    This is the exact shape from the issue's measurements: every session
    showed a healthy tool at a 2:1 started:actual ratio because both rows
    incremented call_count unconditionally.
    """
    operations = [
        _started("Bash", "toolu_1"),
        _completed("Bash", "toolu_1", success=True, duration_ms=100),
    ]

    stats = _accumulate_tool_stats(operations)

    assert stats["Bash"]["call_count"] == 1
    assert stats["Bash"]["success_count"] == 1
    assert stats["Bash"]["error_count"] == 0
    assert stats["Bash"]["total_duration_ms"] == 100


def test_avg_duration_ms_denominator_matches_true_call_count() -> None:
    """The consumer of call_count (avg_duration_ms) must divide by the true
    number of calls, not the doubled row count. Regression for the halved
    averages reported in issue #1061.
    """
    operations = [
        _started("Read", "toolu_a"),
        _completed("Read", "toolu_a", success=True, duration_ms=200),
        _started("Read", "toolu_b"),
        _completed("Read", "toolu_b", success=True, duration_ms=100),
    ]

    stats = _accumulate_tool_stats(operations)

    call_count = stats["Read"]["call_count"]
    avg_duration_ms = stats["Read"]["total_duration_ms"] / call_count

    assert call_count == 2
    assert avg_duration_ms == 150


def test_hung_call_with_no_completed_row_is_still_counted() -> None:
    """A tool call that started but never completed (hung) must still be
    visible in call_count, even though it has no success/error outcome yet.
    This is the other half of issue #1061: hung calls were invisible.
    """
    operations = [_started("Bash", "toolu_hung")]

    stats = _accumulate_tool_stats(operations)

    assert stats["Bash"]["call_count"] == 1
    assert stats["Bash"]["success_count"] == 0
    assert stats["Bash"]["error_count"] == 0
