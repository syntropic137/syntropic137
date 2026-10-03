"""Integration tests for AgentEventStore with real TimescaleDB.

Run with: uv run pytest -m integration packages/syn-adapters/tests/events/test_integration.py -v

Uses shared test_infrastructure fixture (ADR-034) which auto-detects:
- test-stack (just test-stack) on port 15432
- testcontainers fallback with dynamic ports
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from syn_domain.storable_text import pg_safe

# Use centralized event type constants - NO hardcoded strings!
from syn_shared.events import TOOL_EXECUTION_STARTED

# Use typed factories for type-safe event creation
from syn_shared.events.factories import (
    session_completed,
    session_started,
    tool_completed,
    tool_started,
)

# Mark all tests as integration - only run when explicitly requested
pytestmark = pytest.mark.integration


@pytest.fixture
async def event_store(test_infrastructure):
    """Create an AgentEventStore using shared test infrastructure."""
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    yield store
    await store.close()


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

    @pytest.mark.asyncio
    async def test_insert_one_and_query(self, event_store, session_id):
        """Test inserting a single event and querying it back."""
        await event_store.initialize()

        # Insert a test event using type-safe factory
        event = tool_started(
            session_id=session_id,
            tool_name="Read",
            tool_use_id="test-tool-123",
            input_preview='{"path": "/test.txt"}',
        )

        await event_store.insert_one(event)

        # Query it back
        events = await event_store.query(session_id)

        assert len(events) == 1
        assert events[0]["event_type"] == TOOL_EXECUTION_STARTED
        assert events[0]["session_id"] == session_id
        assert events[0]["data"]["tool_name"] == "Read"

    @pytest.mark.asyncio
    async def test_hostile_agent_output_does_not_fail_the_write(self, event_store, session_id):
        """A real NUL and a real lone surrogate, against a real Postgres (#1241).

        This is the one that runs the actual rejection: unit tests assert on the
        values handed to the driver, and only a live server can say whether it
        accepts them. Unpatched, this raises
        `unsupported Unicode escape sequence ... cannot be converted to text`
        and, in production, took the whole execution with it.
        """
        await event_store.initialize()

        hostile = "before" + chr(0) + "middle" + chr(0xDEAD) + "after"

        await event_store.insert_one(
            tool_completed(
                session_id=session_id + chr(0),
                tool_name="Bash",
                tool_use_id="hostile-1",
                success=False,
                error=hostile,
            )
        )
        await event_store.insert_batch(
            [
                tool_completed(
                    session_id=session_id,
                    tool_name="Bash",
                    tool_use_id="hostile-2",
                    success=False,
                    error=hostile,
                )
            ]
        )

        # THE HOSTILE ID IS ITS OWN SESSION, and that is the whole point.
        #
        # Event 1 was written under `session_id + chr(0)`. This assertion used
        # to read `errors == ["beforemiddleafter", "beforemiddleafter"]`, and
        # it passed because that id STRIPPED to `session_id`: the event landed
        # in the CLEAN session's stream. One harness emitting a NUL could write
        # into another session's history, and a reader of the clean session
        # could not tell. That is the collision #1241 closed, and this test was
        # asserting it.
        clean = await event_store.query(session_id)
        assert len(clean) == 1, "a NUL-bearing session id wrote into the clean session"

        hostile_session = pg_safe(session_id + chr(0))
        assert hostile_session != session_id, "the two ids must not share a key"
        theirs = await event_store.query(hostile_session)
        assert len(theirs) == 1, "the hostile session's own event is unreachable"

        # Both stored, both readable, and neither carrying a codepoint Postgres
        # refuses - which is what this test exists to prove against a real
        # server rather than against the values handed to the driver.
        for row in (*clean, *theirs):
            stored = row["data"].get("error")
            assert isinstance(stored, str)
            assert stored.startswith("beforemiddleafter"), stored
            assert chr(0) not in stored

        # Same raw error in both, so the same stored spelling in both: the
        # derivation depends only on the input, which is what lets a writer and
        # a reader agree without coordinating.
        assert clean[0]["data"].get("error") == theirs[0]["data"].get("error")

    @pytest.mark.asyncio
    async def test_insert_batch_performance(self, event_store, session_id):
        """Test batch insert with many events."""
        await event_store.initialize()

        # Create 1000 test events using type-safe factories
        events = [
            tool_completed(
                session_id=session_id,
                tool_name=f"Tool_{i}",
                tool_use_id=f"tool-{i}",
                success=True,
                duration_ms=i * 10,
            )
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

    @pytest.mark.asyncio
    async def test_query_by_event_type(self, event_store, session_id):
        """Test querying events filtered by type."""
        await event_store.initialize()

        # Insert mixed event types using type-safe factories
        events = [
            session_started(session_id=session_id),
            tool_started(session_id=session_id, tool_name="Read", tool_use_id="r1"),
            tool_completed(session_id=session_id, tool_name="Read", tool_use_id="r1", success=True),
            tool_started(session_id=session_id, tool_name="Write", tool_use_id="w1"),
            session_completed(session_id=session_id),
        ]

        await event_store.insert_batch(events)

        # Query only tool_execution_started
        tool_events = await event_store.query(session_id, event_type=TOOL_EXECUTION_STARTED)

        assert len(tool_events) == 2
        assert all(e["event_type"] == TOOL_EXECUTION_STARTED for e in tool_events)

    @pytest.mark.asyncio
    async def test_query_by_execution(self, event_store, session_id):
        """Test querying events by execution ID."""
        await event_store.initialize()

        exec_id = f"exec-{uuid4().hex[:8]}"

        events = [
            session_started(session_id=session_id, execution_id=exec_id),
            tool_started(
                session_id=session_id,
                execution_id=exec_id,
                tool_name="TestTool",
                tool_use_id="exec-test",
            ),
            session_completed(session_id=session_id, execution_id=exec_id),
        ]

        await event_store.insert_batch(events)

        # Query by execution ID
        exec_events = await event_store.query_by_execution(exec_id)

        assert len(exec_events) == 3
        assert all(e["execution_id"] == exec_id for e in exec_events)

    @pytest.mark.asyncio
    async def test_pagination(self, event_store, session_id):
        """Test query pagination with offset."""
        await event_store.initialize()

        # Insert 50 events with valid event types and unique tool_use_ids
        events = [
            tool_started(
                session_id=session_id,
                tool_name=f"Tool_{i}",
                tool_use_id=f"pagination-{i}",
            )
            for i in range(50)
        ]
        await event_store.insert_batch(events)

        # Query first page
        page1 = await event_store.query(session_id, limit=20, offset=0)
        assert len(page1) == 20

        # Query second page
        page2 = await event_store.query(session_id, limit=20, offset=20)
        assert len(page2) == 20

        # Pages should have different tool_use_ids
        page1_ids = {e["data"].get("tool_use_id") for e in page1}
        page2_ids = {e["data"].get("tool_use_id") for e in page2}
        assert page1_ids.isdisjoint(page2_ids)


class TestEventBufferIntegration:
    """Integration tests for EventBuffer with real storage."""

    @pytest.mark.asyncio
    async def test_buffer_flushes_to_store(self, event_store, session_id):
        """Test that EventBuffer properly flushes to AgentEventStore."""
        from syn_adapters.events import EventBuffer

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
                tool_started(
                    session_id=session_id,
                    tool_name=f"BufferTool_{i}",
                    tool_use_id=f"buffer-{i}",
                )
            )

        # Wait for flush
        await asyncio.sleep(0.2)

        # Stop and flush remaining
        await buffer.stop()

        # Verify all events stored
        events = await event_store.query(session_id)
        assert len(events) == 15


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
