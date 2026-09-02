"""Tests for pair_tool_durations (issue #1064).

No producer ever writes duration_ms on a tool_execution_completed observation
(ObservabilityCollector.record_tool_completed takes no duration argument, and
neither EventStreamProcessor nor CodexStreamProcessor pass one). These tests
therefore build fixtures the way production data actually looks — a start row
and a completed row that each carry only a timestamp, never duration_ms — and
assert the duration is derived from the gap between them. A fixture that
injects duration_ms directly would pass whether or not pairing exists, which
is exactly the trap this issue warns about.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_adapters.projections.session_tools import ToolOperation
from syn_adapters.projections.session_tools_duration import pair_tool_durations

pytestmark = pytest.mark.unit


def _op(
    operation_type: str,
    tool_use_id: str | None,
    timestamp: datetime,
    duration_ms: int | None = None,
) -> ToolOperation:
    return ToolOperation(
        observation_id=f"{tool_use_id}-{timestamp.isoformat()}",
        tool_name="Bash",
        tool_use_id=tool_use_id,
        operation_type=operation_type,
        timestamp=timestamp,
        success=True if operation_type.endswith(("completed", "stopped")) else None,
        input_preview=None,
        output_preview=None,
        duration_ms=duration_ms,
    )


class TestPairToolDurations:
    def test_derives_duration_from_start_and_completed_timestamps(self) -> None:
        started = _op(
            "tool_execution_started", "toolu_1", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        )
        completed = _op(
            "tool_execution_completed",
            "toolu_1",
            datetime(2026, 1, 1, 12, 0, 0, 250_000, tzinfo=UTC),
        )
        operations = [started, completed]

        pair_tool_durations(operations)

        assert started.duration_ms is None, "duration belongs on the completed row, not started"
        assert completed.duration_ms == 250

    def test_completed_without_matching_start_stays_none_not_zero(self) -> None:
        """Truncated Codex stream: item.completed with no prior item.started."""
        completed = _op(
            "tool_execution_completed",
            "toolu_orphan",
            datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
        )
        operations = [completed]

        pair_tool_durations(operations)

        assert completed.duration_ms is None

    def test_negative_delta_is_rejected_not_reported(self) -> None:
        """Completed timestamp before started: bad data, must not yield a negative duration."""
        started = _op(
            "tool_execution_started", "toolu_2", datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC)
        )
        completed = _op(
            "tool_execution_completed", "toolu_2", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        )
        operations = [started, completed]

        pair_tool_durations(operations)

        assert completed.duration_ms is None

    def test_duration_exceeding_session_bound_is_rejected(self) -> None:
        """A pairing that implies a longer duration than the session itself is implausible."""
        started = _op(
            "tool_execution_started", "toolu_3", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        )
        completed = _op(
            "tool_execution_completed", "toolu_3", datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC)
        )
        operations = [started, completed]

        pair_tool_durations(operations, session_duration_ms=1_000)

        assert completed.duration_ms is None

    def test_duration_within_session_bound_is_kept(self) -> None:
        started = _op(
            "tool_execution_started", "toolu_4", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        )
        completed = _op(
            "tool_execution_completed",
            "toolu_4",
            datetime(2026, 1, 1, 12, 0, 0, 500_000, tzinfo=UTC),
        )
        operations = [started, completed]

        pair_tool_durations(operations, session_duration_ms=60_000)

        assert completed.duration_ms == 500

    def test_producer_supplied_duration_is_not_overwritten(self) -> None:
        """Forward-compatible: if a future producer does write duration_ms, trust it."""
        started = _op(
            "tool_execution_started", "toolu_5", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        )
        completed = _op(
            "tool_execution_completed",
            "toolu_5",
            datetime(2026, 1, 1, 12, 0, 10, tzinfo=UTC),
            duration_ms=42,
        )
        operations = [started, completed]

        pair_tool_durations(operations)

        assert completed.duration_ms == 42

    def test_subagent_stop_pairs_with_subagent_start(self) -> None:
        """Agent/Task tool calls are relabeled to subagent_started/stopped upstream
        (session_tools_dispatch._is_subagent_tool_event) but carry the same
        tool_use_id, so the same pairing logic must derive their duration too."""
        started = _op("subagent_started", "toolu_6", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
        stopped = _op("subagent_stopped", "toolu_6", datetime(2026, 1, 1, 12, 0, 3, tzinfo=UTC))
        operations = [started, stopped]

        pair_tool_durations(operations)

        assert stopped.duration_ms == 3000

    def test_no_tool_use_id_is_untouched(self) -> None:
        """Git operations have no tool_use_id and no duration semantics."""
        git_op = _op("git_commit", None, datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
        operations = [git_op]

        pair_tool_durations(operations)

        assert git_op.duration_ms is None

    def test_multiple_tool_use_ids_do_not_cross_pair(self) -> None:
        ops = [
            _op("tool_execution_started", "a", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)),
            _op("tool_execution_started", "b", datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC)),
            _op(
                "tool_execution_completed",
                "a",
                datetime(2026, 1, 1, 12, 0, 0, 100_000, tzinfo=UTC),
            ),
            _op(
                "tool_execution_completed",
                "b",
                datetime(2026, 1, 1, 12, 0, 1, 900_000, tzinfo=UTC),
            ),
        ]

        pair_tool_durations(ops)

        assert ops[2].duration_ms == 100
        assert ops[3].duration_ms == 900
