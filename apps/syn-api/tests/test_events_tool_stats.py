"""Regression tests for tool call aggregation in events.py.

Covers issue #1061: `_accumulate_tool_stats` counted every observation row
(both `tool_execution_started` and `tool_execution_completed`) toward
`call_count`, double-counting every finished tool call.

Also covers #1063: counting only `is_started` rows (the #1061 fix) undercounts
two production shapes that the projection actually produces. Those shapes
only appear after `row_to_operation`/`row_to_subagent_operation` have run —
a hand-built `ToolOperation` can't reproduce the subagent rewrite, and
skipping the conversion is exactly how the two #1063 regressions passed
review the first time. So the fixtures for those cases build plain dict rows
(shaped like an `asyncpg.Record`, per the existing pattern in
`test_session_tools_regression.py`) and run them through the real
`SessionToolsProjection._row_to_operation`, rather than constructing
`ToolOperation` directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from syn_adapters.projections.session_tools import SessionToolsProjection, ToolOperation
from syn_api.routes.events import _accumulate_tool_stats
from syn_shared.events import SUBAGENT_STARTED, TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


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


def _row(
    event_type: str,
    tool_name: str | None,
    tool_use_id: str | None,
    *,
    success: bool | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    """A dict shaped like the `asyncpg.Record` the projection reads from the DB.

    Omitting `tool_use_id` (rather than passing "") reproduces the real
    absent-key shape `_build_standard_operation` sees via `data.get(...)`.
    """
    data: dict[str, Any] = {}
    if tool_name is not None:
        data["tool_name"] = tool_name
    if tool_use_id is not None:
        data["tool_use_id"] = tool_use_id
    if success is not None:
        data["success"] = success
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    return {"event_type": event_type, "time": _NOW, "data": data}


def _convert(row: dict[str, Any]) -> ToolOperation:
    """Run a row through the real projection conversion, not a hand-built object."""
    op = SessionToolsProjection()._row_to_operation(row)
    assert op is not None
    return op


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


def test_completion_only_row_counts_as_one_call() -> None:
    """#1063 blocker 1: a completion with no matching start must still count.

    CodexStreamProcessor._handle_command_execution_completed explicitly
    supports this for a truncated stream: item.completed is recorded even
    when item.started never arrived. Gating call_count on `is_started` alone
    makes this row report call_count=0 next to success_count=1 - an
    impossible summary. This value (call_count == 1 for a completion-only
    row) could not arise from the `is_started`-only guard; it requires the
    tool_use_id fallback.
    """
    op = _convert(_row(TOOL_EXECUTION_COMPLETED, "Bash", "toolu_orphan", success=True))

    stats = _accumulate_tool_stats([op])

    assert stats["Bash"]["call_count"] == 1
    assert stats["Bash"]["success_count"] == 1
    assert stats["Bash"]["error_count"] == 0


def test_agent_call_via_real_projection_conversion_counts_as_one() -> None:
    """#1063 blocker 2: an Agent/Task call must count, even though the
    projection rewrites its started row's operation_type away from
    tool_execution_started before this function ever sees it.

    Built from raw dict rows run through the real
    row_to_operation -> row_to_subagent_operation path (not a hand-built
    ToolOperation), because that rewrite is exactly what a hand-built
    fixture bypasses and exactly where this regression lived.
    """
    started_op = _convert(_row(TOOL_EXECUTION_STARTED, "Agent", "toolu_sub_1"))
    completed_op = _convert(
        _row(TOOL_EXECUTION_COMPLETED, "Agent", "toolu_sub_1", success=True, duration_ms=2000)
    )

    # Confirm the rewrite actually happened, i.e. this fixture is exercising
    # the regression and not silently degrading to the standard-tool path.
    assert started_op.operation_type == SUBAGENT_STARTED
    assert not started_op.is_started

    stats = _accumulate_tool_stats([started_op, completed_op])

    assert stats["Agent"]["call_count"] == 1
    assert stats["Agent"]["success_count"] == 1
    assert stats["Agent"]["total_duration_ms"] == 2000


def test_duplicate_replayed_rows_count_as_one_call() -> None:
    """At-least-once delivery can replay the same lifecycle row.

    Two identical started rows and two identical completed rows for the same
    tool_use_id must still contribute exactly one call, one success, and one
    call's worth of duration - not two of each.
    """
    started_row = _row(TOOL_EXECUTION_STARTED, "Bash", "toolu_dup")
    completed_row = _row(
        TOOL_EXECUTION_COMPLETED, "Bash", "toolu_dup", success=True, duration_ms=80
    )
    operations = [
        _convert(started_row),
        _convert(started_row),
        _convert(completed_row),
        _convert(completed_row),
    ]

    stats = _accumulate_tool_stats(operations)

    assert stats["Bash"]["call_count"] == 1
    assert stats["Bash"]["success_count"] == 1
    assert stats["Bash"]["total_duration_ms"] == 80


def test_row_with_no_tool_use_id_falls_back_to_per_row_started_gating() -> None:
    """A row with no usable tool_use_id can't be deduplicated by identity, so
    it keeps the pre-#1063 per-row, is_started-gated behavior: a started row
    with no id still counts, but this means a hypothetical completion-only
    row with no id would NOT count (the same impossible-summary shape as
    blocker 1, just for the one production shape that has no identity to
    fall back on). Pinning both halves down explicitly rather than leaving
    the no-id case implicit.
    """
    started_op = _convert(_row(TOOL_EXECUTION_STARTED, "Bash", None))
    assert started_op.tool_use_id is None

    started_stats = _accumulate_tool_stats([started_op])
    assert started_stats["Bash"]["call_count"] == 1

    completed_op = _convert(_row(TOOL_EXECUTION_COMPLETED, "Bash", None, success=True))
    assert completed_op.tool_use_id is None

    completed_stats = _accumulate_tool_stats([completed_op])
    assert completed_stats["Bash"]["call_count"] == 0
    assert completed_stats["Bash"]["success_count"] == 1
