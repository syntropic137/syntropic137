"""Tests for tool timeline projection."""

import pytest

from aef_adapters.projection_stores import InMemoryProjectionStore
from aef_domain.contexts.agent_sessions.domain.queries import GetToolTimelineQuery
from aef_domain.contexts.agent_sessions.slices.tool_timeline import (
    ToolTimelineHandler,
    ToolTimelineProjection,
)


@pytest.fixture
def memory_store() -> InMemoryProjectionStore:
    """Create an in-memory projection store."""
    return InMemoryProjectionStore()


@pytest.fixture
def projection(memory_store: InMemoryProjectionStore) -> ToolTimelineProjection:
    """Create a tool timeline projection with memory store."""
    return ToolTimelineProjection(memory_store)


@pytest.fixture
def handler(projection: ToolTimelineProjection) -> ToolTimelineHandler:
    """Create a tool timeline handler."""
    return ToolTimelineHandler(projection)


@pytest.mark.unit
class TestToolTimelineProjection:
    """Tests for ToolTimelineProjection."""

    @pytest.mark.asyncio
    async def test_on_tool_execution_started(self, projection: ToolTimelineProjection) -> None:
        """Test handling tool_execution_started event."""
        event_data = {
            "event_id": "evt-123",
            "session_id": "session-abc",
            "tool_name": "Read",
            "tool_use_id": "toolu_01ABC",
            "timestamp": "2025-12-09T10:30:00Z",
            "tool_input": {"path": "/src/main.py"},
        }

        await projection.on_tool_execution_started(event_data)

        timeline = await projection.get_timeline("session-abc")
        assert timeline.total_executions == 1
        assert timeline.executions[0].tool_name == "Read"
        assert timeline.executions[0].status == "started"

    @pytest.mark.asyncio
    async def test_on_tool_execution_completed(self, projection: ToolTimelineProjection) -> None:
        """Test handling tool_execution_completed event."""
        # First, start the execution
        start_event = {
            "event_id": "evt-123",
            "session_id": "session-abc",
            "tool_name": "Read",
            "tool_use_id": "toolu_01ABC",
            "timestamp": "2025-12-09T10:30:00Z",
        }
        await projection.on_tool_execution_started(start_event)

        # Then complete it
        complete_event = {
            "event_id": "evt-124",
            "session_id": "session-abc",
            "tool_name": "Read",
            "tool_use_id": "toolu_01ABC",
            "timestamp": "2025-12-09T10:30:01Z",
            "duration_ms": 150,
            "success": True,
            "tool_output": "file contents...",
        }
        await projection.on_tool_execution_completed(complete_event)

        timeline = await projection.get_timeline("session-abc")
        assert timeline.total_executions == 1
        assert timeline.executions[0].status == "completed"
        assert timeline.executions[0].duration_ms == 150
        assert timeline.executions[0].success is True

    @pytest.mark.asyncio
    async def test_on_tool_blocked(self, projection: ToolTimelineProjection) -> None:
        """Test handling tool_blocked event."""
        event_data = {
            "event_id": "evt-125",
            "session_id": "session-abc",
            "tool_name": "Shell",
            "tool_use_id": "toolu_02DEF",
            "timestamp": "2025-12-09T10:31:00Z",
            "reason": "Dangerous command detected",
            "tool_input": {"command": "rm -rf /"},
        }

        await projection.on_tool_blocked(event_data)

        timeline = await projection.get_timeline("session-abc")
        assert timeline.total_executions == 1
        assert timeline.blocked_count == 1
        assert timeline.executions[0].status == "blocked"
        assert timeline.executions[0].block_reason == "Dangerous command detected"

    @pytest.mark.asyncio
    async def test_multiple_tools(self, projection: ToolTimelineProjection) -> None:
        """Test timeline with multiple tool executions."""
        # Tool 1: Read (completed)
        await projection.on_tool_execution_started(
            {
                "event_id": "evt-1",
                "session_id": "session-xyz",
                "tool_name": "Read",
                "tool_use_id": "toolu_001",
                "timestamp": "2025-12-09T10:00:00Z",
            }
        )
        await projection.on_tool_execution_completed(
            {
                "event_id": "evt-2",
                "session_id": "session-xyz",
                "tool_name": "Read",
                "tool_use_id": "toolu_001",
                "timestamp": "2025-12-09T10:00:01Z",
                "duration_ms": 100,
                "success": True,
            }
        )

        # Tool 2: Write (completed)
        await projection.on_tool_execution_started(
            {
                "event_id": "evt-3",
                "session_id": "session-xyz",
                "tool_name": "Write",
                "tool_use_id": "toolu_002",
                "timestamp": "2025-12-09T10:00:02Z",
            }
        )
        await projection.on_tool_execution_completed(
            {
                "event_id": "evt-4",
                "session_id": "session-xyz",
                "tool_name": "Write",
                "tool_use_id": "toolu_002",
                "timestamp": "2025-12-09T10:00:03Z",
                "duration_ms": 200,
                "success": True,
            }
        )

        # Tool 3: Shell (blocked)
        await projection.on_tool_blocked(
            {
                "event_id": "evt-5",
                "session_id": "session-xyz",
                "tool_name": "Shell",
                "tool_use_id": "toolu_003",
                "timestamp": "2025-12-09T10:00:04Z",
                "reason": "Not allowed",
            }
        )

        timeline = await projection.get_timeline("session-xyz")
        assert timeline.total_executions == 3
        assert timeline.completed_count == 2
        assert timeline.blocked_count == 1
        assert timeline.avg_duration_ms == 150.0  # (100 + 200) / 2


class TestToolTimelineHandler:
    """Tests for ToolTimelineHandler."""

    @pytest.mark.asyncio
    async def test_handle_query(
        self,
        projection: ToolTimelineProjection,
        handler: ToolTimelineHandler,
    ) -> None:
        """Test handling GetToolTimelineQuery."""
        # Setup some data
        await projection.on_tool_execution_started(
            {
                "event_id": "evt-1",
                "session_id": "session-test",
                "tool_name": "Read",
                "tool_use_id": "toolu_001",
                "timestamp": "2025-12-09T10:00:00Z",
            }
        )

        query = GetToolTimelineQuery(session_id="session-test")
        timeline = await handler.handle(query)

        assert timeline.session_id == "session-test"
        assert timeline.total_executions == 1

    @pytest.mark.asyncio
    async def test_handle_query_exclude_blocked(
        self,
        projection: ToolTimelineProjection,
        handler: ToolTimelineHandler,
    ) -> None:
        """Test excluding blocked tools from timeline."""
        await projection.on_tool_execution_started(
            {
                "event_id": "evt-1",
                "session_id": "session-test",
                "tool_name": "Read",
                "tool_use_id": "toolu_001",
                "timestamp": "2025-12-09T10:00:00Z",
            }
        )
        await projection.on_tool_blocked(
            {
                "event_id": "evt-2",
                "session_id": "session-test",
                "tool_name": "Shell",
                "tool_use_id": "toolu_002",
                "timestamp": "2025-12-09T10:00:01Z",
                "reason": "Blocked",
            }
        )

        query = GetToolTimelineQuery(session_id="session-test", include_blocked=False)
        timeline = await handler.handle(query)

        assert timeline.total_executions == 1
        assert timeline.executions[0].tool_name == "Read"

    @pytest.mark.asyncio
    async def test_handle_query_with_limit(
        self,
        projection: ToolTimelineProjection,
        handler: ToolTimelineHandler,
    ) -> None:
        """Test applying limit to timeline results."""
        for i in range(5):
            await projection.on_tool_execution_started(
                {
                    "event_id": f"evt-{i}",
                    "session_id": "session-test",
                    "tool_name": f"Tool{i}",
                    "tool_use_id": f"toolu_{i:03d}",
                    "timestamp": f"2025-12-09T10:00:0{i}Z",
                }
            )

        query = GetToolTimelineQuery(session_id="session-test", limit=3)
        timeline = await handler.handle(query)

        assert len(timeline.executions) == 3
