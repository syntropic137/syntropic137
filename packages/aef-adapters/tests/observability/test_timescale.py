"""Tests for TimescaleObservability adapter (legacy).

These tests verify that TimescaleObservability correctly implements
the ObservabilityPort protocol and integrates with ObservabilityWriter.

Note: TimescaleObservability is deprecated. Use OTel-first observability.
"""

from __future__ import annotations

import warnings
from unittest.mock import AsyncMock, MagicMock

import pytest

# Suppress deprecation warnings for test imports
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from aef_adapters.observability.protocol import (
        ObservabilityPort,
        ObservationContext,
        ObservationType,
    )
    from aef_adapters.observability.timescale import TimescaleObservability


@pytest.fixture
def mock_writer() -> MagicMock:
    """Create a mock ObservabilityWriter."""
    writer = MagicMock()
    writer.record_observation = AsyncMock(return_value="test-observation-id")
    writer.close = AsyncMock()
    return writer


@pytest.fixture
def observability(mock_writer: MagicMock) -> TimescaleObservability:
    """Create a TimescaleObservability with mock writer."""
    return TimescaleObservability(mock_writer)


@pytest.fixture
def context() -> ObservationContext:
    """Create a test observation context."""
    return ObservationContext(
        session_id="session-123",
        execution_id="exec-456",
        workflow_id="workflow-789",
        phase_id="phase-1",
    )


class TestProtocolCompliance:
    """Tests verifying ObservabilityPort protocol compliance."""

    def test_implements_protocol(self, observability: TimescaleObservability):
        """TimescaleObservability should implement ObservabilityPort."""
        assert isinstance(observability, ObservabilityPort)

    def test_has_all_protocol_methods(self, observability: TimescaleObservability):
        """Should have all required protocol methods."""
        assert hasattr(observability, "record")
        assert hasattr(observability, "record_tool_started")
        assert hasattr(observability, "record_tool_completed")
        assert hasattr(observability, "record_token_usage")
        assert hasattr(observability, "flush")
        assert hasattr(observability, "close")


class TestRecord:
    """Tests for the generic record method."""

    @pytest.mark.asyncio
    async def test_record_calls_writer(
        self,
        observability: TimescaleObservability,
        mock_writer: MagicMock,
        context: ObservationContext,
    ):
        """record() should call the underlying writer."""
        await observability.record(
            ObservationType.PROGRESS,
            context,
            {"message": "Processing..."},
        )

        mock_writer.record_observation.assert_called_once()
        call_kwargs = mock_writer.record_observation.call_args[1]
        assert call_kwargs["session_id"] == "session-123"
        assert call_kwargs["observation_type"] == "progress"
        assert call_kwargs["execution_id"] == "exec-456"
        assert call_kwargs["phase_id"] == "phase-1"

    @pytest.mark.asyncio
    async def test_record_maps_workflow_to_workspace(
        self,
        observability: TimescaleObservability,
        mock_writer: MagicMock,
        context: ObservationContext,
    ):
        """workflow_id should be mapped to workspace_id."""
        await observability.record(
            ObservationType.PROGRESS,
            context,
            {},
        )

        call_kwargs = mock_writer.record_observation.call_args[1]
        assert call_kwargs["workspace_id"] == "workflow-789"


class TestToolOperations:
    """Tests for tool operation recording."""

    @pytest.mark.asyncio
    async def test_record_tool_started(
        self,
        observability: TimescaleObservability,
        mock_writer: MagicMock,
        context: ObservationContext,
    ):
        """record_tool_started should return operation ID."""
        operation_id = await observability.record_tool_started(
            context,
            tool_name="Bash",
            tool_input={"command": "echo 'hello'"},
        )

        assert operation_id is not None
        assert len(operation_id) == 36  # UUID format

        call_kwargs = mock_writer.record_observation.call_args[1]
        assert call_kwargs["observation_type"] == "tool_started"
        assert "tool_name" in call_kwargs["data"]
        assert call_kwargs["data"]["tool_name"] == "Bash"

    @pytest.mark.asyncio
    async def test_record_tool_completed(
        self,
        observability: TimescaleObservability,
        mock_writer: MagicMock,
        context: ObservationContext,
    ):
        """record_tool_completed should record completion data."""
        await observability.record_tool_completed(
            context,
            operation_id="op-123",
            tool_name="Bash",
            success=True,
            duration_ms=150,
            output_preview="hello\n",
        )

        call_kwargs = mock_writer.record_observation.call_args[1]
        assert call_kwargs["observation_type"] == "tool_completed"
        data = call_kwargs["data"]
        assert data["operation_id"] == "op-123"
        assert data["tool_name"] == "Bash"
        assert data["success"] is True
        assert data["duration_ms"] == 150

    @pytest.mark.asyncio
    async def test_tool_started_truncates_long_input(
        self,
        observability: TimescaleObservability,
        mock_writer: MagicMock,
        context: ObservationContext,
    ):
        """Long tool inputs should be truncated."""
        long_input = {"command": "x" * 1000}

        await observability.record_tool_started(
            context,
            tool_name="Bash",
            tool_input=long_input,
        )

        call_kwargs = mock_writer.record_observation.call_args[1]
        input_preview = call_kwargs["data"]["input_preview"]
        assert len(input_preview) <= 500


class TestTokenUsage:
    """Tests for token usage recording."""

    @pytest.mark.asyncio
    async def test_record_token_usage(
        self,
        observability: TimescaleObservability,
        mock_writer: MagicMock,
        context: ObservationContext,
    ):
        """record_token_usage should calculate total tokens."""
        await observability.record_token_usage(
            context,
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=100,
            cache_write_tokens=50,
            model="claude-sonnet-4-20250514",
        )

        call_kwargs = mock_writer.record_observation.call_args[1]
        assert call_kwargs["observation_type"] == "token_usage"
        data = call_kwargs["data"]
        assert data["input_tokens"] == 1000
        assert data["output_tokens"] == 500
        assert data["total_tokens"] == 1500
        assert data["model"] == "claude-sonnet-4-20250514"


class TestLifecycle:
    """Tests for lifecycle methods."""

    @pytest.mark.asyncio
    async def test_flush_succeeds(self, observability: TimescaleObservability):
        """flush() should succeed without error."""
        await observability.flush()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_calls_writer_close(
        self,
        observability: TimescaleObservability,
        mock_writer: MagicMock,
    ):
        """close() should close the underlying writer."""
        await observability.close()
        mock_writer.close.assert_called_once()
