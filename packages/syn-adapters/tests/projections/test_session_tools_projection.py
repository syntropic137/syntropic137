"""Integration tests for SessionToolsProjection.

These tests verify the projection correctly queries and transforms tool events
from TimescaleDB. They use a real database connection to ensure query correctness.

Uses shared test_infrastructure fixture (ADR-034) which auto-detects:
- test-stack (just test-stack) on port 15432
- testcontainers fallback with dynamic ports

POKA-YOKE: This test would have caught the event type mismatch bug where we
queried for 'tool_execution_started' but stored 'tool_started'.

Now uses shared constants from syn_shared.events for type safety.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from syn_shared.events import TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

# Mark all tests as requiring database
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _dt(*args: int) -> datetime:
    """Build a UTC datetime for deterministic event timestamps."""
    return datetime(*args, tzinfo=UTC)


@pytest.fixture
async def event_store(test_infrastructure):
    """Create a fresh event store using shared test infrastructure."""
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def projection(event_store):
    """Get SessionToolsProjection with initialized pool."""
    from syn_adapters.projections import SessionToolsProjection

    return SessionToolsProjection(pool=event_store.pool)


@pytest.fixture
def session_id():
    """Generate unique session ID for test isolation."""
    return str(uuid4())


@pytest.mark.integration
class TestSessionToolsProjection:
    """Tests for SessionToolsProjection."""

    async def test_get_returns_empty_for_unknown_session(self, projection):
        """Projection returns empty list for session with no events."""
        result = await projection.get("nonexistent-session-id")
        assert result == []

    async def test_get_returns_tool_started_events(self, projection, event_store, session_id):
        """Projection returns tool_started events with correct data."""
        # Arrange: Insert a tool_started event using constant
        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_STARTED,
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_use_id": "toolu_123",
                "input_preview": '{"command": "ls -la"}',
            }
        )

        # Act
        result = await projection.get(session_id)

        # Assert
        assert len(result) == 1
        op = result[0]
        assert op.operation_type == TOOL_EXECUTION_STARTED
        assert op.tool_name == "Bash"
        assert op.tool_use_id == "toolu_123"

    async def test_get_returns_tool_completed_events(self, projection, event_store, session_id):
        """Projection returns tool_completed events with correct data."""
        # Arrange: Insert a tool_completed event using constant
        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_COMPLETED,
                "session_id": session_id,
                "tool_use_id": "toolu_456",
                "success": True,
            }
        )

        # Act
        result = await projection.get(session_id)

        # Assert
        assert len(result) == 1
        op = result[0]
        assert op.operation_type == TOOL_EXECUTION_COMPLETED
        assert op.tool_use_id == "toolu_456"
        assert op.success is True

    async def test_get_returns_events_in_time_order(self, projection, event_store, session_id):
        """Events are returned in chronological order."""
        # Arrange: Insert events in order using constant
        tools = ["Read", "Write", "Bash"]
        for tool_name in tools:
            await event_store.insert_one(
                event={
                    "event_type": TOOL_EXECUTION_STARTED,
                    "session_id": session_id,
                    "tool_name": tool_name,
                    "tool_use_id": f"toolu_{tool_name}",
                }
            )

        # Act
        result = await projection.get(session_id)

        # Assert
        assert len(result) == 3
        assert [op.tool_name for op in result] == tools

    async def test_get_filters_by_session_id(self, projection, event_store):
        """Events from other sessions are not returned."""
        session_1 = str(uuid4())
        session_2 = str(uuid4())

        # Arrange: Insert events for two sessions using constant
        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_STARTED,
                "session_id": session_1,
                "tool_name": "Session1Tool",
            }
        )
        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_STARTED,
                "session_id": session_2,
                "tool_name": "Session2Tool",
            }
        )

        # Act
        result = await projection.get(session_1)

        # Assert
        assert len(result) == 1
        assert result[0].tool_name == "Session1Tool"

    async def test_event_type_names_match_producer(self, projection, event_store, session_id):
        """CRITICAL: Verify event types match what WorkflowExecutionEngine produces.

        This test uses the shared constants from syn_shared.events to ensure
        both producer and consumer use the SAME values. The old bug was caused
        by hardcoded strings that didn't match.

        Now that we use constants:
        - Producer (WorkflowExecutionEngine) must use TOOL_EXECUTION_STARTED, TOOL_EXECUTION_COMPLETED
        - Consumer (SessionToolsProjection) uses TOOL_EXECUTION_STARTED, TOOL_EXECUTION_COMPLETED
        - Type checker catches any mismatches at dev time!

        If this test fails, something is very wrong with the shared constants.
        """
        # Use the shared constants - these are THE source of truth
        producer_event_types = [TOOL_EXECUTION_STARTED, TOOL_EXECUTION_COMPLETED]

        for event_type in producer_event_types:
            await event_store.insert_one(
                event={
                    "event_type": event_type,
                    "session_id": session_id,
                    "tool_name": "TestTool",
                    "tool_use_id": f"toolu_{event_type}",
                }
            )

        # Projection should find both events
        result = await projection.get(session_id)

        # CRITICAL ASSERTION: All producer event types must be queryable
        result_types = {op.operation_type for op in result}
        assert result_types == set(producer_event_types), (
            f"Event type mismatch! Producer emits {producer_event_types} "
            f"but projection only found {result_types}"
        )


@pytest.mark.integration
class TestToolDurationPairing:
    """Regression tests for issue #1064: record_tool_completed never carried
    a duration, so total_duration_ms/avg_duration_ms were always 0.

    The fix computes duration_ms on the READ side by pairing started/
    completed rows on tool_use_id, since both are already stored with
    timestamps -- no producer change needed, and it's retroactive for
    sessions already in the store. These tests exercise the actual SQL in
    session_tools_helpers.py (get()), not a mock of it, since the defect
    lives in the query text itself.
    """

    async def test_paired_started_and_completed_yields_positive_duration(
        self, projection, event_store, session_id
    ):
        """A normal paired start/complete produces a correct, positive
        duration_ms — the case the original 'always 0' bug broke entirely."""
        t0 = _dt(2024, 1, 1, 12, 0, 0)
        t1 = t0 + timedelta(milliseconds=750)

        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_STARTED,
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_use_id": "toolu_paired",
                "time": t0,
            }
        )
        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_COMPLETED,
                "session_id": session_id,
                "tool_use_id": "toolu_paired",
                "success": True,
                "time": t1,
            }
        )

        result = await projection.get(session_id)
        completed = [op for op in result if op.is_completed]

        assert len(completed) == 1
        assert completed[0].duration_ms == 750
        assert completed[0].duration_ms >= 0

    async def test_completed_without_started_has_no_duration(
        self, projection, event_store, session_id
    ):
        """A truncated stream (CodexStreamProcessor.py:579) can deliver a
        completion with no matching start. The row must report
        duration_ms=None, not a fabricated 0 that looks like a real
        measurement."""
        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_COMPLETED,
                "session_id": session_id,
                "tool_use_id": "toolu_orphan_completion",
                "success": True,
            }
        )

        result = await projection.get(session_id)
        completed = [op for op in result if op.is_completed]

        assert len(completed) == 1
        assert completed[0].duration_ms is None

    async def test_out_of_order_timestamps_do_not_produce_negative_duration(
        self, projection, event_store, session_id
    ):
        """A corrupted/out-of-order pair (completed timestamp before
        started) must not silently produce a negative duration -- it must
        read as unknown (None), the same as a missing pair."""
        t0 = _dt(2024, 1, 1, 12, 0, 5)
        t_before = t0 - timedelta(seconds=1)

        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_STARTED,
                "session_id": session_id,
                "tool_name": "Write",
                "tool_use_id": "toolu_out_of_order",
                "time": t0,
            }
        )
        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_COMPLETED,
                "session_id": session_id,
                "tool_use_id": "toolu_out_of_order",
                "success": True,
                "time": t_before,
            }
        )

        result = await projection.get(session_id)
        completed = [op for op in result if op.is_completed]

        assert len(completed) == 1
        assert completed[0].duration_ms is None, (
            "out-of-order started/completed pair must not yield a negative duration"
        )

    async def test_duration_never_exceeds_the_session_span(
        self, projection, event_store, session_id
    ):
        """Invariant: a reported duration must not exceed the session's own
        duration. Derived directly from real timestamps within the session's
        span, so this holds by construction unless the pairing logic reaches
        outside the tool's own start/complete pair."""
        session_start = _dt(2024, 1, 1, 9, 0, 0)
        session_end = session_start + timedelta(minutes=10)

        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_STARTED,
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_use_id": "toolu_span",
                "time": session_start + timedelta(seconds=1),
            }
        )
        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_COMPLETED,
                "session_id": session_id,
                "tool_use_id": "toolu_span",
                "success": True,
                "time": session_start + timedelta(seconds=30),
            }
        )

        result = await projection.get(session_id)
        completed = [op for op in result if op.is_completed]
        session_span_ms = (session_end - session_start).total_seconds() * 1000

        assert len(completed) == 1
        assert completed[0].duration_ms is not None
        assert 0 <= completed[0].duration_ms <= session_span_ms

    async def test_query_path_pairs_duration_same_as_get(self, projection, event_store, session_id):
        """The filtered query() path (session_tools_queries.py) must agree
        with get() on duration_ms -- it has its own SQL and would otherwise
        silently diverge (issue #1064 hop 2)."""
        execution_id = str(uuid4())
        t0 = _dt(2024, 1, 1, 15, 0, 0)
        t1 = t0 + timedelta(milliseconds=300)

        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_STARTED,
                "session_id": session_id,
                "tool_name": "Read",
                "tool_use_id": "toolu_query_path",
                "time": t0,
            },
            execution_id=execution_id,
        )
        await event_store.insert_one(
            event={
                "event_type": TOOL_EXECUTION_COMPLETED,
                "session_id": session_id,
                "tool_use_id": "toolu_query_path",
                "success": True,
                "time": t1,
            },
            execution_id=execution_id,
        )

        result = await projection.query(execution_id=execution_id)
        completed = [op for op in result if op.is_completed]

        assert len(completed) == 1
        assert completed[0].duration_ms == 300
