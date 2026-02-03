"""Regression tests for event sourcing and projection consistency.

These tests ensure that:
1. All commands emit the expected domain events
2. All domain events have corresponding projection handlers
3. The projection state is updated correctly after event processing

This prevents the class of bugs where:
- Events are defined but never emitted
- Events are emitted but never handled by projections
- Projection state doesn't reflect the event data correctly
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

# =============================================================================
# Test: Workflow Execution Events
# =============================================================================


@pytest.mark.unit
class TestWorkflowExecutionEventProjectionConsistency:
    """Test that all workflow execution events are emitted AND projected correctly."""

    @pytest.fixture
    def mock_projection_store(self) -> MagicMock:
        """Create mock projection store."""
        store = AsyncMock()
        store.get = AsyncMock(return_value=None)
        store.save = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_start_execution_emits_event(self) -> None:
        """REGRESSION: StartExecutionCommand must emit WorkflowExecutionStartedEvent."""
        from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        aggregate = WorkflowExecutionAggregate()
        command = StartExecutionCommand(
            execution_id="exec-1",
            workflow_id="workflow-1",
            workflow_name="Test Workflow",
            total_phases=5,
            inputs={"topic": "test"},
        )

        aggregate._handle_command(command)

        # Verify event was emitted
        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.__class__.__name__ == "WorkflowExecutionStartedEvent"
        assert events[0].event.workflow_id == "workflow-1"
        assert events[0].event.execution_id == "exec-1"
        assert events[0].event.total_phases == 5

    @pytest.mark.asyncio
    async def test_complete_phase_emits_event(self) -> None:
        """REGRESSION: CompletePhaseCommand must emit PhaseCompletedEvent."""
        from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            CompletePhaseCommand,
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        aggregate = WorkflowExecutionAggregate()

        # First start the execution
        start_cmd = StartExecutionCommand(
            execution_id="exec-1",
            workflow_id="workflow-1",
            workflow_name="Test Workflow",
            total_phases=5,
            inputs={},
        )
        aggregate._handle_command(start_cmd)

        # Mark events as committed to clear them
        aggregate.mark_events_as_committed()

        # Now complete a phase
        phase_cmd = CompletePhaseCommand(
            execution_id="exec-1",
            workflow_id="workflow-1",
            phase_id="phase-1",
            session_id="session-1",
            artifact_id="artifact-1",
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            cost_usd=Decimal("0.05"),
            duration_seconds=10.5,
        )
        aggregate._handle_command(phase_cmd)

        # Verify PhaseCompleted event was emitted
        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        event = events[0].event
        assert event.__class__.__name__ == "PhaseCompletedEvent"
        assert event.workflow_id == "workflow-1"
        assert event.execution_id == "exec-1"
        assert event.phase_id == "phase-1"
        assert event.input_tokens == 100
        assert event.output_tokens == 200
        assert event.total_tokens == 300
        assert event.cost_usd == Decimal("0.05")
        assert event.duration_seconds == 10.5

    @pytest.mark.asyncio
    async def test_complete_execution_emits_event(self) -> None:
        """REGRESSION: CompleteExecutionCommand must emit WorkflowCompletedEvent."""
        from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            CompleteExecutionCommand,
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        aggregate = WorkflowExecutionAggregate()

        # Start execution first
        start_cmd = StartExecutionCommand(
            execution_id="exec-1",
            workflow_id="workflow-1",
            workflow_name="Test Workflow",
            total_phases=5,
            inputs={},
        )
        aggregate._handle_command(start_cmd)
        aggregate.mark_events_as_committed()

        # Complete execution
        complete_cmd = CompleteExecutionCommand(
            execution_id="exec-1",
            completed_phases=5,
            total_phases=5,
            total_input_tokens=500,
            total_output_tokens=1000,
            total_cost_usd=Decimal("0.50"),
            duration_seconds=120.0,
            artifact_ids=["a1", "a2"],
        )
        aggregate._handle_command(complete_cmd)

        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.__class__.__name__ == "WorkflowCompletedEvent"
        assert events[0].event.total_input_tokens == 500
        assert events[0].event.total_output_tokens == 1000

    @pytest.mark.asyncio
    async def test_fail_execution_emits_event(self) -> None:
        """REGRESSION: FailExecutionCommand must emit WorkflowFailedEvent."""
        from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            FailExecutionCommand,
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        aggregate = WorkflowExecutionAggregate()

        # Start execution first
        start_cmd = StartExecutionCommand(
            execution_id="exec-1",
            workflow_id="workflow-1",
            workflow_name="Test Workflow",
            total_phases=5,
            inputs={},
        )
        aggregate._handle_command(start_cmd)
        aggregate.mark_events_as_committed()

        # Fail execution
        fail_cmd = FailExecutionCommand(
            execution_id="exec-1",
            error="Something went wrong",
            error_type="RuntimeError",
            failed_phase_id="phase-2",
            completed_phases=1,
            total_phases=5,
        )
        aggregate._handle_command(fail_cmd)

        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.__class__.__name__ == "WorkflowFailedEvent"
        assert events[0].event.error_message == "Something went wrong"


class TestWorkflowTemplateProjectionHandlesTemplateEvents:
    """Test that WorkflowDetailProjection handles TEMPLATE events.

    Note: WorkflowDetailProjection is for TEMPLATES only.
    Execution events are handled by WorkflowExecutionDetailProjection.
    """

    @pytest.fixture
    def mock_store(self) -> AsyncMock:
        """Create a mock projection store."""
        store = AsyncMock()
        store.get = AsyncMock(return_value=None)
        store.save = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_projection_increments_runs_count_on_execution_started(
        self, mock_store: AsyncMock
    ) -> None:
        """Template projection should increment runs_count when execution starts."""
        from aef_domain.contexts.orchestration.slices.get_workflow_detail.projection import (
            WorkflowDetailProjection,
        )

        # Setup existing workflow template
        mock_store.get = AsyncMock(
            return_value={
                "id": "workflow-1",
                "name": "Test Workflow",
                "workflow_type": "research",
                "classification": "standard",
                "description": None,
                "phases": [
                    {"id": "phase-1", "name": "Research", "order": 0},
                ],
                "created_at": None,
                "runs_count": 5,
            }
        )

        projection = WorkflowDetailProjection(mock_store)

        # Process WorkflowExecutionStarted event
        await projection.on_workflow_execution_started(
            {
                "workflow_id": "workflow-1",
                "execution_id": "exec-1",
                "started_at": "2025-01-01T00:00:00",
            }
        )

        # Verify save was called with incremented runs_count
        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]
        assert saved_data["runs_count"] == 6


# =============================================================================
# Test: Session Events
# =============================================================================


class TestSessionEventProjectionConsistency:
    """Test that all session events are emitted AND projected correctly."""

    @pytest.mark.asyncio
    async def test_start_session_emits_event(self) -> None:
        """REGRESSION: StartSessionCommand must emit SessionStartedEvent."""
        from aef_domain.contexts.sessions.domain.aggregate_session.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions.domain.commands.StartSessionCommand import (
            StartSessionCommand,
        )

        aggregate = AgentSessionAggregate()
        command = StartSessionCommand(
            aggregate_id="session-1",
            workflow_id="workflow-1",
            phase_id="phase-1",
            agent_provider="claude",
        )
        aggregate._handle_command(command)

        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.__class__.__name__ == "SessionStartedEvent"
        assert events[0].event.workflow_id == "workflow-1"
        assert events[0].event.phase_id == "phase-1"

    @pytest.mark.asyncio
    async def test_record_operation_emits_event(self) -> None:
        """REGRESSION: RecordOperationCommand must emit OperationRecordedEvent."""
        from aef_domain.contexts.sessions._shared.value_objects import OperationType
        from aef_domain.contexts.sessions.domain.aggregate_session.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions.domain.commands.RecordOperationCommand import (
            RecordOperationCommand,
        )
        from aef_domain.contexts.sessions.domain.commands.StartSessionCommand import (
            StartSessionCommand,
        )

        aggregate = AgentSessionAggregate()

        # Start session first
        start_cmd = StartSessionCommand(
            aggregate_id="session-1",
            workflow_id="workflow-1",
            phase_id="phase-1",
            agent_provider="claude",
        )
        aggregate._handle_command(start_cmd)
        aggregate.mark_events_as_committed()

        # Record operation
        op_cmd = RecordOperationCommand(
            aggregate_id="session-1",
            operation_type=OperationType.AGENT_REQUEST,
            duration_seconds=5.0,
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            tool_name=None,
            success=True,
            metadata={},
        )
        aggregate._handle_command(op_cmd)

        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.__class__.__name__ == "OperationRecordedEvent"
        # OperationRecordedEvent stores total_tokens, not tokens_used
        assert events[0].event.total_tokens == 300

    @pytest.mark.asyncio
    async def test_complete_session_emits_event(self) -> None:
        """REGRESSION: CompleteSessionCommand must emit SessionCompletedEvent."""
        from aef_domain.contexts.sessions.domain.aggregate_session.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions.domain.commands.CompleteSessionCommand import (
            CompleteSessionCommand,
        )
        from aef_domain.contexts.sessions.domain.commands.StartSessionCommand import (
            StartSessionCommand,
        )

        aggregate = AgentSessionAggregate()

        # Start session first
        start_cmd = StartSessionCommand(
            aggregate_id="session-1",
            workflow_id="workflow-1",
            phase_id="phase-1",
            agent_provider="claude",
        )
        aggregate._handle_command(start_cmd)
        aggregate.mark_events_as_committed()

        # Complete session
        complete_cmd = CompleteSessionCommand(
            aggregate_id="session-1",
            success=True,
            error_message=None,
        )
        aggregate._handle_command(complete_cmd)

        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.__class__.__name__ == "SessionCompletedEvent"
        # SessionCompletedEvent uses status enum, not success boolean
        assert events[0].event.status.value == "completed"


class TestSessionListProjectionHandlesAllEvents:
    """Test that SessionListProjection handles all session events."""

    @pytest.fixture
    def mock_store(self) -> AsyncMock:
        """Create a mock projection store."""
        store = AsyncMock()
        store.get = AsyncMock(return_value=None)
        store.save = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_projection_handles_operation_recorded(self, mock_store: AsyncMock) -> None:
        """REGRESSION: Projection must handle OperationRecorded to store operations."""
        from aef_domain.contexts.sessions.slices.list_sessions.projection import (
            SessionListProjection,
        )

        # Setup existing session
        mock_store.get = AsyncMock(
            return_value={
                "id": "session-1",
                "workflow_id": "workflow-1",
                "status": "running",
                "total_tokens": 0,
                "operations": [],
            }
        )

        projection = SessionListProjection(mock_store)

        # Process OperationRecorded event
        await projection.on_operation_recorded(
            {
                "session_id": "session-1",
                "operation_type": "agent_request",
                "tokens_used": 300,
                "input_tokens": 100,
                "output_tokens": 200,
                "cost_usd": Decimal("0.05"),
                "recorded_at": datetime.now(UTC).isoformat(),
            }
        )

        # Verify save was called with updated data including operations
        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]
        assert saved_data["total_tokens"] == 300
        assert len(saved_data["operations"]) == 1
        assert saved_data["operations"][0]["input_tokens"] == 100
        assert saved_data["operations"][0]["output_tokens"] == 200


# =============================================================================
# Test: Event Handler Registry Completeness
# =============================================================================


class TestEventHandlerCompleteness:
    """Test that all domain events have corresponding projection handlers.

    This is a meta-test that ensures we don't forget to handle events.
    """

    def test_workflow_detail_projection_has_required_handlers(self) -> None:
        """Ensure WorkflowDetailProjection (TEMPLATE) handles template events.

        Note: WorkflowDetailProjection is for TEMPLATES, not executions.
        Execution events are handled by WorkflowExecutionDetailProjection.
        """
        from aef_domain.contexts.orchestration.slices.get_workflow_detail.projection import (
            WorkflowDetailProjection,
        )

        # Template projection only needs these handlers
        required_handlers = [
            "on_workflow_created",
            "on_workflow_execution_started",  # To increment runs_count
        ]

        for handler in required_handlers:
            assert hasattr(WorkflowDetailProjection, handler), (
                f"WorkflowDetailProjection missing handler: {handler}"
            )

    def test_session_list_projection_has_required_handlers(self) -> None:
        """Ensure SessionListProjection handles all session events."""
        from aef_domain.contexts.sessions.slices.list_sessions.projection import (
            SessionListProjection,
        )

        required_handlers = [
            "on_session_started",
            "on_operation_recorded",  # CRITICAL: Must store operations!
            "on_session_completed",
        ]

        for handler in required_handlers:
            assert hasattr(SessionListProjection, handler), (
                f"SessionListProjection missing handler: {handler}"
            )

    def test_workflow_execution_list_projection_has_required_handlers(self) -> None:
        """REGRESSION: Ensure WorkflowExecutionListProjection handles all execution events."""
        from aef_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        required_handlers = [
            "on_workflow_execution_started",
            "on_phase_completed",
            "on_workflow_completed",
            "on_workflow_failed",
        ]

        for handler in required_handlers:
            assert hasattr(WorkflowExecutionListProjection, handler), (
                f"WorkflowExecutionListProjection missing handler: {handler}"
            )

    def test_workflow_execution_detail_projection_has_required_handlers(self) -> None:
        """REGRESSION: Ensure WorkflowExecutionDetailProjection handles all execution events."""
        from aef_domain.contexts.orchestration.slices.get_execution_detail.projection import (
            WorkflowExecutionDetailProjection,
        )

        required_handlers = [
            "on_workflow_execution_started",
            "on_phase_completed",
            "on_workflow_completed",
            "on_workflow_failed",
        ]

        for handler in required_handlers:
            assert hasattr(WorkflowExecutionDetailProjection, handler), (
                f"WorkflowExecutionDetailProjection missing handler: {handler}"
            )


# =============================================================================
# Test: Workflow Execution Model (F7.6)
# =============================================================================


class TestWorkflowExecutionListProjection:
    """REGRESSION: Test WorkflowExecutionListProjection handles events correctly."""

    @pytest.fixture
    def mock_store(self) -> AsyncMock:
        """Create a mock projection store."""
        store = AsyncMock()
        store.get = AsyncMock(return_value=None)
        store.save = AsyncMock()
        store.get_all = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_handles_workflow_execution_started(self, mock_store: AsyncMock) -> None:
        """REGRESSION: Projection must create execution summary on start."""
        from aef_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        projection = WorkflowExecutionListProjection(mock_store)

        await projection.on_workflow_execution_started(
            {
                "execution_id": "exec-1",
                "workflow_id": "workflow-1",
                "workflow_name": "Test Workflow",
                "started_at": "2024-12-04T10:00:00Z",
                "total_phases": 5,
            }
        )

        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]
        assert saved_data["workflow_execution_id"] == "exec-1"
        assert saved_data["workflow_id"] == "workflow-1"
        assert saved_data["status"] == "running"
        assert saved_data["total_phases"] == 5
        assert saved_data["completed_phases"] == 0

    @pytest.mark.asyncio
    async def test_handles_phase_completed_updates_metrics(self, mock_store: AsyncMock) -> None:
        """REGRESSION: Projection must update metrics when phase completes."""
        from aef_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        # Setup existing execution
        mock_store.get = AsyncMock(
            return_value={
                "execution_id": "exec-1",
                "workflow_id": "workflow-1",
                "status": "running",
                "completed_phases": 1,
                "total_phases": 5,
                "total_tokens": 500,
                "total_cost_usd": "0.10",
            }
        )

        projection = WorkflowExecutionListProjection(mock_store)

        await projection.on_phase_completed(
            {
                "execution_id": "exec-1",
                "phase_id": "phase-2",
                "total_tokens": 300,
                "cost_usd": Decimal("0.05"),
            }
        )

        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]
        assert saved_data["completed_phases"] == 2
        assert saved_data["total_tokens"] == 800  # 500 + 300
        assert saved_data["total_cost_usd"] == "0.15"  # 0.10 + 0.05

    @pytest.mark.asyncio
    async def test_handles_workflow_completed(self, mock_store: AsyncMock) -> None:
        """REGRESSION: Projection must mark execution as completed."""
        from aef_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        mock_store.get = AsyncMock(
            return_value={
                "execution_id": "exec-1",
                "status": "running",
                "completed_phases": 4,
            }
        )

        projection = WorkflowExecutionListProjection(mock_store)

        await projection.on_workflow_completed(
            {
                "execution_id": "exec-1",
                "completed_at": "2024-12-04T11:00:00Z",
                "completed_phases": 5,
                "total_tokens": 2000,
                "total_cost_usd": "0.50",
            }
        )

        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]
        assert saved_data["status"] == "completed"
        assert saved_data["completed_at"] == "2024-12-04T11:00:00Z"

    @pytest.mark.asyncio
    async def test_handles_workflow_failed(self, mock_store: AsyncMock) -> None:
        """REGRESSION: Projection must mark execution as failed."""
        from aef_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        mock_store.get = AsyncMock(
            return_value={
                "execution_id": "exec-1",
                "status": "running",
            }
        )

        projection = WorkflowExecutionListProjection(mock_store)

        await projection.on_workflow_failed(
            {
                "execution_id": "exec-1",
                "failed_at": "2024-12-04T10:30:00Z",
                "error_message": "Agent timeout",
            }
        )

        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]
        assert saved_data["status"] == "failed"
        assert saved_data["completed_at"] == "2024-12-04T10:30:00Z"

    @pytest.mark.asyncio
    async def test_get_by_workflow_id_filters_correctly(self, mock_store: AsyncMock) -> None:
        """REGRESSION: get_by_workflow_id must filter and sort executions."""
        from aef_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        mock_store.get_all = AsyncMock(
            return_value=[
                {
                    "execution_id": "exec-1",
                    "workflow_id": "workflow-1",
                    "workflow_name": "Test",
                    "status": "completed",
                    "started_at": "2024-12-04T09:00:00Z",
                    "completed_phases": 3,
                    "total_phases": 3,
                    "total_tokens": 1000,
                    "total_cost_usd": "0.20",
                },
                {
                    "execution_id": "exec-2",
                    "workflow_id": "workflow-1",
                    "workflow_name": "Test",
                    "status": "completed",
                    "started_at": "2024-12-04T10:00:00Z",  # Later, should be first
                    "completed_phases": 3,
                    "total_phases": 3,
                    "total_tokens": 1500,
                    "total_cost_usd": "0.30",
                },
                {
                    "execution_id": "exec-3",
                    "workflow_id": "workflow-2",  # Different workflow
                    "workflow_name": "Other",
                    "status": "completed",
                    "started_at": "2024-12-04T11:00:00Z",
                    "completed_phases": 2,
                    "total_phases": 2,
                    "total_tokens": 500,
                    "total_cost_usd": "0.10",
                },
            ]
        )

        projection = WorkflowExecutionListProjection(mock_store)
        executions = await projection.get_by_workflow_id("workflow-1")

        assert len(executions) == 2
        assert all(e.workflow_id == "workflow-1" for e in executions)
        # Should be sorted by started_at descending
        assert executions[0].workflow_execution_id == "exec-2"
        assert executions[1].workflow_execution_id == "exec-1"


class TestWorkflowExecutionDetailProjection:
    """REGRESSION: Test WorkflowExecutionDetailProjection handles events correctly."""

    @pytest.fixture
    def mock_store(self) -> AsyncMock:
        """Create a mock projection store."""
        store = AsyncMock()
        store.get = AsyncMock(return_value=None)
        store.save = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_handles_workflow_execution_started(self, mock_store: AsyncMock) -> None:
        """REGRESSION: Projection must create execution detail on start."""
        from aef_domain.contexts.orchestration.slices.get_execution_detail.projection import (
            WorkflowExecutionDetailProjection,
        )

        projection = WorkflowExecutionDetailProjection(mock_store)

        await projection.on_workflow_execution_started(
            {
                "execution_id": "exec-1",
                "workflow_id": "workflow-1",
                "workflow_name": "Test Workflow",
                "started_at": "2024-12-04T10:00:00Z",
                "total_phases": 3,
            }
        )

        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]
        assert saved_data["execution_id"] == "exec-1"
        assert saved_data["workflow_name"] == "Test Workflow"
        assert saved_data["status"] == "running"
        assert saved_data["phases"] == []  # Empty until phases complete

    @pytest.mark.asyncio
    async def test_handles_phase_completed_adds_phase_detail(self, mock_store: AsyncMock) -> None:
        """REGRESSION: Projection must add phase detail when phase completes."""
        from aef_domain.contexts.orchestration.slices.get_execution_detail.projection import (
            WorkflowExecutionDetailProjection,
        )

        mock_store.get = AsyncMock(
            return_value={
                "execution_id": "exec-1",
                "workflow_id": "workflow-1",
                "workflow_name": "Test Workflow",
                "status": "running",
                "phases": [],
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost_usd": "0",
                "artifact_ids": [],
            }
        )

        projection = WorkflowExecutionDetailProjection(mock_store)

        await projection.on_phase_completed(
            {
                "execution_id": "exec-1",
                "phase_id": "research",
                "phase_name": "Research",
                "session_id": "session-1",
                "artifact_id": "artifact-1",
                "input_tokens": 100,
                "output_tokens": 200,
                "cost_usd": Decimal("0.05"),
                "duration_seconds": 10.5,
            }
        )

        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]
        assert len(saved_data["phases"]) == 1
        phase = saved_data["phases"][0]
        assert phase["phase_id"] == "research"
        # Name falls back to phase_name from event, or phase_id if not provided
        assert phase["name"] in ("Research", "research")
        assert phase["session_id"] == "session-1"
        assert phase["input_tokens"] == 100
        assert phase["output_tokens"] == 200
        assert saved_data["total_input_tokens"] == 100
        assert saved_data["total_output_tokens"] == 200


class TestSessionExecutionLinkage:
    """REGRESSION: Test that sessions are properly linked to executions."""

    @pytest.mark.asyncio
    async def test_session_started_event_includes_execution_id(self) -> None:
        """REGRESSION: SessionStartedEvent must include execution_id."""
        from aef_domain.contexts.sessions.domain.aggregate_session.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions.domain.commands.StartSessionCommand import (
            StartSessionCommand,
        )

        aggregate = AgentSessionAggregate()
        command = StartSessionCommand(
            aggregate_id="session-1",
            workflow_id="workflow-1",
            execution_id="exec-1",  # This must be included
            phase_id="phase-1",
            agent_provider="claude",
        )
        aggregate._handle_command(command)

        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        event = events[0].event
        assert event.__class__.__name__ == "SessionStartedEvent"
        assert event.execution_id == "exec-1"

    @pytest.mark.asyncio
    async def test_session_projection_stores_execution_id(self) -> None:
        """REGRESSION: SessionListProjection must store execution_id."""
        from aef_domain.contexts.sessions.slices.list_sessions.projection import (
            SessionListProjection,
        )

        mock_store = AsyncMock()
        mock_store.get = AsyncMock(return_value=None)
        mock_store.save = AsyncMock()

        projection = SessionListProjection(mock_store)

        await projection.on_session_started(
            {
                "session_id": "session-1",
                "workflow_id": "workflow-1",
                "execution_id": "exec-1",
                "phase_id": "phase-1",
                "agent_provider": "claude",
                "started_at": "2024-12-04T10:00:00Z",
            }
        )

        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]
        assert saved_data["execution_id"] == "exec-1"


# =============================================================================
# Test: Projection Manager Event Registration
# =============================================================================


class TestProjectionManagerEventRegistration:
    """REGRESSION: Test that ProjectionManager routes events to correct projections."""

    def test_execution_events_registered_to_execution_list_projection(self) -> None:
        """REGRESSION: Execution events must be routed to workflow_execution_list projection."""
        from aef_adapters.projections.manager import EVENT_HANDLERS

        # Verify execution events are routed to workflow_execution_list
        execution_events = [
            "WorkflowExecutionStarted",
            "PhaseCompleted",
            "WorkflowCompleted",
            "WorkflowFailed",
        ]
        for event in execution_events:
            assert event in EVENT_HANDLERS, f"Event {event} not in handlers"
            projections = [h[0] for h in EVENT_HANDLERS[event]]
            assert "workflow_execution_list" in projections, (
                f"Event {event} not routed to workflow_execution_list projection"
            )

    def test_execution_events_registered_to_execution_detail_projection(self) -> None:
        """REGRESSION: Execution events must be routed to workflow_execution_detail projection."""
        from aef_adapters.projections.manager import EVENT_HANDLERS

        execution_events = [
            "WorkflowExecutionStarted",
            "PhaseCompleted",
            "WorkflowCompleted",
            "WorkflowFailed",
        ]
        for event in execution_events:
            assert event in EVENT_HANDLERS, f"Event {event} not in handlers"
            projections = [h[0] for h in EVENT_HANDLERS[event]]
            assert "workflow_execution_detail" in projections, (
                f"Event {event} not routed to workflow_execution_detail projection"
            )
