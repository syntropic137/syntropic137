"""Tests for issue #1064's actual consumer: the tool-duration aggregation in
apps/syn-api/src/syn_api/routes/events.py.

_accumulate_tool_stats and get_session_tools_endpoint are what read
ToolOperation.duration_ms and turn it into total_duration_ms/avg_duration_ms.
That is the hop this issue is about: the field can be populated correctly on
ToolOperation and still be dropped or silently zeroed one hop later here, at
the sum-and-divide step, so this exercises that step directly rather than
re-checking the object session_tools_duration.py already covers.

Fixtures below build ToolOperation instances the way
session_tools_duration.pair_tool_durations actually produces them (derived
from a started/completed timestamp gap) — not a literal duration_ms value
a producer never writes — so a fixture that already looks like the fixed
answer can't be the reason these pass.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_adapters.projections.session_tools import ToolOperation
from syn_adapters.projections.session_tools_duration import pair_tool_durations
from syn_api.routes.events import _accumulate_tool_stats, get_session_tool_summary
from syn_api.types import Err

pytestmark = pytest.mark.unit


def _op(
    operation_type: str,
    tool_use_id: str,
    tool_name: str,
    timestamp: datetime,
) -> ToolOperation:
    return ToolOperation(
        observation_id=f"{tool_use_id}-{timestamp.isoformat()}",
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        operation_type=operation_type,
        timestamp=timestamp,
        success=True if operation_type == "tool_execution_completed" else None,
        input_preview=None,
        output_preview=None,
        duration_ms=None,  # never producer-supplied — see module docstring
    )


def _derived_bash_call_pair() -> list[ToolOperation]:
    """One Bash call: started, then completed 300ms later. duration_ms is
    unset on both until pair_tool_durations derives it from the gap."""
    started = _op(
        "tool_execution_started", "toolu_1", "Bash", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    )
    completed = _op(
        "tool_execution_completed",
        "toolu_1",
        "Bash",
        datetime(2026, 1, 1, 12, 0, 0, 300_000, tzinfo=UTC),
    )
    operations = [started, completed]
    pair_tool_durations(operations)
    return operations


class TestAccumulateToolStats:
    def test_total_duration_ms_is_nonzero_after_pairing(self) -> None:
        """The regression this issue names directly: total_duration_ms must
        not be silently 0 once the projection has derived a real duration."""
        stats = _accumulate_tool_stats(_derived_bash_call_pair())

        assert stats["Bash"]["total_duration_ms"] == 300

    def test_started_row_contributes_zero_not_none_to_sum(self) -> None:
        """A started row has no duration of its own; it must add 0 to the
        sum rather than raising on a None duration_ms."""
        stats = _accumulate_tool_stats(_derived_bash_call_pair())

        # Both the started and completed rows count as calls for this tool;
        # only the completed row's derived duration contributes to the sum.
        assert stats["Bash"]["call_count"] == 2
        assert stats["Bash"]["total_duration_ms"] == 300

    def test_orphaned_completed_row_contributes_zero_but_stays_derivable_as_missing(
        self,
    ) -> None:
        """A truncated-stream completed row (no start) has duration_ms=None
        after pairing; the sum must treat that as 0 contribution, not crash,
        and must not be conflated with an actual 0ms call at the ToolOperation
        level (duration_ms stays None there — see test_session_tools_duration.py)."""
        orphan = _op(
            "tool_execution_completed",
            "toolu_orphan",
            "Bash",
            datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
        )
        operations = [orphan]
        pair_tool_durations(operations)

        assert orphan.duration_ms is None
        stats = _accumulate_tool_stats(operations)
        assert stats["Bash"]["total_duration_ms"] == 0


class TestGetSessionToolSummary:
    async def test_tool_summary_reports_nonzero_duration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end through the actual HTTP-facing service function: a
        session whose events were paired must yield a ToolUsageSummary with
        a real total_duration_ms, not the 0 issue #1064 reports."""
        operations = _derived_bash_call_pair()

        class _FakeSessionTools:
            async def get(self, session_id: str) -> list[ToolOperation]:
                return operations

        class _FakeManager:
            session_tools = _FakeSessionTools()

        import syn_api.routes.events as events_module

        monkeypatch.setattr(events_module, "ensure_connected", _noop_async)
        monkeypatch.setattr(events_module, "get_projection_mgr", lambda: _FakeManager())

        result = await get_session_tool_summary(session_id="session-123")

        assert not isinstance(result, Err), getattr(result, "message", None)
        summaries = {s.tool_name: s for s in result.value}
        assert summaries["Bash"].total_duration_ms == 300


async def _noop_async() -> None:
    return None
