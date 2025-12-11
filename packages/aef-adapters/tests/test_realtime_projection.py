"""Tests for the RealTimeProjection.

Tests verify that:
1. Connections can be registered/unregistered
2. Events are broadcast to connected clients
3. Dead connections are cleaned up
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from aef_adapters.projections.realtime import (
    RealTimeProjection,
    get_realtime_projection,
    reset_realtime_projection,
)


@pytest.fixture
def projection() -> RealTimeProjection:
    """Create a fresh RealTimeProjection instance."""
    reset_realtime_projection()
    return RealTimeProjection()


@pytest.fixture
def mock_websocket() -> MagicMock:
    """Create a mock WebSocket."""
    ws = MagicMock()
    ws.send_text = AsyncMock()
    return ws


class TestRealTimeProjectionConnection:
    """Test connection management."""

    @pytest.mark.asyncio
    async def test_connect(self, projection: RealTimeProjection, mock_websocket: MagicMock) -> None:
        """Test registering a WebSocket connection."""
        await projection.connect("exec-1", mock_websocket)

        assert projection.execution_count == 1
        assert projection.connection_count == 1

    @pytest.mark.asyncio
    async def test_connect_multiple(
        self, projection: RealTimeProjection, mock_websocket: MagicMock
    ) -> None:
        """Test registering multiple connections for same execution."""
        ws2 = MagicMock()
        ws2.send_text = AsyncMock()

        await projection.connect("exec-1", mock_websocket)
        await projection.connect("exec-1", ws2)

        assert projection.execution_count == 1
        assert projection.connection_count == 2

    @pytest.mark.asyncio
    async def test_connect_different_executions(
        self, projection: RealTimeProjection, mock_websocket: MagicMock
    ) -> None:
        """Test connections to different executions."""
        ws2 = MagicMock()
        ws2.send_text = AsyncMock()

        await projection.connect("exec-1", mock_websocket)
        await projection.connect("exec-2", ws2)

        assert projection.execution_count == 2
        assert projection.connection_count == 2

    @pytest.mark.asyncio
    async def test_disconnect(
        self, projection: RealTimeProjection, mock_websocket: MagicMock
    ) -> None:
        """Test unregistering a WebSocket connection."""
        await projection.connect("exec-1", mock_websocket)
        await projection.disconnect("exec-1", mock_websocket)

        assert projection.execution_count == 0
        assert projection.connection_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_partial(
        self, projection: RealTimeProjection, mock_websocket: MagicMock
    ) -> None:
        """Test disconnecting one of multiple connections."""
        ws2 = MagicMock()
        ws2.send_text = AsyncMock()

        await projection.connect("exec-1", mock_websocket)
        await projection.connect("exec-1", ws2)
        await projection.disconnect("exec-1", mock_websocket)

        assert projection.execution_count == 1
        assert projection.connection_count == 1


class TestRealTimeProjectionBroadcast:
    """Test event broadcasting."""

    @pytest.mark.asyncio
    async def test_broadcast_to_connected(
        self, projection: RealTimeProjection, mock_websocket: MagicMock
    ) -> None:
        """Test broadcasting an event to connected clients."""
        await projection.connect("exec-1", mock_websocket)
        await projection.broadcast("exec-1", "TestEvent", {"key": "value"})

        mock_websocket.send_text.assert_called_once()
        message = json.loads(mock_websocket.send_text.call_args[0][0])
        assert message["type"] == "event"
        assert message["event_type"] == "TestEvent"
        assert message["data"] == {"key": "value"}
        assert "timestamp" in message

    @pytest.mark.asyncio
    async def test_broadcast_no_connections(self, projection: RealTimeProjection) -> None:
        """Test broadcasting when no connections exist."""
        # Should not raise
        await projection.broadcast("exec-1", "TestEvent", {"key": "value"})

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple(
        self, projection: RealTimeProjection, mock_websocket: MagicMock
    ) -> None:
        """Test broadcasting to multiple connections."""
        ws2 = MagicMock()
        ws2.send_text = AsyncMock()

        await projection.connect("exec-1", mock_websocket)
        await projection.connect("exec-1", ws2)
        await projection.broadcast("exec-1", "TestEvent", {"key": "value"})

        assert mock_websocket.send_text.call_count == 1
        assert ws2.send_text.call_count == 1

    @pytest.mark.asyncio
    async def test_broadcast_only_to_execution(
        self, projection: RealTimeProjection, mock_websocket: MagicMock
    ) -> None:
        """Test that broadcasts only go to matching execution."""
        ws2 = MagicMock()
        ws2.send_text = AsyncMock()

        await projection.connect("exec-1", mock_websocket)
        await projection.connect("exec-2", ws2)
        await projection.broadcast("exec-1", "TestEvent", {"key": "value"})

        assert mock_websocket.send_text.call_count == 1
        assert ws2.send_text.call_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_cleans_dead_connections(self, projection: RealTimeProjection) -> None:
        """Test that dead connections are cleaned up after failed send."""
        # Create a mock that fails on send
        dead_ws = MagicMock()
        dead_ws.send_text = AsyncMock(side_effect=Exception("Connection closed"))

        await projection.connect("exec-1", dead_ws)
        assert projection.connection_count == 1

        await projection.broadcast("exec-1", "TestEvent", {"key": "value"})

        # Connection should be removed
        assert projection.connection_count == 0


class TestRealTimeProjectionEventHandlers:
    """Test domain event handlers."""

    @pytest.mark.asyncio
    async def test_on_workflow_execution_started(
        self, projection: RealTimeProjection, mock_websocket: MagicMock
    ) -> None:
        """Test handling WorkflowExecutionStarted event."""
        await projection.connect("exec-1", mock_websocket)
        await projection.on_workflow_execution_started(
            {
                "execution_id": "exec-1",
                "workflow_id": "wf-1",
            }
        )

        mock_websocket.send_text.assert_called_once()
        message = json.loads(mock_websocket.send_text.call_args[0][0])
        assert message["event_type"] == "WorkflowExecutionStarted"

    @pytest.mark.asyncio
    async def test_on_phase_started(
        self, projection: RealTimeProjection, mock_websocket: MagicMock
    ) -> None:
        """Test handling PhaseStarted event."""
        await projection.connect("exec-1", mock_websocket)
        await projection.on_phase_started(
            {
                "execution_id": "exec-1",
                "phase_id": "phase-1",
            }
        )

        mock_websocket.send_text.assert_called_once()
        message = json.loads(mock_websocket.send_text.call_args[0][0])
        assert message["event_type"] == "PhaseStarted"

    @pytest.mark.asyncio
    async def test_on_operation_recorded(
        self, projection: RealTimeProjection, mock_websocket: MagicMock
    ) -> None:
        """Test handling OperationRecorded event."""
        await projection.connect("exec-1", mock_websocket)
        await projection.on_operation_recorded(
            {
                "execution_id": "exec-1",
                "operation_type": "tool_completed",
                "tool_name": "Read",
            }
        )

        mock_websocket.send_text.assert_called_once()
        message = json.loads(mock_websocket.send_text.call_args[0][0])
        assert message["event_type"] == "OperationRecorded"

    @pytest.mark.asyncio
    async def test_event_without_execution_id(
        self, projection: RealTimeProjection, mock_websocket: MagicMock
    ) -> None:
        """Test that events without execution_id are ignored."""
        await projection.connect("exec-1", mock_websocket)
        await projection.on_phase_started({"phase_id": "phase-1"})  # No execution_id

        mock_websocket.send_text.assert_not_called()


class TestSingleton:
    """Test singleton behavior."""

    def test_get_realtime_projection_singleton(self) -> None:
        """Test that get_realtime_projection returns same instance."""
        reset_realtime_projection()
        p1 = get_realtime_projection()
        p2 = get_realtime_projection()
        assert p1 is p2

    def test_reset_clears_singleton(self) -> None:
        """Test that reset_realtime_projection clears the singleton."""
        p1 = get_realtime_projection()
        reset_realtime_projection()
        p2 = get_realtime_projection()
        assert p1 is not p2
