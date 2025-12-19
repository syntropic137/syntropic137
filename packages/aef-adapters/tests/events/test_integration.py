"""Integration tests for AgentEventStore with real TimescaleDB.

Run with: uv run pytest -m integration packages/aef-adapters/tests/events/test_integration.py -v

Requires: docker compose -f docker/docker-compose.dev.yaml up timescaledb
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

TIMESCALE_URL = os.getenv(
    "TIMESCALE_URL",
    "postgresql://aef:aef_dev_password@localhost:5433/aef_observability",
)

# Mark all tests as integration - only run when explicitly requested
pytestmark = pytest.mark.integration


@pytest.fixture
def event_store():
    """Create an AgentEventStore for testing."""
    from aef_adapters.events import AgentEventStore

    return AgentEventStore(TIMESCALE_URL)


@pytest.fixture
def session_id():
    """Generate a unique session ID for test isolation."""
    return f"test-session-{uuid4().hex[:8]}"


@pytest.mark.integration
class TestAgentEventStoreIntegration:
    """Integration tests for AgentEventStore with real TimescaleDB."""

    @pytest.mark.asyncio
    async def test_initialize_creates_schema(self, event_store):
        """Test that initialize creates the agent_events table."""
        await event_store.initialize()

        assert event_store.pool is not None
        assert event_store._initialized is True

        # Verify table exists
        async with event_store.pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'agent_events'
                )
                """
            )
            assert result is True

        await event_store.close()

    @pytest.mark.asyncio
    async def test_insert_one_and_query(self, event_store, session_id):
        """Test inserting a single event and querying it back."""
        await event_store.initialize()

        # Insert a test event
        event = {
            "event_type": "tool_execution_started",
            "session_id": session_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "tool_name": "Read",
            "tool_use_id": "test-tool-123",
            "input_preview": '{"path": "/test.txt"}',
        }

        await event_store.insert_one(event)

        # Query it back
        events = await event_store.query(session_id)

        assert len(events) == 1
        assert events[0]["event_type"] == "tool_execution_started"
        assert events[0]["session_id"] == session_id
        assert events[0]["data"]["tool_name"] == "Read"

        await event_store.close()

    @pytest.mark.asyncio
    async def test_insert_batch_performance(self, event_store, session_id):
        """Test batch insert with many events."""
        await event_store.initialize()

        # Create 1000 test events
        events = [
            {
                "event_type": "tool_execution_completed",
                "session_id": session_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "tool_name": f"Tool_{i}",
                "tool_use_id": f"tool-{i}",
                "success": True,
                "duration_ms": i * 10,
            }
            for i in range(1000)
        ]

        # Insert batch
        import time

        start = time.perf_counter()
        count = await event_store.insert_batch(events)
        elapsed = time.perf_counter() - start

        assert count == 1000
        print(f"\nInserted 1000 events in {elapsed:.3f}s ({1000 / elapsed:.0f} events/sec)")

        # Verify count
        events_back = await event_store.query(session_id, limit=2000)
        assert len(events_back) == 1000

        await event_store.close()

    @pytest.mark.asyncio
    async def test_query_by_event_type(self, event_store, session_id):
        """Test querying events filtered by type."""
        await event_store.initialize()

        # Insert mixed event types
        events = [
            {"event_type": "session_started", "session_id": session_id},
            {"event_type": "tool_execution_started", "session_id": session_id, "tool_name": "Read"},
            {
                "event_type": "tool_execution_completed",
                "session_id": session_id,
                "tool_name": "Read",
            },
            {
                "event_type": "tool_execution_started",
                "session_id": session_id,
                "tool_name": "Write",
            },
            {"event_type": "session_completed", "session_id": session_id},
        ]

        await event_store.insert_batch(events)

        # Query only tool_execution_started
        tool_events = await event_store.query(session_id, event_type="tool_execution_started")

        assert len(tool_events) == 2
        assert all(e["event_type"] == "tool_execution_started" for e in tool_events)

        await event_store.close()

    @pytest.mark.asyncio
    async def test_query_by_execution(self, event_store, session_id):
        """Test querying events by execution ID."""
        await event_store.initialize()

        exec_id = f"exec-{uuid4().hex[:8]}"

        events = [
            {"event_type": "session_started", "session_id": session_id, "execution_id": exec_id},
            {
                "event_type": "tool_execution_started",
                "session_id": session_id,
                "execution_id": exec_id,
            },
            {"event_type": "session_completed", "session_id": session_id, "execution_id": exec_id},
        ]

        await event_store.insert_batch(events)

        # Query by execution ID
        exec_events = await event_store.query_by_execution(exec_id)

        assert len(exec_events) == 3
        assert all(e["execution_id"] == exec_id for e in exec_events)

        await event_store.close()

    @pytest.mark.asyncio
    async def test_pagination(self, event_store, session_id):
        """Test query pagination with offset."""
        await event_store.initialize()

        # Insert 50 events
        events = [{"event_type": f"event_{i}", "session_id": session_id} for i in range(50)]
        await event_store.insert_batch(events)

        # Query first page
        page1 = await event_store.query(session_id, limit=20, offset=0)
        assert len(page1) == 20

        # Query second page
        page2 = await event_store.query(session_id, limit=20, offset=20)
        assert len(page2) == 20

        # Pages should be different
        page1_types = {e["event_type"] for e in page1}
        page2_types = {e["event_type"] for e in page2}
        assert page1_types.isdisjoint(page2_types)

        await event_store.close()


class TestEventBufferIntegration:
    """Integration tests for EventBuffer with real storage."""

    @pytest.mark.asyncio
    async def test_buffer_flushes_to_store(self, event_store, session_id):
        """Test that EventBuffer properly flushes to AgentEventStore."""
        from aef_adapters.events import EventBuffer

        await event_store.initialize()

        # Create buffer with small flush size
        buffer = EventBuffer(
            store=event_store,
            flush_size=10,
            flush_interval=0.1,
        )

        await buffer.start()

        # Add 15 events (should trigger one flush at 10)
        for i in range(15):
            await buffer.add(
                {
                    "event_type": "buffer_test",
                    "session_id": session_id,
                    "index": i,
                }
            )

        # Wait for flush
        await asyncio.sleep(0.2)

        # Stop and flush remaining
        await buffer.stop()

        # Verify all events stored
        events = await event_store.query(session_id)
        assert len(events) == 15

        await event_store.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
