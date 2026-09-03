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

import itertools
from datetime import UTC, datetime
from typing import TypedDict

import pytest

from syn_adapters.projections.session_tools import SessionToolsProjection, ToolOperation
from syn_api.routes.events import _accumulate_tool_stats
from syn_shared.events import (
    GIT_COMMIT,
    SUBAGENT_STARTED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

pytestmark = pytest.mark.unit

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


class _EventData(TypedDict, total=False):
    """The event payload column, with the keys these fixtures set.

    `total=False` is load-bearing: a key the fixture leaves out is genuinely
    absent from the payload, which is the shape `_build_standard_operation`
    reads with `data.get(...)` - and an absent `tool_use_id` is a different
    input from an empty one.
    """

    tool_name: str
    tool_use_id: str
    success: bool
    duration_ms: int
    operation: str
    sha: str


class _Row(TypedDict):
    """A row shaped like the `asyncpg.Record` the projection reads from the DB."""

    event_type: str
    time: datetime
    data: _EventData


def _row(
    event_type: str,
    tool_name: str | None,
    tool_use_id: str | None,
    *,
    success: bool | None = None,
    duration_ms: int | None = None,
) -> _Row:
    """Build one such row; `None` for a field means the key is absent."""
    data: _EventData = {}
    if tool_name is not None:
        data["tool_name"] = tool_name
    if tool_use_id is not None:
        data["tool_use_id"] = tool_use_id
    if success is not None:
        data["success"] = success
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    return {"event_type": event_type, "time": _NOW, "data": data}


def _convert(row: _Row) -> ToolOperation:
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


def test_completion_only_row_with_no_tool_use_id_still_counts_as_one_call() -> None:
    """A row with no usable `tool_use_id` falls back to `observation_id` as
    its identity (see `_accumulate_tool_stats` docstring), not to the old
    per-row `is_started`-gated counting. A started row with no id still
    counts, AND a completion-only row with no id now counts too - it no
    longer produces the impossible `call_count=0, success_count=1` shape
    that the previous version of this test asserted was correct (#1063
    cross-model review finding: the case was considered and the wrong
    answer was pinned down as a regression test).

    This is a genuine change in observed behavior, not a restatement of the
    old default: under the pre-fix code this assertion (`call_count == 1`
    for a completion-only, no-id row) fails with `call_count == 0`.
    """
    started_op = _convert(_row(TOOL_EXECUTION_STARTED, "Bash", None))
    assert started_op.tool_use_id is None

    started_stats = _accumulate_tool_stats([started_op])
    assert started_stats["Bash"]["call_count"] == 1

    completed_op = _convert(_row(TOOL_EXECUTION_COMPLETED, "Bash", None, success=True))
    assert completed_op.tool_use_id is None

    completed_stats = _accumulate_tool_stats([completed_op])
    assert completed_stats["Bash"]["call_count"] == 1
    assert completed_stats["Bash"]["success_count"] == 1


def test_git_operation_row_counts_as_one_call() -> None:
    """Git rows (`row_to_git_operation`) always set `tool_use_id=None` - not
    a rare production edge case but the standing shape for every git event
    in every session. Before this fix, every single git operation reported
    `call_count=0` next to `success_count=1` in `_accumulate_tool_stats`,
    the identical invariant violation as the completion-only no-id case,
    reached through the same `tool_use_id`-missing branch. Reproduced via
    the real `row_to_operation` -> `row_to_git_operation` path, not a
    hand-built `ToolOperation`.
    """
    row: _Row = {
        "event_type": GIT_COMMIT,
        "time": _NOW,
        "data": {"operation": "commit", "sha": "deadbeef"},
    }
    op = SessionToolsProjection()._row_to_operation(row)
    assert op is not None
    assert op.tool_use_id is None

    stats = _accumulate_tool_stats([op])

    assert stats["commit"]["call_count"] == 1
    assert stats["commit"]["success_count"] == 1


def test_duplicate_replayed_no_id_completion_row_counts_as_one_call() -> None:
    """Replay safety for the no-id fallback path: `observation_id` is
    derived deterministically from row content (event type, tool_use_id,
    timestamp), so redelivering the identical no-id completion row twice
    must still contribute exactly one call, not two - the event store can
    and does deliver the same row more than once.
    """
    row = _row(TOOL_EXECUTION_COMPLETED, "Bash", None, success=True)
    operations = [_convert(row), _convert(row)]

    stats = _accumulate_tool_stats(operations)

    assert stats["Bash"]["call_count"] == 1
    assert stats["Bash"]["success_count"] == 1


# ---------------------------------------------------------------------------
# Invariant: call_count >= success_count + error_count, for every row shape.
#
# The bug this rework fixes was a specific test asserting one specific wrong
# output (call_count=0, success_count=1) was correct. An invariant test
# closes that hole structurally: it can't be satisfied by blessing any one
# case, because it runs over the full combinatorial space of row shapes
# below rather than a single hand-picked example.
#
# No property-testing library (e.g. hypothesis) is in this repo's dependency
# tree. Enumerating the shape space by hand below is deterministic, needs no
# new dependency, and is small enough (order of a few hundred cases) to run
# in milliseconds - the property gained from a library here would be
# shrinking on failure, which isn't needed to see which fixed case failed.
# ---------------------------------------------------------------------------

_TOOL_USE_IDS: tuple[str | None, ...] = (None, "", "toolu_shared")
_SUCCESS_VALUES: tuple[bool | None, ...] = (True, False, None)
_ROW_SHAPES: tuple[str, ...] = ("start_only", "completion_only", "paired", "paired_duplicated")


def _build_operations_for_shape(
    shape: str, tool_use_id: str | None, success: bool | None
) -> list[ToolOperation]:
    """Build the operations list for one (shape, tool_use_id, success) case."""
    started_row = _row(TOOL_EXECUTION_STARTED, "Bash", tool_use_id)
    completed_row = _row(
        TOOL_EXECUTION_COMPLETED, "Bash", tool_use_id, success=success, duration_ms=50
    )

    if shape == "start_only":
        return [_convert(started_row)]
    if shape == "completion_only":
        return [_convert(completed_row)]
    if shape == "paired":
        return [_convert(started_row), _convert(completed_row)]
    if shape == "paired_duplicated":
        # Same rows, converted twice each - simulates at-least-once replay.
        return [
            _convert(started_row),
            _convert(started_row),
            _convert(completed_row),
            _convert(completed_row),
        ]
    raise AssertionError(f"unknown shape: {shape}")


@pytest.mark.parametrize(
    ("shape", "tool_use_id", "success"),
    list(itertools.product(_ROW_SHAPES, _TOOL_USE_IDS, _SUCCESS_VALUES)),
)
def test_call_count_invariant_holds_across_row_shapes(
    shape: str, tool_use_id: str | None, success: bool | None
) -> None:
    """call_count must never be less than success_count + error_count,
    regardless of row shape, tool_use_id presence, or outcome - including
    the missing/empty-id, completion-only combination that used to violate
    it (this exact case was `call_count=0, success_count=1` before the fix).
    """
    operations = _build_operations_for_shape(shape, tool_use_id, success)

    stats = _accumulate_tool_stats(operations)
    assert operations, "every shape must produce at least one operation"
    bash_stats = stats["Bash"]

    call_count = bash_stats["call_count"]
    success_count = bash_stats["success_count"]
    error_count = bash_stats["error_count"]

    assert call_count >= success_count + error_count, (
        f"invariant violated for shape={shape!r} tool_use_id={tool_use_id!r} "
        f"success={success!r}: call_count={call_count}, "
        f"success_count={success_count}, error_count={error_count}"
    )
