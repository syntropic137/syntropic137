"""Unit tests for InterruptExecutionCommand aggregate handler.

T-1: Verifies that the aggregate correctly handles interruption commands
and emits WorkflowInterruptedEvent with the expected data.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    InterruptExecutionCommand,
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowInterruptedEvent import (
    WorkflowInterruptedEvent,
)


def _make_aggregate() -> WorkflowExecutionAggregate:
    """Create a fresh aggregate (not yet started)."""
    return WorkflowExecutionAggregate()


def _start_aggregate(aggregate: WorkflowExecutionAggregate, execution_id: str = "exec-1") -> None:
    """Start the aggregate (transition to RUNNING)."""
    cmd = StartExecutionCommand(
        execution_id=execution_id,
        workflow_id="wf-1",
        workflow_name="Test Workflow",
        total_phases=2,
        inputs={"topic": "test"},
    )
    aggregate._handle_command(cmd)


@pytest.mark.unit
class TestInterruptExecution:
    """Tests for InterruptExecutionCommand aggregate handler."""

    def test_interrupt_from_running_sets_interrupted_status(self) -> None:
        """Interrupting a RUNNING execution sets status to INTERRUPTED."""
        aggregate = _make_aggregate()
        _start_aggregate(aggregate)
        assert aggregate.status == ExecutionStatus.RUNNING

        cmd = InterruptExecutionCommand(
            execution_id="exec-1",
            phase_id="p-1",
            git_sha="abc123",
            reason="User stopped",
        )
        aggregate._handle_command(cmd)

        assert aggregate.status == ExecutionStatus.INTERRUPTED

    def test_interrupt_emits_workflow_interrupted_event(self) -> None:
        """InterruptExecutionCommand emits a WorkflowInterruptedEvent."""
        aggregate = _make_aggregate()
        _start_aggregate(aggregate)

        initial_count = len(aggregate._uncommitted_events)

        cmd = InterruptExecutionCommand(
            execution_id="exec-1",
            phase_id="p-1",
            git_sha="abc123",
            partial_artifact_ids=["art-1"],
            reason="User stopped",
            partial_input_tokens=100,
            partial_output_tokens=50,
        )
        aggregate._handle_command(cmd)

        # _uncommitted_events contains EventEnvelope objects; .event is the DomainEvent
        new_envelopes = aggregate._uncommitted_events[initial_count:]
        interrupted_events = [
            e.event for e in new_envelopes if isinstance(e.event, WorkflowInterruptedEvent)
        ]
        assert len(interrupted_events) == 1

        evt = interrupted_events[0]
        assert evt.git_sha == "abc123"
        assert evt.phase_id == "p-1"
        assert evt.reason == "User stopped"
        assert evt.partial_artifact_ids == ["art-1"]
        assert evt.partial_input_tokens == 100
        assert evt.partial_output_tokens == 50

    def test_interrupt_from_not_started_raises(self) -> None:
        """Interrupting a not-yet-started aggregate raises ValueError."""
        aggregate = _make_aggregate()

        cmd = InterruptExecutionCommand(
            execution_id="exec-1",
            phase_id="p-1",
        )
        with pytest.raises(ValueError, match="Cannot interrupt"):
            aggregate._handle_command(cmd)

    def test_interrupt_without_git_sha_is_allowed(self) -> None:
        """git_sha is optional — interrupt works even if git is unavailable."""
        aggregate = _make_aggregate()
        _start_aggregate(aggregate)

        cmd = InterruptExecutionCommand(
            execution_id="exec-1",
            phase_id="p-1",
            git_sha=None,
        )
        aggregate._handle_command(cmd)

        assert aggregate.status == ExecutionStatus.INTERRUPTED

        new_events = aggregate._uncommitted_events
        interrupted = [e.event for e in new_events if isinstance(e.event, WorkflowInterruptedEvent)]
        assert interrupted[0].git_sha is None

    def test_interrupt_is_terminal_cannot_start_again(self) -> None:
        """INTERRUPTED status is terminal — further commands should fail."""
        from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            CompleteExecutionCommand,
        )

        aggregate = _make_aggregate()
        _start_aggregate(aggregate)

        # Interrupt
        aggregate._handle_command(InterruptExecutionCommand(execution_id="exec-1", phase_id="p-1"))
        assert aggregate.status == ExecutionStatus.INTERRUPTED

        # Cannot complete after interrupted
        with pytest.raises(ValueError):
            aggregate._handle_command(
                CompleteExecutionCommand(
                    execution_id="exec-1",
                    completed_phases=0,
                    total_phases=2,
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_cache_creation_tokens=0,
                    total_cache_read_tokens=0,
                    duration_seconds=0.0,
                    artifact_ids=[],
                )
            )
