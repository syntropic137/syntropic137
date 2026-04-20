"""Tests for the RealTimeProjection.

Tests verify that:
1. Connections can be registered/unregistered
2. Events are broadcast to connected SSE queues
3. Terminal sentinel is enqueued correctly
"""

from __future__ import annotations

import asyncio

import pytest

from syn_adapters.projections.realtime import (
    RealTimeProjection,
    SSEEventFrame,
    SSEQueue,
    get_realtime_projection,
    reset_realtime_projection,
)


@pytest.fixture
def projection() -> RealTimeProjection:
    """Create a fresh RealTimeProjection instance."""
    reset_realtime_projection()
    return RealTimeProjection()


@pytest.mark.unit
class TestRealTimeProjectionConnection:
    """Test connection management."""

    @pytest.mark.asyncio
    async def test_connect(self, projection: RealTimeProjection) -> None:
        """Test registering an SSE subscriber returns a queue."""
        queue = await projection.connect("exec-1")

        assert isinstance(queue, asyncio.Queue)
        assert projection.execution_count == 1
        assert projection.connection_count == 1

    @pytest.mark.asyncio
    async def test_connect_multiple(self, projection: RealTimeProjection) -> None:
        """Test registering multiple subscribers for the same channel."""
        q1 = await projection.connect("exec-1")
        q2 = await projection.connect("exec-1")

        assert q1 is not q2
        assert projection.execution_count == 1
        assert projection.connection_count == 2

    @pytest.mark.asyncio
    async def test_connect_different_executions(self, projection: RealTimeProjection) -> None:
        """Test subscribers on different channels are tracked separately."""
        await projection.connect("exec-1")
        await projection.connect("exec-2")

        assert projection.execution_count == 2
        assert projection.connection_count == 2

    @pytest.mark.asyncio
    async def test_disconnect(self, projection: RealTimeProjection) -> None:
        """Test unregistering a subscriber queue."""
        queue = await projection.connect("exec-1")
        await projection.disconnect("exec-1", queue)

        assert projection.execution_count == 0
        assert projection.connection_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_partial(self, projection: RealTimeProjection) -> None:
        """Test disconnecting one of multiple subscribers."""
        q1 = await projection.connect("exec-1")
        await projection.connect("exec-1")
        await projection.disconnect("exec-1", q1)

        assert projection.execution_count == 1
        assert projection.connection_count == 1


@pytest.mark.unit
class TestRealTimeProjectionBroadcast:
    """Test event broadcasting."""

    @pytest.mark.asyncio
    async def test_broadcast_delivers_frame(self, projection: RealTimeProjection) -> None:
        """Test that broadcast puts a typed SSEEventFrame on the queue."""
        queue = await projection.connect("exec-1")
        await projection.broadcast("exec-1", "TestEvent", {"key": "value"})

        assert queue.qsize() == 1
        frame = await queue.get()
        assert isinstance(frame, SSEEventFrame)
        assert frame.type == "event"
        assert frame.event_type == "TestEvent"
        assert frame.data == {"key": "value"}
        assert frame.timestamp

    @pytest.mark.asyncio
    async def test_broadcast_no_connections(self, projection: RealTimeProjection) -> None:
        """Test broadcasting when no subscribers exist does not raise."""
        await projection.broadcast("exec-1", "TestEvent", {"key": "value"})

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_subscribers(self, projection: RealTimeProjection) -> None:
        """Test broadcast reaches all subscribers on the channel."""
        q1 = await projection.connect("exec-1")
        q2 = await projection.connect("exec-1")
        await projection.broadcast("exec-1", "TestEvent", {"key": "value"})

        assert q1.qsize() == 1
        assert q2.qsize() == 1

    @pytest.mark.asyncio
    async def test_broadcast_only_to_matching_channel(self, projection: RealTimeProjection) -> None:
        """Test that broadcasts do not cross channels."""
        q1 = await projection.connect("exec-1")
        q2 = await projection.connect("exec-2")
        await projection.broadcast("exec-1", "TestEvent", {"key": "value"})

        assert q1.qsize() == 1
        assert q2.qsize() == 0

    @pytest.mark.asyncio
    async def test_broadcast_terminal_enqueues_sentinel(
        self, projection: RealTimeProjection
    ) -> None:
        """Test that terminal=True enqueues the frame then a None sentinel."""
        queue: SSEQueue = await projection.connect("exec-1")
        await projection.broadcast("exec-1", "WorkflowCompleted", {}, terminal=True)

        assert queue.qsize() == 2  # frame + sentinel

        frame = await queue.get()
        assert isinstance(frame, SSEEventFrame)
        assert frame.type == "terminal"

        sentinel = await queue.get()
        assert sentinel is None

    @pytest.mark.asyncio
    async def test_broadcast_non_terminal_no_sentinel(self, projection: RealTimeProjection) -> None:
        """Test that non-terminal broadcasts do not enqueue a sentinel."""
        queue: SSEQueue = await projection.connect("exec-1")
        await projection.broadcast("exec-1", "PhaseStarted", {})

        assert queue.qsize() == 1
        frame = await queue.get()
        assert isinstance(frame, SSEEventFrame)
        assert frame.type == "event"


@pytest.mark.unit
class TestRealTimeProjectionEventHandlers:
    """Test domain event handlers."""

    @pytest.mark.asyncio
    async def test_on_workflow_execution_started(self, projection: RealTimeProjection) -> None:
        """Test handling WorkflowExecutionStarted event."""
        queue = await projection.connect("exec-1")
        await projection.on_workflow_execution_started(
            {"execution_id": "exec-1", "workflow_id": "wf-1"}
        )

        frame = await queue.get()
        assert isinstance(frame, SSEEventFrame)
        assert frame.event_type == "WorkflowExecutionStarted"

    @pytest.mark.asyncio
    async def test_on_phase_started(self, projection: RealTimeProjection) -> None:
        """Test handling PhaseStarted event."""
        queue = await projection.connect("exec-1")
        await projection.on_phase_started({"execution_id": "exec-1", "phase_id": "phase-1"})

        frame = await queue.get()
        assert isinstance(frame, SSEEventFrame)
        assert frame.event_type == "PhaseStarted"

    @pytest.mark.asyncio
    async def test_on_operation_recorded(self, projection: RealTimeProjection) -> None:
        """Test handling OperationRecorded event."""
        queue = await projection.connect("exec-1")
        await projection.on_operation_recorded(
            {"execution_id": "exec-1", "operation_type": "tool_completed", "tool_name": "Read"}
        )

        frame = await queue.get()
        assert isinstance(frame, SSEEventFrame)
        assert frame.event_type == "OperationRecorded"

    @pytest.mark.asyncio
    async def test_on_workflow_completed_is_terminal(self, projection: RealTimeProjection) -> None:
        """Test that WorkflowCompleted sends a terminal frame + sentinel."""
        queue: SSEQueue = await projection.connect("exec-1")
        await projection.on_workflow_completed({"execution_id": "exec-1"})

        frame = await queue.get()
        assert isinstance(frame, SSEEventFrame)
        assert frame.type == "terminal"
        assert frame.event_type == "WorkflowCompleted"

        sentinel = await queue.get()
        assert sentinel is None

    @pytest.mark.asyncio
    async def test_event_without_execution_id_is_ignored(
        self, projection: RealTimeProjection
    ) -> None:
        """Test that events without execution_id are silently dropped."""
        queue = await projection.connect("exec-1")
        await projection.on_phase_started({"phase_id": "phase-1"})  # no execution_id

        assert queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_on_session_started_broadcasts_per_execution_and_global(
        self, projection: RealTimeProjection
    ) -> None:
        """SessionStarted reaches both the per-execution channel and global activity feed.

        See: docs/adrs/ADR-064-observability-monitor-ui.md
        """
        exec_queue = await projection.connect("exec-1")
        activity_queue = await projection.connect("_activity_")

        payload: dict[str, object] = {
            "execution_id": "exec-1",
            "session_id": "session-1",
            "agent_provider": "claude",
        }
        await projection.on_session_started(payload)  # type: ignore[arg-type]

        exec_frame = await exec_queue.get()
        activity_frame = await activity_queue.get()
        assert isinstance(exec_frame, SSEEventFrame)
        assert isinstance(activity_frame, SSEEventFrame)
        assert exec_frame.event_type == "SessionStarted"
        assert activity_frame.event_type == "SessionStarted"
        assert activity_frame.execution_id is None
        assert exec_frame.execution_id == "exec-1"

    @pytest.mark.asyncio
    async def test_on_session_completed_broadcasts_per_execution_and_global(
        self, projection: RealTimeProjection
    ) -> None:
        """SessionCompleted reaches both per-execution and global activity feed."""
        exec_queue = await projection.connect("exec-1")
        activity_queue = await projection.connect("_activity_")

        payload: dict[str, object] = {
            "execution_id": "exec-1",
            "session_id": "session-1",
            "total_cost_usd": "0.04",
        }
        await projection.on_session_completed(payload)  # type: ignore[arg-type]

        exec_frame = await exec_queue.get()
        activity_frame = await activity_queue.get()
        assert isinstance(exec_frame, SSEEventFrame)
        assert isinstance(activity_frame, SSEEventFrame)
        assert exec_frame.event_type == "SessionCompleted"
        assert activity_frame.event_type == "SessionCompleted"

    @pytest.mark.asyncio
    async def test_on_session_started_without_execution_id_still_broadcasts_global(
        self, projection: RealTimeProjection
    ) -> None:
        """Even if execution_id is missing, the global feed receives the session event."""
        activity_queue = await projection.connect("_activity_")

        await projection.on_session_started({"session_id": "session-1"})  # type: ignore[arg-type]

        frame = await activity_queue.get()
        assert isinstance(frame, SSEEventFrame)
        assert frame.event_type == "SessionStarted"


@pytest.mark.unit
class TestSingleton:
    """Test singleton behavior."""

    def test_get_realtime_projection_singleton(self) -> None:
        """Test that get_realtime_projection returns the same instance."""
        reset_realtime_projection()
        p1 = get_realtime_projection()
        p2 = get_realtime_projection()
        assert p1 is p2

    def test_reset_clears_singleton(self) -> None:
        """Test that reset_realtime_projection returns a new instance."""
        p1 = get_realtime_projection()
        reset_realtime_projection()
        p2 = get_realtime_projection()
        assert p1 is not p2
