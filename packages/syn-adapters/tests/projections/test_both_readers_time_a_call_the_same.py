"""The in-memory timeline and the SQL timeline must answer identically (#1064).

A tool call's `duration_ms` is a property of the PAIR of rows: nothing in a
harness stream carries a per-item timestamp, so the only record of how long a
call took is the gap between when its start was observed and when its
completion was. That makes it un-derivable by any converter that sees one row.

The SQL reader runs that pass. The in-memory reader did not, so identical rows
produced a duration through Postgres and `None` in memory - and the in-memory
reader is what tests and offline runs see, which is precisely where a
divergence would otherwise be caught.

Found by cross-model review of the merge that brought #1064 onto this branch:
both constant families survived the conflict correctly, and main's multi-row
behaviour was simply never wired into the new reader.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from syn_adapters.projections.session_timeline_memory import InMemorySessionTimeline

pytestmark = pytest.mark.unit

_SESSION = "sess-duration-agreement"
_STARTED = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)


async def _timeline_with_a_call(gap: timedelta) -> InMemorySessionTimeline:
    timeline = InMemorySessionTimeline()
    await timeline.record_observation(
        session_id=_SESSION,
        observation_type="tool_execution_started",
        data={"tool_name": "Bash", "tool_use_id": "call-1"},
    )
    await timeline.record_observation(
        session_id=_SESSION,
        observation_type="tool_execution_completed",
        data={"tool_name": "Bash", "tool_use_id": "call-1"},
    )
    # The recorder stamps `datetime.now(UTC)` itself, so the pair is separated
    # by real elapsed time rather than a number this test chose. Rewriting the
    # stamps is what lets the assertion be about a known gap.
    observed = timeline._observed
    observed[-2] = replace(observed[-2], time=_STARTED)
    observed[-1] = replace(observed[-1], time=_STARTED + gap)
    return timeline


@pytest.mark.asyncio
async def test_the_in_memory_reader_times_a_call_from_its_own_two_rows() -> None:
    """The producer supplied no duration, so the pair is the only source."""
    timeline = await _timeline_with_a_call(timedelta(milliseconds=1500))

    operations = await timeline.get(_SESSION)

    completed = [o for o in operations if o.operation_type == "tool_execution_completed"]
    assert completed, "the completion row did not survive conversion"
    assert completed[0].duration_ms == 1500


@pytest.mark.asyncio
async def test_a_completion_whose_start_never_arrived_reports_no_duration() -> None:
    """The safe direction: no pair, no number - never a guess."""
    timeline = InMemorySessionTimeline()
    await timeline.record_observation(
        session_id=_SESSION,
        observation_type="tool_execution_completed",
        data={"tool_name": "Bash", "tool_use_id": "orphan"},
    )

    operations = await timeline.get(_SESSION)

    assert [o.duration_ms for o in operations] == [None]
