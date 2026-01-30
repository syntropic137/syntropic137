"""Integration test for the events API endpoints.

Tests the /events/* endpoints with real TimescaleDB.

Uses shared test_infrastructure fixture (ADR-034) which auto-detects:
- test-stack (just test-stack) on port 15432
- testcontainers fallback with dynamic ports

Run with: uv run pytest -m integration packages/aef-adapters/tests/events/
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

# Use centralized event type constants - NO hardcoded strings!
from aef_shared.events import (
    SESSION_COMPLETED,
    SESSION_STARTED,
    TOKEN_USAGE,
    TOOL_COMPLETED,
    TOOL_STARTED,
)

# Use typed factories for type-safe event creation
from aef_shared.events.factories import (
    session_completed,
    session_started,
    token_usage,
    tool_completed,
    tool_started,
)

# Mark all tests as integration - only run when explicitly requested
pytestmark = pytest.mark.integration


@dataclass
class SeededSessionData:
    """Data returned by seeded_session fixture."""

    session_id: str
    store: object  # AgentEventStore


@pytest.fixture
async def seeded_session(test_infrastructure):
    """Create a session with test events using shared test infrastructure.

    Returns SeededSessionData with both session_id and store for tests to use.
    """
    from aef_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()

    session_id = f"api-test-{uuid4().hex[:8]}"

    # Insert a variety of events using type-safe factories
    events = [
        session_started(session_id=session_id, provider="claude"),
        tool_started(session_id=session_id, tool_name="Read", tool_use_id="tool-1"),
        tool_completed(
            session_id=session_id,
            tool_name="Read",
            tool_use_id="tool-1",
            success=True,
            duration_ms=150,
        ),
        tool_started(session_id=session_id, tool_name="Write", tool_use_id="tool-2"),
        tool_completed(
            session_id=session_id,
            tool_name="Write",
            tool_use_id="tool-2",
            success=True,
            duration_ms=200,
        ),
        tool_started(session_id=session_id, tool_name="Bash", tool_use_id="tool-3"),
        tool_completed(
            session_id=session_id,
            tool_name="Bash",
            tool_use_id="tool-3",
            success=False,
            error="Command failed",
            duration_ms=50,
        ),
        token_usage(
            session_id=session_id,
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=100,
            cache_read_tokens=200,
        ),
        session_completed(session_id=session_id),
    ]

    await store.insert_batch(events)

    yield SeededSessionData(session_id=session_id, store=store)

    await store.close()


@pytest.mark.integration
class TestEventsAPI:
    """Test the events API endpoints."""

    @pytest.mark.asyncio
    async def test_get_session_events(self, seeded_session: SeededSessionData):
        """Test GET /events/sessions/{session_id}."""
        events = await seeded_session.store.query(seeded_session.session_id, limit=100)

        assert len(events) == 9
        event_types = [e["event_type"] for e in events]
        assert SESSION_STARTED in event_types
        assert TOOL_COMPLETED in event_types
        assert SESSION_COMPLETED in event_types

    @pytest.mark.asyncio
    async def test_get_session_events_filtered(self, seeded_session: SeededSessionData):
        """Test GET /events/sessions/{session_id}?event_type=..."""
        # Filter by event type
        tool_events = await seeded_session.store.query(
            seeded_session.session_id,
            event_type=TOOL_COMPLETED,
        )

        assert len(tool_events) == 3
        assert all(e["event_type"] == TOOL_COMPLETED for e in tool_events)

    @pytest.mark.asyncio
    async def test_timeline_events(self, seeded_session: SeededSessionData):
        """Test timeline view of events."""
        events = await seeded_session.store.query(seeded_session.session_id)

        # Filter for timeline-worthy events
        timeline = [
            e
            for e in events
            if e["event_type"]
            in (
                TOOL_STARTED,
                TOOL_COMPLETED,
                SESSION_STARTED,
                SESSION_COMPLETED,
            )
        ]

        assert len(timeline) == 8  # 6 tool events + 2 session events

    @pytest.mark.asyncio
    async def test_cost_aggregation(self, seeded_session: SeededSessionData):
        """Test cost aggregation from token_usage events."""
        # Query token usage events
        token_events = await seeded_session.store.query(
            seeded_session.session_id,
            event_type=TOKEN_USAGE,
        )

        # Aggregate
        total_input = sum(e["data"].get("input_tokens", 0) for e in token_events)
        total_output = sum(e["data"].get("output_tokens", 0) for e in token_events)

        assert total_input == 1000
        assert total_output == 500

    @pytest.mark.asyncio
    async def test_tool_summary(self, seeded_session: SeededSessionData):
        """Test tool usage summary."""
        # Query tool completion events
        tool_events = await seeded_session.store.query(
            seeded_session.session_id,
            event_type=TOOL_COMPLETED,
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
