"""Tests for AgentSession aggregate and value objects.

Tests cover:
- Session lifecycle (start -> record -> complete)
- Token accumulation (cost is Lane 2 telemetry, see session_cost projection)
- Operation recording
- Event sourcing behavior
"""

from typing import cast

import pytest

from syn_domain.contexts.agent_sessions import (
    AgentSessionAggregate,
    CompleteSessionCommand,
    OperationType,
    RecordOperationCommand,
    SessionStatus,
    StartSessionCommand,
    TokenMetrics,
)


@pytest.mark.unit
class TestTokenMetrics:
    """Tests for TokenMetrics value object."""

    def test_default_values(self) -> None:
        """Test default token values."""
        metrics = TokenMetrics()
        assert metrics.input_tokens == 0
        assert metrics.output_tokens == 0
        assert metrics.total_tokens == 0

    def test_total_includes_cache_tokens(self) -> None:
        """REGRESSION(#695): total_tokens must include all 4 components."""
        metrics = TokenMetrics(
            input_tokens=100,
            output_tokens=50,
            cache_creation_tokens=5000,
            cache_read_tokens=12000,
        )
        assert metrics.total_tokens == 100 + 50 + 5000 + 12000

    def test_addition(self) -> None:
        """Test adding token metrics with cache tokens (#695)."""
        m1 = TokenMetrics(
            input_tokens=100, output_tokens=50, cache_creation_tokens=3000, cache_read_tokens=8000
        )
        m2 = TokenMetrics(
            input_tokens=200, output_tokens=100, cache_creation_tokens=2000, cache_read_tokens=4000
        )
        result = m1 + m2
        assert result.input_tokens == 300
        assert result.output_tokens == 150
        assert result.cache_creation_tokens == 5000
        assert result.cache_read_tokens == 12000
        assert result.total_tokens == 300 + 150 + 5000 + 12000

    def test_immutable(self) -> None:
        """Test that TokenMetrics is immutable."""
        metrics = TokenMetrics()
        with pytest.raises(AttributeError):
            metrics.input_tokens = 100  # type: ignore[misc]


# CostMetrics removed (#695): cost is Lane 2 telemetry.
# Cost accounting is now tested in slices/session_cost/test_projection.py.


class TestAgentSessionAggregate:
    """Tests for AgentSessionAggregate."""

    def test_start_session(self) -> None:
        """Test starting a new session."""
        session = AgentSessionAggregate()

        command = StartSessionCommand(
            workflow_id="wf-123",
            phase_id="research",
            agent_provider="claude",
            agent_model="claude-sonnet-4-20250514",
        )

        session.start_session(command)

        assert session.id is not None
        assert session.workflow_id == "wf-123"
        assert session.phase_id == "research"
        assert session.status == SessionStatus.RUNNING
        assert len(session.get_uncommitted_events()) == 1

    def test_start_session_with_id(self) -> None:
        """Test starting session with provided ID."""
        session = AgentSessionAggregate()

        command = StartSessionCommand(
            aggregate_id="custom-session-id",
            workflow_id="wf-123",
            phase_id="research",
            agent_provider="mock",
        )

        session.start_session(command)

        assert str(session.id) == "custom-session-id"

    def test_start_session_twice_fails(self) -> None:
        """Test that starting a session twice raises error."""
        session = AgentSessionAggregate()
        command = StartSessionCommand(
            workflow_id="wf-123",
            phase_id="research",
            agent_provider="mock",
        )

        session.start_session(command)

        with pytest.raises(ValueError, match="already exists"):
            session.start_session(command)

    def test_record_operation(self) -> None:
        """Test recording an operation."""
        session = AgentSessionAggregate()
        session.start_session(
            StartSessionCommand(
                workflow_id="wf-123",
                phase_id="research",
                agent_provider="claude",
            )
        )

        command = RecordOperationCommand(
            aggregate_id=str(session.id),
            operation_type=OperationType.AGENT_REQUEST,
            duration_seconds=1.5,
            input_tokens=500,
            output_tokens=200,
            total_tokens=700,
        )

        session.record_operation(command)

        assert session.operation_count == 1
        assert session.tokens.total_tokens == 700
        assert session.tokens.input_tokens == 500
        assert session.tokens.output_tokens == 200

    def test_record_multiple_operations(self) -> None:
        """Test recording multiple operations accumulates metrics."""
        session = AgentSessionAggregate()
        session.start_session(
            StartSessionCommand(
                workflow_id="wf-123",
                phase_id="research",
                agent_provider="claude",
            )
        )

        # First operation
        session.record_operation(
            RecordOperationCommand(
                aggregate_id=str(session.id),
                operation_type=OperationType.AGENT_REQUEST,
                input_tokens=500,
                output_tokens=200,
                total_tokens=700,
            )
        )

        # Second operation
        session.record_operation(
            RecordOperationCommand(
                aggregate_id=str(session.id),
                operation_type=OperationType.TOOL_EXECUTION,
                tool_name="Write",
                duration_seconds=0.1,
                total_tokens=0,
            )
        )

        # Third operation
        session.record_operation(
            RecordOperationCommand(
                aggregate_id=str(session.id),
                operation_type=OperationType.AGENT_REQUEST,
                input_tokens=300,
                output_tokens=100,
                total_tokens=400,
            )
        )

        assert session.operation_count == 3
        assert session.tokens.total_tokens == 1100  # 700 + 0 + 400
        assert session.tokens.input_tokens == 800  # 500 + 0 + 300
        assert session.tokens.output_tokens == 300  # 200 + 0 + 100

    def test_record_operation_when_not_running_fails(self) -> None:
        """Test that recording when session is completed fails."""
        session = AgentSessionAggregate()
        session.start_session(
            StartSessionCommand(
                workflow_id="wf-123",
                phase_id="research",
                agent_provider="mock",
            )
        )

        # Complete the session
        session.complete_session(
            CompleteSessionCommand(
                aggregate_id=str(session.id),
                success=True,
            )
        )

        # Try to record - should fail
        with pytest.raises(ValueError, match="Cannot record operation"):
            session.record_operation(
                RecordOperationCommand(
                    aggregate_id=str(session.id),
                    operation_type=OperationType.AGENT_REQUEST,
                )
            )

    def test_complete_session_success(self) -> None:
        """Test completing a session successfully."""
        session = AgentSessionAggregate()
        session.start_session(
            StartSessionCommand(
                workflow_id="wf-123",
                phase_id="research",
                agent_provider="claude",
            )
        )

        # Record some operations
        session.record_operation(
            RecordOperationCommand(
                aggregate_id=str(session.id),
                operation_type=OperationType.AGENT_REQUEST,
                input_tokens=1000,
                output_tokens=500,
                total_tokens=1500,
            )
        )

        # Complete
        session.complete_session(
            CompleteSessionCommand(
                aggregate_id=str(session.id),
                success=True,
            )
        )

        assert session.status == SessionStatus.COMPLETED
        assert session.duration_seconds is not None
        assert session.tokens.total_tokens == 1500

    def test_complete_session_failure(self) -> None:
        """Test completing a session with failure."""
        session = AgentSessionAggregate()
        session.start_session(
            StartSessionCommand(
                workflow_id="wf-123",
                phase_id="research",
                agent_provider="mock",
            )
        )

        session.complete_session(
            CompleteSessionCommand(
                aggregate_id=str(session.id),
                success=False,
                error_message="Agent rate limited",
            )
        )

        assert session.status == SessionStatus.FAILED

    def test_complete_already_completed_fails(self) -> None:
        """Test that completing an already completed session fails."""
        session = AgentSessionAggregate()
        session.start_session(
            StartSessionCommand(
                workflow_id="wf-123",
                phase_id="research",
                agent_provider="mock",
            )
        )

        session.complete_session(
            CompleteSessionCommand(
                aggregate_id=str(session.id),
                success=True,
            )
        )

        with pytest.raises(ValueError, match="Cannot complete session"):
            session.complete_session(
                CompleteSessionCommand(
                    aggregate_id=str(session.id),
                    success=True,
                )
            )

    def test_full_session_lifecycle(self) -> None:
        """Test complete session lifecycle from start to finish."""
        session = AgentSessionAggregate()

        # Start
        session.start_session(
            StartSessionCommand(
                workflow_id="wf-demo",
                phase_id="research",
                milestone_id="m1",
                agent_provider="claude",
                agent_model="claude-sonnet-4-20250514",
                metadata={"project": "test-project"},
            )
        )

        assert session.status == SessionStatus.RUNNING

        # Record agent request
        session.record_operation(
            RecordOperationCommand(
                aggregate_id=str(session.id),
                operation_type=OperationType.AGENT_REQUEST,
                duration_seconds=2.5,
                input_tokens=1000,
                output_tokens=500,
                total_tokens=1500,
            )
        )

        # Record tool execution
        session.record_operation(
            RecordOperationCommand(
                aggregate_id=str(session.id),
                operation_type=OperationType.TOOL_EXECUTION,
                tool_name="Bash",
                duration_seconds=0.1,
                success=True,
            )
        )

        # Record another agent request
        session.record_operation(
            RecordOperationCommand(
                aggregate_id=str(session.id),
                operation_type=OperationType.AGENT_REQUEST,
                duration_seconds=1.8,
                input_tokens=800,
                output_tokens=300,
                total_tokens=1100,
            )
        )

        # Verify accumulated metrics
        assert session.operation_count == 3
        assert session.tokens.total_tokens == 2600

        # Complete
        session.complete_session(
            CompleteSessionCommand(
                aggregate_id=str(session.id),
                success=True,
            )
        )

        # Status changes after command is processed (cast needed for mypy)
        final_status = cast("SessionStatus", session.status)
        assert final_status == SessionStatus.COMPLETED
        assert session.duration_seconds is not None
        assert session.duration_seconds > 0

        # Verify all events generated
        events = session.get_uncommitted_events()
        assert len(events) == 5  # started, 3 operations, completed


class TestAgentSessionEventSourcing:
    """Tests for event sourcing behavior."""

    def test_uncommitted_events_cleared_after_mark(self) -> None:
        """Test that mark_events_as_committed clears events."""
        session = AgentSessionAggregate()
        session.start_session(
            StartSessionCommand(
                workflow_id="wf-123",
                phase_id="research",
                agent_provider="mock",
            )
        )

        assert len(session.get_uncommitted_events()) == 1

        session.mark_events_as_committed()

        assert len(session.get_uncommitted_events()) == 0

    def test_aggregate_type(self) -> None:
        """Test aggregate type is set correctly."""
        session = AgentSessionAggregate()
        session.start_session(
            StartSessionCommand(
                workflow_id="wf-123",
                phase_id="research",
                agent_provider="mock",
            )
        )

        assert session.get_aggregate_type() == "AgentSession"
