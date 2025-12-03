"""Tests for workflow execution engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:
    from aef_domain.contexts.artifacts._shared.ArtifactAggregate import ArtifactAggregate
    from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
from aef_domain.contexts.workflows._shared.execution_value_objects import (
    ExecutablePhase,
    ExecutionMetrics,
    ExecutionStatus,
    PhaseResult,
    PhaseStatus,
)
from aef_domain.contexts.workflows._shared.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from aef_domain.contexts.workflows._shared.WorkflowAggregate import (
    WorkflowAggregate,
)
from aef_domain.contexts.workflows.create_workflow.CreateWorkflowCommand import (
    CreateWorkflowCommand,
)
from aef_domain.contexts.workflows.execute_workflow.WorkflowExecutionEngine import (
    ExecutionContext,
    WorkflowExecutionEngine,
    WorkflowExecutionResult,
    WorkflowNotFoundError,
)

# =============================================================================
# TEST FIXTURES
# =============================================================================


@dataclass
class MockAgentResponse:
    """Mock agent response for testing."""

    content: str
    model: str = "mock-model"
    input_tokens: int = 100
    output_tokens: int = 200
    total_tokens: int = 300
    stop_reason: str = "end_turn"
    cost_estimate: float = 0.01


@dataclass
class MockInstrumentedAgent:
    """Mock instrumented agent for testing."""

    responses: list[str] = field(default_factory=list)
    _response_index: int = 0
    _session_context: dict[str, Any] = field(default_factory=dict)
    _calls: list[dict[str, Any]] = field(default_factory=list)

    def set_session_context(
        self,
        session_id: str,
        workflow_id: str | None = None,
        phase_id: str | None = None,
    ) -> None:
        self._session_context = {
            "session_id": session_id,
            "workflow_id": workflow_id,
            "phase_id": phase_id,
        }

    async def complete(
        self,
        messages: list[Any],
        config: Any,
    ) -> MockAgentResponse:
        """Return mock response."""
        self._calls.append(
            {
                "messages": messages,
                "config": config,
                "session_context": self._session_context.copy(),
            }
        )

        if self._response_index < len(self.responses):
            content = self.responses[self._response_index]
            self._response_index += 1
        else:
            content = f"Mock response {self._response_index}"
            self._response_index += 1

        return MockAgentResponse(content=content)


class MockWorkflowRepository:
    """Mock workflow repository for testing."""

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowAggregate] = {}

    async def get_by_id(self, workflow_id: str) -> WorkflowAggregate | None:
        return self._workflows.get(workflow_id)

    async def save(self, aggregate: WorkflowAggregate) -> None:
        if aggregate.id:
            self._workflows[aggregate.id] = aggregate

    def add_workflow(self, workflow: WorkflowAggregate) -> None:
        """Add a workflow to the mock store."""
        if workflow.id:
            self._workflows[workflow.id] = workflow


class MockSessionRepository:
    """Mock session repository for testing."""

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSessionAggregate] = {}

    async def save(self, aggregate: AgentSessionAggregate) -> None:
        if aggregate.id:
            self._sessions[aggregate.id] = aggregate


class MockArtifactRepository:
    """Mock artifact repository for testing."""

    def __init__(self) -> None:
        self._artifacts: dict[str, ArtifactAggregate] = {}

    async def save(self, aggregate: ArtifactAggregate) -> None:
        if aggregate.id:
            self._artifacts[aggregate.id] = aggregate

    async def get_by_id(self, artifact_id: str) -> ArtifactAggregate | None:
        return self._artifacts.get(artifact_id)


class MockEventPublisher:
    """Mock event publisher for testing."""

    def __init__(self) -> None:
        self._events: list[Any] = []

    async def publish(self, events: list[Any]) -> None:
        self._events.extend(events)


def create_test_workflow(
    workflow_id: str = "test-workflow-123",
    name: str = "Test Workflow",
    phases: list[PhaseDefinition] | None = None,
) -> WorkflowAggregate:
    """Create a test workflow aggregate."""
    if phases is None:
        phases = [
            PhaseDefinition(
                phase_id="phase-1",
                name="Research Phase",
                order=1,
                description="Research the topic",
                prompt_template_id="Research: {{topic}}",
                output_artifact_types=["research_summary"],
            ),
            PhaseDefinition(
                phase_id="phase-2",
                name="Planning Phase",
                order=2,
                description="Create a plan",
                prompt_template_id="Plan based on: {{phase-1}}",
                output_artifact_types=["plan"],
            ),
        ]

    workflow = WorkflowAggregate()
    command = CreateWorkflowCommand(
        aggregate_id=workflow_id,
        name=name,
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.STANDARD,
        repository_url="https://github.com/test/repo",
        repository_ref="main",
        phases=phases,
        description="Test workflow for execution",
    )
    workflow._handle_command(command)
    return workflow


def get_workflow_id(workflow: WorkflowAggregate) -> str:
    """Get workflow ID, asserting it's not None."""
    workflow_id = workflow.id
    assert workflow_id is not None, "Workflow ID should not be None after creation"
    return workflow_id


# =============================================================================
# VALUE OBJECTS TESTS
# =============================================================================


class TestExecutionValueObjects:
    """Tests for execution value objects."""

    def test_phase_result_creation(self) -> None:
        """Test PhaseResult immutability."""
        result = PhaseResult(
            phase_id="phase-1",
            status=PhaseStatus.COMPLETED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            artifact_id="artifact-123",
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            cost_usd=Decimal("0.01"),
        )

        assert result.phase_id == "phase-1"
        assert result.status == PhaseStatus.COMPLETED
        assert result.total_tokens == 300

    def test_execution_metrics_from_results(self) -> None:
        """Test ExecutionMetrics aggregation."""
        now = datetime.now(UTC)
        results = [
            PhaseResult(
                phase_id="phase-1",
                status=PhaseStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                input_tokens=100,
                output_tokens=200,
                total_tokens=300,
                cost_usd=Decimal("0.01"),
            ),
            PhaseResult(
                phase_id="phase-2",
                status=PhaseStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                input_tokens=150,
                output_tokens=250,
                total_tokens=400,
                cost_usd=Decimal("0.015"),
            ),
        ]

        metrics = ExecutionMetrics.from_results(results)

        assert metrics.total_phases == 2
        assert metrics.completed_phases == 2
        assert metrics.failed_phases == 0
        assert metrics.total_input_tokens == 250
        assert metrics.total_output_tokens == 450
        assert metrics.total_tokens == 700
        assert metrics.total_cost_usd == Decimal("0.025")

    def test_execution_metrics_with_failed_phase(self) -> None:
        """Test metrics include failed phase counts."""
        results = [
            PhaseResult(
                phase_id="phase-1",
                status=PhaseStatus.COMPLETED,
                input_tokens=100,
                output_tokens=200,
                total_tokens=300,
            ),
            PhaseResult(
                phase_id="phase-2",
                status=PhaseStatus.FAILED,
                error_message="Test failure",
            ),
        ]

        metrics = ExecutionMetrics.from_results(results)

        assert metrics.total_phases == 2
        assert metrics.completed_phases == 1
        assert metrics.failed_phases == 1

    def test_executable_phase_default_config(self) -> None:
        """Test ExecutablePhase has default agent configuration."""
        phase = ExecutablePhase(
            phase_id="phase-1",
            name="Test Phase",
            order=1,
        )

        assert phase.agent_config.provider == "claude"  # Default is now Claude, not mock
        assert phase.agent_config.max_tokens == 4096
        assert phase.output_artifact_type == "text"


# =============================================================================
# WORKFLOW EXECUTION ENGINE TESTS
# =============================================================================


class TestWorkflowExecutionEngine:
    """Tests for WorkflowExecutionEngine."""

    @pytest.fixture
    def mock_agent(self) -> MockInstrumentedAgent:
        """Create mock agent with default responses."""
        return MockInstrumentedAgent(
            responses=[
                "Research findings about AI agents...",
                "Plan: 1. Step one 2. Step two...",
            ]
        )

    @pytest.fixture
    def workflow_repo(self) -> MockWorkflowRepository:
        """Create mock workflow repository."""
        return MockWorkflowRepository()

    @pytest.fixture
    def session_repo(self) -> MockSessionRepository:
        """Create mock session repository."""
        return MockSessionRepository()

    @pytest.fixture
    def artifact_repo(self) -> MockArtifactRepository:
        """Create mock artifact repository."""
        return MockArtifactRepository()

    @pytest.fixture
    def event_publisher(self) -> MockEventPublisher:
        """Create mock event publisher."""
        return MockEventPublisher()

    @pytest.fixture
    def engine(
        self,
        workflow_repo: MockWorkflowRepository,
        session_repo: MockSessionRepository,
        artifact_repo: MockArtifactRepository,
        event_publisher: MockEventPublisher,
        mock_agent: MockInstrumentedAgent,
    ) -> WorkflowExecutionEngine:
        """Create execution engine with mock dependencies."""

        def agent_factory(_provider: str) -> Any:
            return mock_agent

        return WorkflowExecutionEngine(
            workflow_repository=workflow_repo,
            session_repository=session_repo,
            artifact_repository=artifact_repo,
            agent_factory=cast("Any", agent_factory),
            event_publisher=event_publisher,
        )

    @pytest.mark.asyncio
    async def test_execute_workflow_not_found(self, engine: WorkflowExecutionEngine) -> None:
        """Test execution fails when workflow not found."""
        with pytest.raises(WorkflowNotFoundError) as exc_info:
            await engine.execute(
                workflow_id="nonexistent-workflow",
                inputs={"topic": "AI"},
            )

        assert exc_info.value.workflow_id == "nonexistent-workflow"

    @pytest.mark.asyncio
    async def test_execute_simple_workflow(
        self,
        engine: WorkflowExecutionEngine,
        workflow_repo: MockWorkflowRepository,
        artifact_repo: MockArtifactRepository,  # noqa: ARG002 - needed by fixture
        mock_agent: MockInstrumentedAgent,
    ) -> None:
        """Test executing a simple 2-phase workflow."""
        # Setup
        workflow = create_test_workflow()
        workflow_repo.add_workflow(workflow)

        # Execute
        result = await engine.execute(
            workflow_id=get_workflow_id(workflow),
            inputs={"topic": "AI agents"},
        )

        # Verify result
        assert result.is_success
        assert result.status == ExecutionStatus.COMPLETED
        assert len(result.phase_results) == 2
        assert len(result.artifact_ids) == 2

        # Verify phases executed
        assert result.phase_results[0].status == PhaseStatus.COMPLETED
        assert result.phase_results[1].status == PhaseStatus.COMPLETED

        # Verify agent was called
        assert len(mock_agent._calls) == 2

    @pytest.mark.asyncio
    async def test_execute_with_custom_execution_id(
        self,
        engine: WorkflowExecutionEngine,
        workflow_repo: MockWorkflowRepository,
    ) -> None:
        """Test custom execution ID is used."""
        workflow = create_test_workflow()
        workflow_repo.add_workflow(workflow)

        result = await engine.execute(
            workflow_id=get_workflow_id(workflow),
            inputs={"topic": "test"},
            execution_id="custom-exec-123",
        )

        assert result.execution_id == "custom-exec-123"

    @pytest.mark.asyncio
    async def test_phase_input_substitution(
        self,
        engine: WorkflowExecutionEngine,
        workflow_repo: MockWorkflowRepository,
        mock_agent: MockInstrumentedAgent,
    ) -> None:
        """Test prompt template variable substitution."""
        phases = [
            PhaseDefinition(
                phase_id="research",
                name="Research",
                order=1,
                prompt_template_id="Research topic: {{topic}}",
                output_artifact_types=["text"],
            ),
        ]
        workflow = create_test_workflow(phases=phases)
        workflow_repo.add_workflow(workflow)

        await engine.execute(
            workflow_id=get_workflow_id(workflow),
            inputs={"topic": "machine learning"},
        )

        # Check the prompt was built correctly
        assert len(mock_agent._calls) == 1
        call = mock_agent._calls[0]
        # The message content should have the topic substituted
        assert "machine learning" in call["messages"][0].content

    @pytest.mark.asyncio
    async def test_phase_chaining_with_previous_output(
        self,
        engine: WorkflowExecutionEngine,
        workflow_repo: MockWorkflowRepository,
        mock_agent: MockInstrumentedAgent,
    ) -> None:
        """Test that phase output is available to next phase."""
        phases = [
            PhaseDefinition(
                phase_id="phase1",
                name="Phase 1",
                order=1,
                prompt_template_id="Start with: {{topic}}",
                output_artifact_types=["text"],
            ),
            PhaseDefinition(
                phase_id="phase2",
                name="Phase 2",
                order=2,
                prompt_template_id="Continue from: {{phase1}}",
                output_artifact_types=["text"],
            ),
        ]
        workflow = create_test_workflow(phases=phases)
        workflow_repo.add_workflow(workflow)

        mock_agent.responses = [
            "Output from phase 1",
            "Output from phase 2",
        ]

        await engine.execute(
            workflow_id=get_workflow_id(workflow),
            inputs={"topic": "test"},
        )

        # Second call should have phase 1 output substituted
        assert len(mock_agent._calls) == 2
        second_call = mock_agent._calls[1]
        assert "Output from phase 1" in second_call["messages"][0].content

    @pytest.mark.asyncio
    async def test_execution_metrics_aggregated(
        self,
        engine: WorkflowExecutionEngine,
        workflow_repo: MockWorkflowRepository,
    ) -> None:
        """Test metrics are properly aggregated."""
        workflow = create_test_workflow()
        workflow_repo.add_workflow(workflow)

        result = await engine.execute(
            workflow_id=get_workflow_id(workflow),
            inputs={"topic": "test"},
        )

        # Each mock response has 300 total tokens
        assert result.metrics.total_phases == 2
        assert result.metrics.completed_phases == 2
        assert result.metrics.total_tokens == 600  # 300 per phase

    @pytest.mark.asyncio
    async def test_artifacts_created_for_each_phase(
        self,
        engine: WorkflowExecutionEngine,
        workflow_repo: MockWorkflowRepository,
        artifact_repo: MockArtifactRepository,
    ) -> None:
        """Test artifacts are created and stored."""
        workflow = create_test_workflow()
        workflow_repo.add_workflow(workflow)

        result = await engine.execute(
            workflow_id=get_workflow_id(workflow),
            inputs={"topic": "test"},
        )

        # Verify artifacts were saved
        assert len(artifact_repo._artifacts) == 2
        assert len(result.artifact_ids) == 2

        # Verify artifact contents
        for artifact_id in result.artifact_ids:
            artifact = artifact_repo._artifacts.get(artifact_id)
            assert artifact is not None
            assert artifact.content is not None

    @pytest.mark.asyncio
    async def test_session_context_set_for_each_phase(
        self,
        engine: WorkflowExecutionEngine,
        workflow_repo: MockWorkflowRepository,
        mock_agent: MockInstrumentedAgent,
    ) -> None:
        """Test session context is properly set for each phase."""
        workflow = create_test_workflow()
        workflow_repo.add_workflow(workflow)

        wf_id = get_workflow_id(workflow)
        await engine.execute(
            workflow_id=wf_id,
            inputs={"topic": "test"},
        )

        # Verify session context was set for each call
        for call in mock_agent._calls:
            ctx = call["session_context"]
            assert ctx["workflow_id"] == wf_id
            assert ctx["session_id"] is not None
            assert ctx["phase_id"] is not None


class TestWorkflowExecutionFailure:
    """Tests for workflow execution failure scenarios."""

    @pytest.fixture
    def failing_agent(self) -> MockInstrumentedAgent:
        """Create an agent that fails."""

        class FailingAgent(MockInstrumentedAgent):
            async def complete(
                self,
                messages: list[Any],  # noqa: ARG002
                config: Any,  # noqa: ARG002
            ) -> Any:
                raise RuntimeError("Agent failed!")

        return FailingAgent()

    @pytest.fixture
    def engine_with_failing_agent(
        self,
        failing_agent: MockInstrumentedAgent,
    ) -> WorkflowExecutionEngine:
        """Create engine with failing agent."""
        workflow_repo = MockWorkflowRepository()
        session_repo = MockSessionRepository()
        artifact_repo = MockArtifactRepository()
        event_publisher = MockEventPublisher()

        # Add test workflow
        workflow = create_test_workflow()
        workflow_repo._workflows[get_workflow_id(workflow)] = workflow

        def agent_factory(_provider: str) -> Any:
            return failing_agent

        return WorkflowExecutionEngine(
            workflow_repository=workflow_repo,
            session_repository=session_repo,
            artifact_repository=artifact_repo,
            agent_factory=cast("Any", agent_factory),
            event_publisher=event_publisher,
        )

    @pytest.mark.asyncio
    async def test_execution_failure_returns_failed_result(
        self, engine_with_failing_agent: WorkflowExecutionEngine
    ) -> None:
        """Test that agent failure is captured in result."""
        result = await engine_with_failing_agent.execute(
            workflow_id="test-workflow-123",
            inputs={"topic": "test"},
        )

        assert not result.is_success
        assert result.status == ExecutionStatus.FAILED
        assert result.error_message is not None
        assert "Agent failed" in result.error_message

    @pytest.mark.asyncio
    async def test_failure_records_partial_progress(
        self,
    ) -> None:
        """Test that partial progress is recorded on failure."""
        # Create agent that succeeds first, then fails
        call_count = 0

        class PartialFailAgent(MockInstrumentedAgent):
            async def complete(
                self,
                messages: list[Any],  # noqa: ARG002
                config: Any,  # noqa: ARG002
            ) -> Any:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return MockAgentResponse(content="Phase 1 complete")
                raise RuntimeError("Phase 2 failed!")

        agent = PartialFailAgent()
        workflow_repo = MockWorkflowRepository()
        workflow = create_test_workflow()
        workflow_repo.add_workflow(workflow)

        engine = WorkflowExecutionEngine(
            workflow_repository=workflow_repo,
            session_repository=MockSessionRepository(),
            artifact_repository=MockArtifactRepository(),
            agent_factory=cast("Any", lambda _p: agent),
            event_publisher=MockEventPublisher(),
        )

        result = await engine.execute(
            workflow_id=get_workflow_id(workflow),
            inputs={"topic": "test"},
        )

        # Should have recorded both phase results
        assert len(result.phase_results) == 2
        assert result.phase_results[0].status == PhaseStatus.COMPLETED
        assert result.phase_results[1].status == PhaseStatus.FAILED


class TestExecutionContext:
    """Tests for ExecutionContext."""

    def test_context_tracks_phase_outputs(self) -> None:
        """Test context stores phase outputs."""
        ctx = ExecutionContext(
            workflow_id="wf-123",
            execution_id="exec-123",
            started_at=datetime.now(UTC),
            inputs={"topic": "test"},
        )

        ctx.phase_outputs["phase-1"] = "Output from phase 1"
        ctx.phase_outputs["phase-2"] = "Output from phase 2"

        assert len(ctx.phase_outputs) == 2
        assert "Output from phase 1" in ctx.phase_outputs["phase-1"]

    def test_context_tracks_artifacts(self) -> None:
        """Test context stores artifact IDs."""
        ctx = ExecutionContext(
            workflow_id="wf-123",
            execution_id="exec-123",
            started_at=datetime.now(UTC),
            inputs={},
        )

        ctx.artifact_ids.append("artifact-1")
        ctx.artifact_ids.append("artifact-2")

        assert len(ctx.artifact_ids) == 2


class TestWorkflowExecutionResult:
    """Tests for WorkflowExecutionResult."""

    def test_is_success_property(self) -> None:
        """Test is_success returns correct value."""
        completed = WorkflowExecutionResult(
            workflow_id="wf-123",
            execution_id="exec-123",
            status=ExecutionStatus.COMPLETED,
            started_at=datetime.now(UTC),
        )
        failed = WorkflowExecutionResult(
            workflow_id="wf-123",
            execution_id="exec-123",
            status=ExecutionStatus.FAILED,
            started_at=datetime.now(UTC),
        )

        assert completed.is_success is True
        assert failed.is_success is False
