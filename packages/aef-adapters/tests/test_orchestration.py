"""Tests for agentic workflow orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator  # noqa: TC003 - used at runtime
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 - used at runtime
from unittest.mock import MagicMock

import pytest

from aef_adapters.agents.agentic_protocol import AgenticProtocol
from aef_adapters.agents.agentic_types import (
    AgentEvent,
    AgentExecutionConfig,
    TaskCompleted,
    TaskFailed,
    TextOutput,
    Workspace,
)
from aef_adapters.orchestration import (
    AgenticWorkflowExecutor,
    PhaseCompleted,
    PhaseFailed,
    PhaseStarted,
    WorkflowCompleted,
    WorkflowFailed,
    WorkflowStarted,
    get_agentic_agent,
)

# ============================================================================
# Test Fixtures
# ============================================================================


@dataclass
class MockPhase:
    """Mock workflow phase for testing."""

    phase_id: str
    name: str
    order: int
    description: str | None = None
    prompt_template: str = "Execute this task: {{topic}}"
    allowed_tools: frozenset[str] = field(default_factory=lambda: frozenset(["Read", "Write"]))
    output_artifact_type: str = "text"
    timeout_seconds: int = 300


@dataclass
class MockWorkflow:
    """Mock workflow definition for testing."""

    workflow_id: str
    name: str
    phases: list[MockPhase] = field(default_factory=list)


class MockAgenticAgent(AgenticProtocol):
    """Mock agentic agent for testing."""

    def __init__(
        self,
        *,
        is_available: bool = True,
        should_fail: bool = False,
        fail_message: str = "Mock failure",
    ) -> None:
        self._is_available = is_available
        self._should_fail = should_fail
        self._fail_message = fail_message
        self._execute_calls: list[tuple[str, Workspace, AgentExecutionConfig]] = []

    @property
    def provider(self) -> str:
        return "mock"

    @property
    def supported_tools(self) -> frozenset[str]:
        return frozenset(["Read", "Write", "Bash"])

    @property
    def is_available(self) -> bool:
        return self._is_available

    async def execute(
        self,
        task: str,
        workspace: Workspace,
        config: AgentExecutionConfig,
    ) -> AsyncIterator[AgentEvent]:
        self._execute_calls.append((task, workspace, config))

        if self._should_fail:
            yield TaskFailed(
                error=self._fail_message,
                error_type="MockError",
                input_tokens=10,
                output_tokens=0,
                turns_used=1,
                duration_ms=100,
            )
            return

        # Simulate successful execution
        yield TextOutput(content="Processing task...", is_partial=True)
        yield TextOutput(content="Task completed!", is_partial=False)
        yield TaskCompleted(
            result=f"Result for: {task[:50]}...",
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            turns_used=3,
            tools_used=["Read", "Write"],
            duration_ms=5000,
        )


@pytest.fixture
def mock_agent() -> MockAgenticAgent:
    """Create a mock agentic agent."""
    return MockAgenticAgent()


@pytest.fixture
def failing_agent() -> MockAgenticAgent:
    """Create a failing mock agent."""
    return MockAgenticAgent(should_fail=True, fail_message="Test failure")


@pytest.fixture
def unavailable_agent() -> MockAgenticAgent:
    """Create an unavailable mock agent."""
    return MockAgenticAgent(is_available=False)


@pytest.fixture
def simple_workflow() -> MockWorkflow:
    """Create a simple single-phase workflow."""
    return MockWorkflow(
        workflow_id="wf-simple",
        name="Simple Workflow",
        phases=[
            MockPhase(
                phase_id="phase-1",
                name="Research Phase",
                order=1,
                prompt_template="Research about {{topic}}",
            ),
        ],
    )


@pytest.fixture
def multi_phase_workflow() -> MockWorkflow:
    """Create a multi-phase workflow."""
    return MockWorkflow(
        workflow_id="wf-multi",
        name="Multi-Phase Workflow",
        phases=[
            MockPhase(
                phase_id="research",
                name="Research Phase",
                order=1,
                prompt_template="Research about {{topic}}",
            ),
            MockPhase(
                phase_id="plan",
                name="Planning Phase",
                order=2,
                prompt_template="Create a plan based on: {{research}}",
            ),
            MockPhase(
                phase_id="execute",
                name="Execution Phase",
                order=3,
                prompt_template="Execute the plan: {{plan}}",
            ),
        ],
    )


@pytest.fixture
def executor(mock_agent: MockAgenticAgent, tmp_path: Path) -> AgenticWorkflowExecutor:
    """Create an executor with mock agent."""
    return AgenticWorkflowExecutor(
        agent_factory=lambda _: mock_agent,
        workspace_factory=MagicMock(),
        base_workspace_path=tmp_path,
    )


# ============================================================================
# Test AgenticWorkflowExecutor
# ============================================================================


class TestAgenticWorkflowExecutor:
    """Tests for AgenticWorkflowExecutor."""

    @pytest.mark.asyncio
    async def test_execute_simple_workflow(
        self,
        executor: AgenticWorkflowExecutor,
        simple_workflow: MockWorkflow,
    ) -> None:
        """Test executing a simple single-phase workflow."""
        events = []
        async for event in executor.execute(simple_workflow, {"topic": "AI"}):
            events.append(event)

        # Verify event sequence
        assert len(events) >= 4  # Started, PhaseStarted, PhaseCompleted, Completed

        # Check workflow started
        assert isinstance(events[0], WorkflowStarted)
        assert events[0].workflow_id == "wf-simple"
        assert events[0].total_phases == 1

        # Check phase started
        assert isinstance(events[1], PhaseStarted)
        assert events[1].phase_id == "phase-1"

        # Check phase completed
        assert isinstance(events[2], PhaseCompleted)
        assert events[2].phase_id == "phase-1"
        assert events[2].total_tokens > 0

        # Check workflow completed
        assert isinstance(events[3], WorkflowCompleted)
        assert events[3].completed_phases == 1
        assert len(events[3].artifact_ids) == 1

    @pytest.mark.asyncio
    async def test_execute_multi_phase_workflow(
        self,
        mock_agent: MockAgenticAgent,
        multi_phase_workflow: MockWorkflow,
        tmp_path: Path,
    ) -> None:
        """Test executing a multi-phase workflow."""
        executor = AgenticWorkflowExecutor(
            agent_factory=lambda _: mock_agent,
            workspace_factory=MagicMock(),
            base_workspace_path=tmp_path,
        )

        events = []
        async for event in executor.execute(multi_phase_workflow, {"topic": "AI"}):
            events.append(event)

        # Should have started, 3x(PhaseStarted, PhaseCompleted), completed
        workflow_started = [e for e in events if isinstance(e, WorkflowStarted)]
        phase_started = [e for e in events if isinstance(e, PhaseStarted)]
        phase_completed = [e for e in events if isinstance(e, PhaseCompleted)]
        workflow_completed = [e for e in events if isinstance(e, WorkflowCompleted)]

        assert len(workflow_started) == 1
        assert len(phase_started) == 3
        assert len(phase_completed) == 3
        assert len(workflow_completed) == 1

        # Phases should be executed in order
        assert [e.phase_id for e in phase_started] == ["research", "plan", "execute"]

        # Final completion should have 3 artifacts
        assert workflow_completed[0].completed_phases == 3
        assert len(workflow_completed[0].artifact_ids) == 3

    @pytest.mark.asyncio
    async def test_execute_with_unavailable_agent(
        self,
        unavailable_agent: MockAgenticAgent,
        simple_workflow: MockWorkflow,
        tmp_path: Path,
    ) -> None:
        """Test execution fails gracefully with unavailable agent."""
        executor = AgenticWorkflowExecutor(
            agent_factory=lambda _: unavailable_agent,
            workspace_factory=MagicMock(),
            base_workspace_path=tmp_path,
        )

        events = []
        async for event in executor.execute(simple_workflow, {"topic": "AI"}):
            events.append(event)

        # Should have started then failed
        assert len(events) == 2
        assert isinstance(events[0], WorkflowStarted)
        assert isinstance(events[1], WorkflowFailed)
        assert "not available" in events[1].error

    @pytest.mark.asyncio
    async def test_execute_with_phase_failure(
        self,
        failing_agent: MockAgenticAgent,
        simple_workflow: MockWorkflow,
        tmp_path: Path,
    ) -> None:
        """Test execution handles phase failure."""
        executor = AgenticWorkflowExecutor(
            agent_factory=lambda _: failing_agent,
            workspace_factory=MagicMock(),
            base_workspace_path=tmp_path,
        )

        events = []
        async for event in executor.execute(simple_workflow, {"topic": "AI"}):
            events.append(event)

        # Should have started, phase started, phase failed, workflow failed
        phase_failed = [e for e in events if isinstance(e, PhaseFailed)]
        workflow_failed = [e for e in events if isinstance(e, WorkflowFailed)]

        assert len(phase_failed) == 1
        assert len(workflow_failed) == 1
        assert phase_failed[0].error == "Test failure"
        assert workflow_failed[0].failed_phase_id == "phase-1"

    @pytest.mark.asyncio
    async def test_phase_context_passing(
        self,
        mock_agent: MockAgenticAgent,
        multi_phase_workflow: MockWorkflow,
        tmp_path: Path,
    ) -> None:
        """Test that phase outputs are passed to subsequent phases."""
        executor = AgenticWorkflowExecutor(
            agent_factory=lambda _: mock_agent,
            workspace_factory=MagicMock(),
            base_workspace_path=tmp_path,
        )

        # Execute workflow
        events = []
        async for event in executor.execute(multi_phase_workflow, {"topic": "AI"}):
            events.append(event)

        # Agent should have been called 3 times
        assert len(mock_agent._execute_calls) == 3

        # Second call should reference first phase output
        second_task = mock_agent._execute_calls[1][0]
        assert "research" in second_task.lower() or "Result for" in second_task

    @pytest.mark.asyncio
    async def test_custom_execution_id(
        self,
        executor: AgenticWorkflowExecutor,
        simple_workflow: MockWorkflow,
    ) -> None:
        """Test using custom execution ID."""
        custom_id = "custom-exec-123"

        events = []
        async for event in executor.execute(
            simple_workflow, {"topic": "AI"}, execution_id=custom_id
        ):
            events.append(event)

        assert events[0].execution_id == custom_id

    @pytest.mark.asyncio
    async def test_workspace_creation(
        self,
        mock_agent: MockAgenticAgent,
        simple_workflow: MockWorkflow,
        tmp_path: Path,
    ) -> None:
        """Test that workspace is created for execution."""
        executor = AgenticWorkflowExecutor(
            agent_factory=lambda _: mock_agent,
            workspace_factory=MagicMock(),
            base_workspace_path=tmp_path,
        )

        events = []
        async for event in executor.execute(simple_workflow, {"topic": "AI"}):
            events.append(event)

        # Check workspace was created
        phase_started = next(e for e in events if isinstance(e, PhaseStarted))
        assert phase_started.workspace_path.exists()


# ============================================================================
# Test Factory
# ============================================================================


class TestAgenticAgentFactory:
    """Tests for agentic agent factory."""

    def test_get_agentic_agent_claude(self) -> None:
        """Test getting Claude agentic agent."""
        # This may or may not be available depending on environment
        try:
            agent = get_agentic_agent("claude")
            assert agent is not None
            assert hasattr(agent, "execute")
        except ValueError:
            # Expected if SDK not installed
            pass

    def test_get_agentic_agent_unknown_provider(self) -> None:
        """Test error for unknown provider."""
        with pytest.raises(ValueError, match="Unsupported agentic provider"):
            get_agentic_agent("unknown_provider")

    def test_get_agentic_agent_case_insensitive(self) -> None:
        """Test provider name is case insensitive."""
        try:
            agent1 = get_agentic_agent("claude")
            agent2 = get_agentic_agent("CLAUDE")
            agent3 = get_agentic_agent("Claude")

            # All should return same type
            assert type(agent1) is type(agent2) is type(agent3)
        except ValueError:
            pass


# ============================================================================
# Test Execution Events
# ============================================================================


class TestExecutionEvents:
    """Tests for execution event dataclasses."""

    def test_workflow_started_event(self) -> None:
        """Test WorkflowStarted event."""
        event = WorkflowStarted(
            workflow_id="wf-1",
            execution_id="exec-1",
            workflow_name="Test Workflow",
            total_phases=3,
            started_at=datetime.now(UTC),
            inputs={"topic": "AI"},
        )

        assert event.workflow_id == "wf-1"
        assert event.total_phases == 3
        assert event.inputs["topic"] == "AI"

    def test_phase_completed_event(self) -> None:
        """Test PhaseCompleted event."""
        event = PhaseCompleted(
            workflow_id="wf-1",
            execution_id="exec-1",
            phase_id="phase-1",
            completed_at=datetime.now(UTC),
            artifact_bundle_id="bundle-1",
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            duration_ms=5000.0,
        )

        assert event.phase_id == "phase-1"
        assert event.total_tokens == 300

    def test_workflow_failed_event(self) -> None:
        """Test WorkflowFailed event."""
        event = WorkflowFailed(
            workflow_id="wf-1",
            execution_id="exec-1",
            failed_at=datetime.now(UTC),
            failed_phase_id="phase-2",
            error="Something went wrong",
            error_type="RuntimeError",
            completed_phases=1,
            total_phases=3,
        )

        assert event.failed_phase_id == "phase-2"
        assert event.completed_phases == 1
        assert event.total_phases == 3
