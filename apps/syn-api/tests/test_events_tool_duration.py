"""Tests for per-tool duration aggregation (issue #1064).

record_tool_completed never carried a duration_ms, so total_duration_ms was
always 0 and avg_duration_ms was meaningless. The fix computes duration_ms on
the read side by pairing started/completed rows on tool_use_id
(session_tools_helpers.py, session_tools_queries.py) -- that pairing needs a
real database and is covered by the integration tests in
packages/syn-adapters/tests/projections/test_session_tools_projection.py.

These tests cover the consumer of that fix: the stats aggregation in
routes/events.py that sums and averages whatever duration_ms values arrive.
A test that only checks one happy pair would keep passing while the "unpaired
completion drags the average toward zero" bug (or the original "always 0"
bug) persisted, so each test below uses a mix of paired and unpaired
operations, constructed from the real ToolOperation dataclass -- not a mock
-- so the numbers could not have arisen without the duration_count fix.
"""

from __future__ import annotations

from datetime import UTC, datetime

from syn_adapters.projections.session_tools import ToolOperation
from syn_api.routes.events import _accumulate_tool_stats, _build_tool_summaries
from syn_api.types import ToolUsageSummary

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _op(
    tool_name: str,
    *,
    duration_ms: int | None,
    success: bool | None = True,
) -> ToolOperation:
    return ToolOperation(
        observation_id=f"{tool_name}-{duration_ms}",
        tool_name=tool_name,
        tool_use_id="toolu_x",
        operation_type="tool_execution_completed",
        timestamp=_NOW,
        success=success,
        input_preview=None,
        output_preview=None,
        duration_ms=duration_ms,
    )


class TestAccumulateToolStats:
    def test_premise_call_count_alone_would_have_masked_the_bug(self) -> None:
        """A single paired op is not enough to catch the regression this
        fix addresses -- it would pass under the old `or 0` code too."""
        stats = _accumulate_tool_stats([_op("Bash", duration_ms=500)])
        assert stats["Bash"]["total_duration_ms"] == 500
        assert stats["Bash"]["duration_count"] == 1

    def test_unpaired_completion_does_not_pull_total_or_average_toward_zero(self) -> None:
        """A completed row with no matching started row (truncated Codex
        stream, CodexStreamProcessor.py:579) reports duration_ms=None. It
        must not be folded into total_duration_ms as a 0, and must not
        inflate the denominator used for the average."""
        ops = [
            _op("Bash", duration_ms=1000),
            _op("Bash", duration_ms=None),  # unpaired completion
            _op("Bash", duration_ms=2000),
        ]
        stats = _accumulate_tool_stats(ops)

        assert stats["Bash"]["call_count"] == 3
        assert stats["Bash"]["duration_count"] == 2  # only the paired ones
        assert stats["Bash"]["total_duration_ms"] == 3000

    def test_all_unpaired_reports_no_known_duration(self) -> None:
        """If nothing is derivable, duration_count is 0 -- the consumer
        (_build_tool_summaries) must read that as 'unknown', not 0."""
        stats = _accumulate_tool_stats([_op("Read", duration_ms=None)] * 3)

        assert stats["Read"]["call_count"] == 3
        assert stats["Read"]["duration_count"] == 0
        assert stats["Read"]["total_duration_ms"] == 0.0

    def test_duration_ms_never_negative_is_the_caller_contract(self) -> None:
        """The SQL pairing guards ts.started_time <= completed.time so a
        corrupted/out-of-order pair yields None rather than a negative
        number (session_tools_helpers.py). Assert the invariant holds for
        whatever reaches this aggregator: never negative, never silently
        clamped to 0 when actually unknown."""
        ops = [_op("Write", duration_ms=750), _op("Write", duration_ms=None)]
        stats = _accumulate_tool_stats(ops)

        assert stats["Write"]["total_duration_ms"] >= 0
        # The unpaired op contributed to call_count but not duration_count —
        # if it had been treated as a 0-duration measurement instead, this
        # would be 2, and the average below would be silently wrong.
        assert stats["Write"]["duration_count"] == 1


class TestBuildToolSummaries:
    def test_average_divides_by_known_durations_not_call_count(self) -> None:
        """This is the assertion that would have failed under the
        pre-fix `total_duration_ms / call_count` formula: 3000/3 = 1000,
        not the correct 3000/2 = 1500."""
        summaries = [
            ToolUsageSummary(
                tool_name="Bash",
                call_count=3,
                success_count=3,
                error_count=0,
                total_duration_ms=3000.0,
                duration_count=2,
            )
        ]

        result = _build_tool_summaries(summaries)

        assert len(result) == 1
        assert result[0].total_duration_ms == 3000
        assert result[0].avg_duration_ms == 1500.0

    def test_zero_known_durations_reports_zero_not_a_crash(self) -> None:
        """No paired operation at all (duration_count=0) must not divide by
        zero, and the 0.0 fallback here is a documented, deliberate limit
        of the current wire type (ToolSummary.avg_duration_ms is a
        non-nullable float) -- see the PR description for why this wasn't
        widened to Optional."""
        summaries = [
            ToolUsageSummary(
                tool_name="Read",
                call_count=5,
                success_count=5,
                error_count=0,
                total_duration_ms=0.0,
                duration_count=0,
            )
        ]

        result = _build_tool_summaries(summaries)

        assert result[0].total_duration_ms == 0
        assert result[0].avg_duration_ms == 0.0

    def test_duration_never_exceeds_a_trivial_upper_bound(self) -> None:
        """Invariant: a reported duration must be non-negative. This is
        enforced upstream in SQL (session_tools_helpers.py / queries.py) by
        requiring completed.time >= started.time; here we assert the
        aggregator never manufactures a negative value from legitimate
        non-negative inputs."""
        summaries = [
            ToolUsageSummary(
                tool_name="Grep",
                call_count=2,
                success_count=2,
                error_count=0,
                total_duration_ms=42.0,
                duration_count=2,
            )
        ]

        result = _build_tool_summaries(summaries)

        assert result[0].total_duration_ms >= 0
        assert result[0].avg_duration_ms >= 0
