"""Tests for executor control signal integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

from aef_adapters.agents.agentic_types import (
    AgentExecutionConfig,
    TaskCompleted,
    ToolUseCompleted,
    ToolUseStarted,
    Workspace,
)
from aef_adapters.control import ControlSignal, ControlSignalType
from aef_adapters.orchestration.executor import (
    AgenticWorkflowExecutor,
)

# =============================================================================
# Mock Classes
# =============================================================================


@dataclass
class MockPhase:
    """Mock workflow phase."""

    phase_id: str = "test-phase"
    name: str = "Test Phase"
    order: int = 1
    description: str | None = "Test phase description"
    prompt_template: str = "Do something with {{topic}}"
    allowed_tools: frozenset[str] = frozenset({"read_file", "write_file"})
    output_artifact_type: str = "text"
    timeout_seconds: int = 300


@dataclass
class MockWorkflow:
    """Mock workflow definition."""

    workflow_id: str = "test-workflow"
    name: str = "Test Workflow"
    phases: list[MockPhase] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.phases is None:
            self.phases = [MockPhase()]


class MockAgent:
    """Mock agentic agent."""

    is_available: bool = True

    def __init__(self, events: list | None = None) -> None:
        self._events = events or []

    async def execute(
        self,
        _task: str,
        _workspace: Workspace,
        _config: AgentExecutionConfig,
    ) -> AsyncIterator:
        """Execute mock agent, yielding configured events."""
        for event in self._events:
            yield event


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_workspace_factory() -> MagicMock:
    """Create mock workspace factory."""
    return MagicMock()


@pytest.fixture
def mock_workflow() -> MockWorkflow:
    """Create mock workflow."""
    return MockWorkflow()


# =============================================================================
# Tests
# =============================================================================


class TestExecutorControlSignals:
    """Tests for control signal handling in executor."""

    @pytest.mark.asyncio
    async def test_executor_pause_and_resume_signal(
        self,
        mock_workspace_factory: MagicMock,
        mock_workflow: MockWorkflow,
        tmp_path: Path,
    ) -> None:
        """Test executor pauses and resumes on control signals."""
        # Setup: agent yields tool events
        agent_events = [
            ToolUseStarted(
                tool_name="read_file",
                tool_use_id="tool-1",
                tool_input={"path": "test.txt"},
                timestamp=datetime.now(UTC),
            ),
            ToolUseCompleted(
                tool_name="read_file",
                tool_use_id="tool-1",
                tool_output="file content",
                duration_ms=100.0,
                success=True,
                timestamp=datetime.now(UTC),
            ),
            TaskCompleted(
                result="Done",
                input_tokens=100,
                output_tokens=50,
            ),
        ]
        mock_agent = MockAgent(agent_events)

        # Signal checker: first returns PAUSE, then RESUME
        signal_calls = [0]
        pause_signal = ControlSignal(
            signal_type=ControlSignalType.PAUSE,
            execution_id="exec-1",
            reason="User paused",
        )
        resume_signal = ControlSignal(
            signal_type=ControlSignalType.RESUME,
            execution_id="exec-1",
        )

        async def check_signal(_execution_id: str) -> ControlSignal | None:
            signal_calls[0] += 1
            if signal_calls[0] == 1:
                return pause_signal
            elif signal_calls[0] == 2:
                return resume_signal
            return None

        executor = AgenticWorkflowExecutor(
            agent_factory=lambda _: mock_agent,
            workspace_service=mock_workspace_factory,
            control_signal_checker=check_signal,
        )

        # Execute and collect events
        events = []
        async for event in executor.execute(mock_workflow, {"topic": "test"}):
            events.append(event)

        # Verify we got pause and resume events
        event_types = [type(e).__name__ for e in events]
        assert "ExecutionPaused" in event_types
        assert "ExecutionResumed" in event_types
        assert "PhaseCompleted" in event_types  # Should complete after resume

    @pytest.mark.asyncio
    async def test_executor_cancel_signal(
        self,
        mock_workspace_factory: MagicMock,
        mock_workflow: MockWorkflow,
        tmp_path: Path,
    ) -> None:
        """Test executor cancels on cancel signal."""
        agent_events = [
            ToolUseStarted(
                tool_name="read_file",
                tool_use_id="tool-1",
                tool_input={"path": "test.txt"},
                timestamp=datetime.now(UTC),
            ),
            ToolUseCompleted(
                tool_name="read_file",
                tool_use_id="tool-1",
                tool_output="file content",
                duration_ms=100.0,
                success=True,
                timestamp=datetime.now(UTC),
            ),
            # Note: TaskCompleted won't be reached due to cancel
            TaskCompleted(
                result="Done",
                input_tokens=100,
                output_tokens=50,
            ),
        ]
        mock_agent = MockAgent(agent_events)

        # Signal checker: returns CANCEL on first check
        cancel_signal = ControlSignal(
            signal_type=ControlSignalType.CANCEL,
            execution_id="exec-1",
            reason="User cancelled",
        )

        async def check_signal(_execution_id: str) -> ControlSignal | None:
            return cancel_signal

        executor = AgenticWorkflowExecutor(
            agent_factory=lambda _: mock_agent,
            workspace_service=mock_workspace_factory,
            control_signal_checker=check_signal,
        )

        events = []
        async for event in executor.execute(mock_workflow, {"topic": "test"}):
            events.append(event)

        # Verify we got cancel event
        event_types = [type(e).__name__ for e in events]
        assert "ExecutionCancelled" in event_types
        # Phase was cancelled, so no PhaseCompleted
        assert "PhaseCompleted" not in event_types
        # Workflow completes (cancellation is a clean exit, not failure)
        assert "WorkflowCompleted" in event_types

    @pytest.mark.asyncio
    async def test_executor_no_signal_continues_normally(
        self,
        mock_workspace_factory: MagicMock,
        mock_workflow: MockWorkflow,
        tmp_path: Path,
    ) -> None:
        """Test executor continues normally when no signal is returned."""
        agent_events = [
            ToolUseStarted(
                tool_name="read_file",
                tool_use_id="tool-1",
                tool_input={"path": "test.txt"},
                timestamp=datetime.now(UTC),
            ),
            ToolUseCompleted(
                tool_name="read_file",
                tool_use_id="tool-1",
                tool_output="file content",
                duration_ms=100.0,
                success=True,
                timestamp=datetime.now(UTC),
            ),
            TaskCompleted(
                result="Done",
                input_tokens=100,
                output_tokens=50,
            ),
        ]
        mock_agent = MockAgent(agent_events)

        # Signal checker always returns None
        async def check_signal(_execution_id: str) -> ControlSignal | None:
            return None

        executor = AgenticWorkflowExecutor(
            agent_factory=lambda _: mock_agent,
            workspace_service=mock_workspace_factory,
            control_signal_checker=check_signal,
        )

        events = []
        async for event in executor.execute(mock_workflow, {"topic": "test"}):
            events.append(event)

        # Verify normal completion
        event_types = [type(e).__name__ for e in events]
        assert "WorkflowStarted" in event_types
        assert "PhaseStarted" in event_types
        assert "PhaseCompleted" in event_types
        assert "WorkflowCompleted" in event_types
        # Should NOT have pause/resume/cancel events
        assert "ExecutionPaused" not in event_types
        assert "ExecutionResumed" not in event_types
        assert "ExecutionCancelled" not in event_types

    @pytest.mark.asyncio
    async def test_executor_without_signal_checker(
        self,
        mock_workspace_factory: MagicMock,
        mock_workflow: MockWorkflow,
        tmp_path: Path,
    ) -> None:
        """Test executor works without signal checker configured."""
        agent_events = [
            ToolUseStarted(
                tool_name="read_file",
                tool_use_id="tool-1",
                tool_input={"path": "test.txt"},
                timestamp=datetime.now(UTC),
            ),
            ToolUseCompleted(
                tool_name="read_file",
                tool_use_id="tool-1",
                tool_output="file content",
                duration_ms=100.0,
                success=True,
                timestamp=datetime.now(UTC),
            ),
            TaskCompleted(
                result="Done",
                input_tokens=100,
                output_tokens=50,
            ),
        ]
        mock_agent = MockAgent(agent_events)

        # No signal checker configured
        executor = AgenticWorkflowExecutor(
            agent_factory=lambda _: mock_agent,
            workspace_service=mock_workspace_factory,
        )

        events = []
        async for event in executor.execute(mock_workflow, {"topic": "test"}):
            events.append(event)

        # Verify normal completion
        event_types = [type(e).__name__ for e in events]
        assert "WorkflowCompleted" in event_types

    @pytest.mark.asyncio
    async def test_cancel_while_paused(
        self,
        mock_workspace_factory: MagicMock,
        mock_workflow: MockWorkflow,
        tmp_path: Path,
    ) -> None:
        """Test cancelling execution while it's paused."""
        agent_events = [
            ToolUseStarted(
                tool_name="read_file",
                tool_use_id="tool-1",
                tool_input={"path": "test.txt"},
                timestamp=datetime.now(UTC),
            ),
            ToolUseCompleted(
                tool_name="read_file",
                tool_use_id="tool-1",
                tool_output="file content",
                duration_ms=100.0,
                success=True,
                timestamp=datetime.now(UTC),
            ),
            TaskCompleted(
                result="Done",
                input_tokens=100,
                output_tokens=50,
            ),
        ]
        mock_agent = MockAgent(agent_events)

        # Signal checker: PAUSE first, then CANCEL
        signal_calls = [0]
        pause_signal = ControlSignal(
            signal_type=ControlSignalType.PAUSE,
            execution_id="exec-1",
            reason="User paused",
        )
        cancel_signal = ControlSignal(
            signal_type=ControlSignalType.CANCEL,
            execution_id="exec-1",
            reason="User cancelled while paused",
        )

        async def check_signal(_execution_id: str) -> ControlSignal | None:
            signal_calls[0] += 1
            if signal_calls[0] == 1:
                return pause_signal
            elif signal_calls[0] == 2:
                return cancel_signal
            return None

        executor = AgenticWorkflowExecutor(
            agent_factory=lambda _: mock_agent,
            workspace_service=mock_workspace_factory,
            control_signal_checker=check_signal,
        )

        events = []
        async for event in executor.execute(mock_workflow, {"topic": "test"}):
            events.append(event)

        # Verify pause then cancel
        event_types = [type(e).__name__ for e in events]
        assert "ExecutionPaused" in event_types
        assert "ExecutionCancelled" in event_types
        # Should NOT have resume (cancelled before resume)
        assert "ExecutionResumed" not in event_types
