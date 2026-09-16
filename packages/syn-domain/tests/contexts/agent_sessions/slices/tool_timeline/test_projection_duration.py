"""The tool timeline must time a call it recorded both ends of (#1064).

This projection has the same shape of the bug the issue names: it took
`duration_ms` straight from the completion observation, which its Lane 2
producer (`ObservabilityCollector.record_tool_completed`) never writes - so
every record read `"duration_ms": None` and `ToolTimeline.avg_duration_ms`
was never anything but None, while the record itself held `started_at` and
was being handed `completed_at` on the same line.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syn_domain.contexts.agent_sessions.slices.tool_timeline.projection import (
    ToolTimelineProjection,
)

pytestmark = pytest.mark.unit

SESSION_ID = "sess-1064"
TOOL_USE_ID = "toolu_1"
STARTED_AT = datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC)
# 1.5s: not a round second, so a wrong unit cannot pass as 1500.
TOOK = timedelta(milliseconds=1500)


class _FakeStore:
    """Minimal in-memory projection store stand-in for testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    async def save(self, projection: str, key: str, data: dict) -> None:
        self._data[key] = data

    async def get(self, projection: str, key: str) -> dict | None:
        return self._data.get(key)

    async def get_all(self, projection: str) -> list[dict]:
        return list(self._data.values())

    async def query(
        self,
        projection: str,
        filters: dict | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        results = list(self._data.values())
        if filters:
            for key, value in filters.items():
                results = [r for r in results if r.get(key) == value]
        return results[offset : offset + limit] if limit else results[offset:]


def _started(timestamp: datetime | str) -> dict:
    return {
        "session_id": SESSION_ID,
        "tool_use_id": TOOL_USE_ID,
        "tool_name": "Bash",
        "timestamp": timestamp,
    }


def _completed(timestamp: datetime | str, **extra: object) -> dict:
    """The completion as its producer really sends it: no duration in sight."""
    return {
        "session_id": SESSION_ID,
        "tool_use_id": TOOL_USE_ID,
        "timestamp": timestamp,
        "success": True,
        **extra,
    }


@pytest.mark.asyncio
async def test_a_completed_call_is_timed_from_the_record_s_own_two_stamps() -> None:
    projection = ToolTimelineProjection(_FakeStore())  # type: ignore[arg-type]  # ProjectionStore stand-in

    await projection.on_tool_execution_started(_started(STARTED_AT))
    await projection.on_tool_execution_completed(_completed(STARTED_AT + TOOK))

    timeline = await projection.get_timeline(SESSION_ID)
    (execution,) = timeline.executions
    assert execution.duration_ms == 1500
    assert timeline.avg_duration_ms == 1500.0


@pytest.mark.asyncio
async def test_stamps_stored_as_text_are_timed_the_same_way() -> None:
    """The store round-trips records as JSON, so a replayed start is a string."""
    projection = ToolTimelineProjection(_FakeStore())  # type: ignore[arg-type]  # ProjectionStore stand-in

    await projection.on_tool_execution_started(_started(STARTED_AT.isoformat()))
    await projection.on_tool_execution_completed(_completed((STARTED_AT + TOOK).isoformat()))

    (execution,) = (await projection.get_timeline(SESSION_ID)).executions
    assert execution.duration_ms == 1500


@pytest.mark.asyncio
async def test_a_duration_the_producer_measured_itself_is_kept() -> None:
    """A measured number beats the gap between two writes, so it is not replaced."""
    projection = ToolTimelineProjection(_FakeStore())  # type: ignore[arg-type]  # ProjectionStore stand-in

    await projection.on_tool_execution_started(_started(STARTED_AT))
    await projection.on_tool_execution_completed(_completed(STARTED_AT + TOOK, duration_ms=250))

    (execution,) = (await projection.get_timeline(SESSION_ID)).executions
    assert execution.duration_ms == 250


@pytest.mark.asyncio
async def test_a_completion_whose_start_was_missed_reports_no_duration() -> None:
    """Nothing to measure from: the record must not claim the call was instant."""
    projection = ToolTimelineProjection(_FakeStore())  # type: ignore[arg-type]  # ProjectionStore stand-in

    await projection.on_tool_execution_completed(_completed(STARTED_AT + TOOK))

    timeline = await projection.get_timeline(SESSION_ID)
    (execution,) = timeline.executions
    assert execution.duration_ms is None
    assert timeline.avg_duration_ms is None
