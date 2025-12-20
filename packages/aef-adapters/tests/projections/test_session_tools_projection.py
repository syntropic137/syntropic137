"""Unit tests for SessionToolsProjection.

These tests verify the projection correctly queries and transforms tool events
from TimescaleDB. They use a real database connection to ensure query correctness.

POKA-YOKE: This test would have caught the event type mismatch bug where we
queried for 'tool_execution_started' but stored 'tool_started'.

Now uses shared constants from aef_shared.events for type safety.
"""

import os
from uuid import uuid4

import pytest

from aef_shared.events import TOOL_COMPLETED, TOOL_STARTED

# Mark all tests as requiring database
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Connection string for TimescaleDB (uses main aef database)
TIMESCALE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://aef:aef_dev_password@localhost:5432/aef",
)


@pytest.fixture
async def event_store():
    """Create a fresh event store for testing."""
    from aef_adapters.events import AgentEventStore

    store = AgentEventStore(TIMESCALE_URL)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def projection(event_store):
    """Get SessionToolsProjection with initialized pool."""
    from aef_adapters.projections import SessionToolsProjection

    return SessionToolsProjection(pool=event_store.pool)


@pytest.fixture
def session_id():
    """Generate unique session ID for test isolation."""
    return str(uuid4())


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
                "event_type": TOOL_STARTED,
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
        assert op.operation_type == TOOL_STARTED
        assert op.tool_name == "Bash"
        assert op.tool_use_id == "toolu_123"

    async def test_get_returns_tool_completed_events(self, projection, event_store, session_id):
        """Projection returns tool_completed events with correct data."""
        # Arrange: Insert a tool_completed event using constant
        await event_store.insert_one(
            event={
                "event_type": TOOL_COMPLETED,
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
        assert op.operation_type == TOOL_COMPLETED
        assert op.tool_use_id == "toolu_456"
        assert op.success is True

    async def test_get_returns_events_in_time_order(self, projection, event_store, session_id):
        """Events are returned in chronological order."""
        # Arrange: Insert events in order using constant
        tools = ["Read", "Write", "Bash"]
        for tool_name in tools:
            await event_store.insert_one(
                event={
                    "event_type": TOOL_STARTED,
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
                "event_type": TOOL_STARTED,
                "session_id": session_1,
                "tool_name": "Session1Tool",
            }
        )
        await event_store.insert_one(
            event={
                "event_type": TOOL_STARTED,
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

        This test uses the shared constants from aef_shared.events to ensure
        both producer and consumer use the SAME values. The old bug was caused
        by hardcoded strings that didn't match.

        Now that we use constants:
        - Producer (WorkflowExecutionEngine) must use TOOL_STARTED, TOOL_COMPLETED
        - Consumer (SessionToolsProjection) uses TOOL_STARTED, TOOL_COMPLETED
        - Type checker catches any mismatches at dev time!

        If this test fails, something is very wrong with the shared constants.
        """
        # Use the shared constants - these are THE source of truth
        producer_event_types = [TOOL_STARTED, TOOL_COMPLETED]

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
