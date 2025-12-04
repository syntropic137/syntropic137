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
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
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
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
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
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
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
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
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


class TestWorkflowDetailProjectionHandlesAllEvents:
    """Test that WorkflowDetailProjection handles all workflow events."""

    @pytest.fixture
    def mock_store(self) -> AsyncMock:
        """Create a mock projection store."""
        store = AsyncMock()
        store.get = AsyncMock(return_value=None)
        store.save = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_projection_handles_phase_completed(self, mock_store: AsyncMock) -> None:
        """REGRESSION: Projection must handle PhaseCompleted to update phase metrics."""
        from aef_domain.contexts.workflows.slices.get_workflow_detail.projection import (
            WorkflowDetailProjection,
        )

        # Setup existing workflow
        mock_store.get = AsyncMock(
            return_value={
                "id": "workflow-1",
                "name": "Test Workflow",
                "status": "in_progress",
                "phases": [
                    {"phase_id": "phase-1", "name": "Research", "status": "pending"},
                    {"phase_id": "phase-2", "name": "Innovate", "status": "pending"},
                ],
            }
        )

        projection = WorkflowDetailProjection(mock_store)

        # Process PhaseCompleted event
        await projection.on_phase_completed(
            {
                "workflow_id": "workflow-1",
                "phase_id": "phase-1",
                "input_tokens": 100,
                "output_tokens": 200,
                "total_tokens": 300,
                "cost_usd": Decimal("0.05"),
                "duration_seconds": 10.5,
                "session_id": "session-1",
            }
        )

        # Verify save was called with updated data
        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]

        # Find the phase that was updated
        phase_1 = next(p for p in saved_data["phases"] if p["phase_id"] == "phase-1")
        assert phase_1["status"] == "completed"
        assert phase_1["input_tokens"] == 100
        assert phase_1["output_tokens"] == 200
        assert phase_1["total_tokens"] == 300


# =============================================================================
# Test: Session Events
# =============================================================================


class TestSessionEventProjectionConsistency:
    """Test that all session events are emitted AND projected correctly."""

    @pytest.mark.asyncio
    async def test_start_session_emits_event(self) -> None:
        """REGRESSION: StartSessionCommand must emit SessionStartedEvent."""
        from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions.start_session.StartSessionCommand import (
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
        from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions._shared.value_objects import OperationType
        from aef_domain.contexts.sessions.record_operation.RecordOperationCommand import (
            RecordOperationCommand,
        )
        from aef_domain.contexts.sessions.start_session.StartSessionCommand import (
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
        from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions.complete_session.CompleteSessionCommand import (
            CompleteSessionCommand,
        )
        from aef_domain.contexts.sessions.start_session.StartSessionCommand import (
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
        """Ensure WorkflowDetailProjection handles all workflow events."""
        from aef_domain.contexts.workflows.slices.get_workflow_detail.projection import (
            WorkflowDetailProjection,
        )

        required_handlers = [
            "on_workflow_created",
            "on_workflow_execution_started",
            "on_phase_started",
            "on_phase_completed",  # CRITICAL: This was missing!
            "on_workflow_completed",
            "on_workflow_failed",
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
