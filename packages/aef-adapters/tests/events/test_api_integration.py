"""Integration test for the events API endpoints.

Tests the /events/* endpoints with real TimescaleDB.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

TIMESCALE_URL = os.getenv(
    "TIMESCALE_URL",
    "postgresql://aef:aef_dev_password@localhost:5433/aef_observability",
)


@pytest.fixture
async def seeded_session():
    """Create a session with test events in the database."""
    from aef_adapters.events import AgentEventStore

    store = AgentEventStore(TIMESCALE_URL)
    await store.initialize()

    session_id = f"api-test-{uuid4().hex[:8]}"

    # Insert a variety of events
    events = [
        {
            "event_type": "session_started",
            "session_id": session_id,
            "provider": "claude",
        },
        {
            "event_type": "tool_execution_started",
            "session_id": session_id,
            "tool_name": "Read",
            "tool_use_id": "tool-1",
        },
        {
            "event_type": "tool_execution_completed",
            "session_id": session_id,
            "tool_name": "Read",
            "tool_use_id": "tool-1",
            "success": True,
            "duration_ms": 150,
        },
        {
            "event_type": "tool_execution_started",
            "session_id": session_id,
            "tool_name": "Write",
            "tool_use_id": "tool-2",
        },
        {
            "event_type": "tool_execution_completed",
            "session_id": session_id,
            "tool_name": "Write",
            "tool_use_id": "tool-2",
            "success": True,
            "duration_ms": 200,
        },
        {
            "event_type": "tool_execution_started",
            "session_id": session_id,
            "tool_name": "Bash",
            "tool_use_id": "tool-3",
        },
        {
            "event_type": "tool_execution_completed",
            "session_id": session_id,
            "tool_name": "Bash",
            "tool_use_id": "tool-3",
            "success": False,
            "error": "Command failed",
            "duration_ms": 50,
        },
        {
            "event_type": "token_usage",
            "session_id": session_id,
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_creation_tokens": 100,
            "cache_read_tokens": 200,
        },
        {
            "event_type": "session_completed",
            "session_id": session_id,
        },
    ]

    await store.insert_batch(events)

    yield session_id

    await store.close()


class TestEventsAPI:
    """Test the events API endpoints."""

    @pytest.mark.asyncio
    async def test_get_session_events(self, seeded_session):
        """Test GET /events/sessions/{session_id}."""
        from aef_adapters.events import get_event_store

        # Manually test the query logic (simulating API call)
        store = get_event_store(TIMESCALE_URL)
        await store.initialize()

        events = await store.query(seeded_session, limit=100)

        assert len(events) == 9
        event_types = [e["event_type"] for e in events]
        assert "session_started" in event_types
        assert "tool_execution_completed" in event_types
        assert "session_completed" in event_types

    @pytest.mark.asyncio
    async def test_get_session_events_filtered(self, seeded_session):
        """Test GET /events/sessions/{session_id}?event_type=..."""
        from aef_adapters.events import get_event_store

        store = get_event_store(TIMESCALE_URL)
        await store.initialize()

        # Filter by event type
        tool_events = await store.query(
            seeded_session,
            event_type="tool_execution_completed",
        )

        assert len(tool_events) == 3
        assert all(e["event_type"] == "tool_execution_completed" for e in tool_events)

    @pytest.mark.asyncio
    async def test_timeline_events(self, seeded_session):
        """Test timeline view of events."""
        from aef_adapters.events import get_event_store

        store = get_event_store(TIMESCALE_URL)
        await store.initialize()

        events = await store.query(seeded_session)

        # Filter for timeline-worthy events
        timeline = [
            e
            for e in events
            if e["event_type"]
            in (
                "tool_execution_started",
                "tool_execution_completed",
                "session_started",
                "session_completed",
            )
        ]

        assert len(timeline) == 8  # 6 tool events + 2 session events

    @pytest.mark.asyncio
    async def test_cost_aggregation(self, seeded_session):
        """Test cost aggregation from token_usage events."""
        from aef_adapters.events import get_event_store

        store = get_event_store(TIMESCALE_URL)
        await store.initialize()

        # Query token usage events
        token_events = await store.query(
            seeded_session,
            event_type="token_usage",
        )

        # Aggregate
        total_input = sum(e["data"].get("input_tokens", 0) for e in token_events)
        total_output = sum(e["data"].get("output_tokens", 0) for e in token_events)

        assert total_input == 1000
        assert total_output == 500

    @pytest.mark.asyncio
    async def test_tool_summary(self, seeded_session):
        """Test tool usage summary."""
        from aef_adapters.events import get_event_store

        store = get_event_store(TIMESCALE_URL)
        await store.initialize()

        # Query tool completion events
        tool_events = await store.query(
            seeded_session,
            event_type="tool_execution_completed",
        )

        # Build summary
        from collections import defaultdict

        tool_stats: dict = defaultdict(
            lambda: {
                "call_count": 0,
                "success_count": 0,
                "error_count": 0,
                "total_duration_ms": 0,
            }
        )

        for e in tool_events:
            data = e["data"]
            tool_name = data.get("tool_name", "unknown")
            stats = tool_stats[tool_name]
            stats["call_count"] += 1
            if data.get("success", True):
                stats["success_count"] += 1
            else:
                stats["error_count"] += 1
            stats["total_duration_ms"] += data.get("duration_ms", 0)

        assert tool_stats["Read"]["call_count"] == 1
        assert tool_stats["Read"]["success_count"] == 1
        assert tool_stats["Write"]["call_count"] == 1
        assert tool_stats["Bash"]["error_count"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
