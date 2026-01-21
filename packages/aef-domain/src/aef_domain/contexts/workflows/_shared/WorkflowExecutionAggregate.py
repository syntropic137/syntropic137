"""WorkflowExecution aggregate - tracks execution lifecycle.

Each workflow execution is its own aggregate, allowing multiple
concurrent executions of the same workflow without conflicts.

The aggregate_id is the execution_id (not workflow_id).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal  # noqa: TC003 - used at runtime for dataclass
from typing import TYPE_CHECKING, Any

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from aef_domain.contexts.workflows._shared.ExecutionValueObjects import ExecutionStatus

if TYPE_CHECKING:
    pass  # Additional type hints as needed
    from aef_domain.contexts.workflows.slices.execute_workflow.WorkflowCompletedEvent import (
        WorkflowCompletedEvent,
    )
    from aef_domain.contexts.workflows.slices.execute_workflow.WorkflowExecutionStartedEvent import (
        WorkflowExecutionStartedEvent,
    )
    from aef_domain.contexts.workflows.slices.execute_workflow.WorkflowFailedEvent import (
        WorkflowFailedEvent,
    )


# =============================================================================
# Commands
# =============================================================================


class StartExecutionCommand:
    """Command to start a workflow execution."""

    def __init__(
        self,
        execution_id: str,
        workflow_id: str,
        workflow_name: str,
        total_phases: int,
        inputs: dict[str, Any],
        expected_completion_at: datetime | None = None,
    ) -> None:
        """Initialize command.

        Args:
            execution_id: Unique execution ID
            workflow_id: Workflow being executed
            workflow_name: Name of the workflow
            total_phases: Number of phases to execute
            inputs: Input parameters for the workflow
            expected_completion_at: When we expect this to complete (for stale detection)
        """
        self.aggregate_id = execution_id
        self.workflow_id = workflow_id
        self.workflow_name = workflow_name
        self.total_phases = total_phases
        self.inputs = inputs
        self.expected_completion_at = expected_completion_at


class CompleteExecutionCommand:
    """Command to mark a workflow execution as completed."""

    def __init__(
        self,
        execution_id: str,
        completed_phases: int,
        total_phases: int,
        total_input_tokens: int,
        total_output_tokens: int,
        total_cost_usd: Decimal,
        duration_seconds: float,
        artifact_ids: list[str],
    ) -> None:
        """Initialize command."""
        self.aggregate_id = execution_id
        self.completed_phases = completed_phases
        self.total_phases = total_phases
        self.total_input_tokens = total_input_tokens
        self.total_output_tokens = total_output_tokens
        self.total_cost_usd = total_cost_usd
        self.duration_seconds = duration_seconds
        self.artifact_ids = artifact_ids


class FailExecutionCommand:
    """Command to mark a workflow execution as failed."""

    def __init__(
        self,
        execution_id: str,
        error: str,
        error_type: str | None,
        failed_phase_id: str | None,
        completed_phases: int,
        total_phases: int,
    ) -> None:
        """Initialize command."""
        self.aggregate_id = execution_id
        self.error = error
        self.error_type = error_type
        self.failed_phase_id = failed_phase_id
        self.completed_phases = completed_phases
        self.total_phases = total_phases


class StartPhaseCommand:
    """Command to start a phase execution."""

    def __init__(
        self,
        execution_id: str,
        workflow_id: str,
        phase_id: str,
        phase_name: str,
        phase_order: int,
        session_id: str | None = None,
    ) -> None:
        """Initialize command."""
        self.aggregate_id = execution_id
        self.workflow_id = workflow_id
        self.phase_id = phase_id
        self.phase_name = phase_name
        self.phase_order = phase_order
        self.session_id = session_id


class CompletePhaseCommand:
    """Command to mark a phase as completed with metrics."""

    def __init__(
        self,
        execution_id: str,
        workflow_id: str,
        phase_id: str,
        session_id: str | None,
        artifact_id: str | None,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cost_usd: Decimal,
        duration_seconds: float,
    ) -> None:
        """Initialize command."""
        self.aggregate_id = execution_id
        self.workflow_id = workflow_id
        self.phase_id = phase_id
        self.session_id = session_id
        self.artifact_id = artifact_id
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        self.cost_usd = cost_usd
        self.duration_seconds = duration_seconds


class PauseExecutionCommand:
    """Command to pause a workflow execution."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        reason: str | None = None,
    ) -> None:
        """Initialize command."""
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.reason = reason


class ResumeExecutionCommand:
    """Command to resume a paused workflow execution."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
    ) -> None:
        """Initialize command."""
        self.aggregate_id = execution_id
        self.phase_id = phase_id


class CancelExecutionCommand:
    """Command to cancel a workflow execution."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        reason: str | None = None,
    ) -> None:
        """Initialize command."""
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.reason = reason


# =============================================================================
# Aggregate
# =============================================================================


@aggregate("WorkflowExecution")
class WorkflowExecutionAggregate(AggregateRoot["WorkflowExecutionStartedEvent"]):
    """Aggregate for tracking workflow execution lifecycle.

    Each execution instance is its own aggregate, keyed by execution_id.
    This allows multiple concurrent executions without conflicts.

    Events emitted:
    - WorkflowExecutionStarted: Execution begins
    - WorkflowCompleted: Execution succeeds
    - WorkflowFailed: Execution fails
    """

    _aggregate_type: str  # Set by @aggregate decorator

    def __init__(self) -> None:
        """Initialize aggregate."""
        super().__init__()
        self._workflow_id: str | None = None
        self._workflow_name: str | None = None
        self._status: ExecutionStatus = ExecutionStatus.RUNNING
        self._started_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._expected_completion_at: datetime | None = None  # For stale detection
        self._total_phases: int = 0
        self._completed_phases: int = 0
        self._current_phase_order: int = 0
        self._total_tokens: int = 0
        self._artifact_ids: list[str] = []
        self._error: str | None = None

    def get_aggregate_type(self) -> str:
        """Return aggregate type name."""
        return self._aggregate_type

    @property
    def workflow_id(self) -> str | None:
        """Get the workflow ID being executed."""
        return self._workflow_id

    @property
    def status(self) -> ExecutionStatus:
        """Get execution status."""
        return self._status

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    @command_handler("StartExecutionCommand")
    def start_execution(self, command: StartExecutionCommand) -> None:
        """Handle StartExecutionCommand."""
        from aef_domain.contexts.workflows.slices.execute_workflow.WorkflowExecutionStartedEvent import (
            WorkflowExecutionStartedEvent,
        )

        if self.id is not None:
            msg = "Execution already started"
            raise ValueError(msg)

        self._initialize(command.aggregate_id)

        event = WorkflowExecutionStartedEvent(
            workflow_id=command.workflow_id,
            execution_id=command.aggregate_id,
            workflow_name=command.workflow_name,
            started_at=datetime.now(UTC),
            total_phases=command.total_phases,
            inputs=command.inputs,
            expected_completion_at=command.expected_completion_at,
        )
        self._apply(event)

    @command_handler("CompleteExecutionCommand")
    def complete_execution(self, command: CompleteExecutionCommand) -> None:
        """Handle CompleteExecutionCommand."""
        from aef_domain.contexts.workflows.slices.execute_workflow.WorkflowCompletedEvent import (
            WorkflowCompletedEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot complete execution in status {self._status}"
            raise ValueError(msg)

        total_tokens = command.total_input_tokens + command.total_output_tokens

        event = WorkflowCompletedEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            completed_at=datetime.now(UTC),
            total_phases=command.total_phases,
            completed_phases=command.completed_phases,
            total_input_tokens=command.total_input_tokens,
            total_output_tokens=command.total_output_tokens,
            total_tokens=total_tokens,
            total_cost_usd=command.total_cost_usd,
            total_duration_seconds=command.duration_seconds,
            artifact_ids=command.artifact_ids,
        )
        self._apply(event)  # type: ignore[arg-type]

    @command_handler("FailExecutionCommand")
    def fail_execution(self, command: FailExecutionCommand) -> None:
        """Handle FailExecutionCommand."""
        from aef_domain.contexts.workflows.slices.execute_workflow.WorkflowFailedEvent import (
            WorkflowFailedEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot fail execution in status {self._status}"
            raise ValueError(msg)

        event = WorkflowFailedEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            failed_at=datetime.now(UTC),
            failed_phase_id=command.failed_phase_id,
            error_message=command.error,
            error_type=command.error_type,
            completed_phases=command.completed_phases,
            total_phases=command.total_phases,
        )
        self._apply(event)  # type: ignore[arg-type]

    @command_handler("StartPhaseCommand")
    def start_phase(self, command: StartPhaseCommand) -> None:
        """Handle StartPhaseCommand - emit PhaseStartedEvent."""
        from aef_domain.contexts.workflows.slices.execute_workflow.PhaseStartedEvent import (
            PhaseStartedEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot start phase in status {self._status}"
            raise ValueError(msg)

        event = PhaseStartedEvent(
            workflow_id=command.workflow_id,
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            phase_name=command.phase_name,
            phase_order=command.phase_order,
            started_at=datetime.now(UTC),
            session_id=command.session_id,
        )
        self._apply(event)  # type: ignore[arg-type]

    @command_handler("CompletePhaseCommand")
    def complete_phase(self, command: CompletePhaseCommand) -> None:
        """Handle CompletePhaseCommand - emit PhaseCompletedEvent."""
        from aef_domain.contexts.workflows.slices.execute_workflow.PhaseCompletedEvent import (
            PhaseCompletedEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot complete phase in status {self._status}"
            raise ValueError(msg)

        event = PhaseCompletedEvent(
            workflow_id=command.workflow_id,
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            completed_at=datetime.now(UTC),
            success=True,
            artifact_id=command.artifact_id,
            session_id=command.session_id,
            input_tokens=command.input_tokens,
            output_tokens=command.output_tokens,
            total_tokens=command.total_tokens,
            cost_usd=command.cost_usd,
            duration_seconds=command.duration_seconds,
        )
        self._apply(event)  # type: ignore[arg-type]

    # =========================================================================
    # EVENT SOURCING HANDLERS
    # =========================================================================

    @event_sourcing_handler("WorkflowExecutionStarted")
    def on_execution_started(self, event: WorkflowExecutionStartedEvent) -> None:
        """Apply WorkflowExecutionStartedEvent."""
        if hasattr(event, "workflow_id"):
            self._workflow_id = event.workflow_id
            self._workflow_name = event.workflow_name
            self._started_at = event.started_at
            self._total_phases = event.total_phases
            self._expected_completion_at = getattr(event, "expected_completion_at", None)
        else:
            # Dict-based event from gRPC
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._workflow_id = data.get("workflow_id")
            self._workflow_name = data.get("workflow_name")
            self._started_at = data.get("started_at")
            self._total_phases = data.get("total_phases", 0)
            self._expected_completion_at = data.get("expected_completion_at")

        self._status = ExecutionStatus.RUNNING

    @event_sourcing_handler("WorkflowCompleted")
    def on_execution_completed(self, event: WorkflowCompletedEvent) -> None:
        """Apply WorkflowCompletedEvent."""
        if hasattr(event, "completed_at"):
            self._completed_at = event.completed_at
            self._completed_phases = event.completed_phases
            self._total_tokens = event.total_tokens
            self._artifact_ids = list(event.artifact_ids)
        else:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._completed_at = data.get("completed_at")
            self._completed_phases = data.get("completed_phases", 0)
            self._total_tokens = data.get("total_tokens", 0)
            self._artifact_ids = data.get("artifact_ids", [])

        self._status = ExecutionStatus.COMPLETED

    @event_sourcing_handler("WorkflowFailed")
    def on_execution_failed(self, event: WorkflowFailedEvent) -> None:
        """Apply WorkflowFailedEvent."""
        if hasattr(event, "failed_at"):
            self._completed_at = event.failed_at
            self._error = event.error_message
        else:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._completed_at = data.get("failed_at")
            self._error = data.get("error_message")

        self._status = ExecutionStatus.FAILED

    @event_sourcing_handler("PhaseStarted")
    def on_phase_started(self, event: Any) -> None:
        """Apply PhaseStartedEvent - track current phase."""
        # Track the current phase order for ordering/validation purposes
        if hasattr(event, "phase_order"):
            self._current_phase_order = event.phase_order
        else:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._current_phase_order = data.get("phase_order", 0)

    @event_sourcing_handler("PhaseCompleted")
    def on_phase_completed(self, _event: Any) -> None:
        """Apply PhaseCompletedEvent - track completed phases."""
        # Increment completed phases count
        # Note: We don't use event data here - just counting phases
        self._completed_phases += 1

    # =========================================================================
    # CONTROL PLANE COMMAND HANDLERS
    # =========================================================================

    @command_handler("PauseExecutionCommand")
    def pause_execution(self, command: PauseExecutionCommand) -> None:
        """Handle PauseExecutionCommand."""
        from aef_domain.contexts.workflows.slices.execute_workflow.ExecutionPausedEvent import (
            ExecutionPausedEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot pause execution in status {self._status}"
            raise ValueError(msg)

        event = ExecutionPausedEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            paused_at=datetime.now(UTC),
            reason=command.reason,
        )
        self._apply(event)  # type: ignore[arg-type]

    @command_handler("ResumeExecutionCommand")
    def resume_execution(self, command: ResumeExecutionCommand) -> None:
        """Handle ResumeExecutionCommand."""
        from aef_domain.contexts.workflows.slices.execute_workflow.ExecutionResumedEvent import (
            ExecutionResumedEvent,
        )

        if self._status != ExecutionStatus.PAUSED:
            msg = f"Cannot resume execution in status {self._status}"
            raise ValueError(msg)

        event = ExecutionResumedEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            resumed_at=datetime.now(UTC),
        )
        self._apply(event)  # type: ignore[arg-type]

    @command_handler("CancelExecutionCommand")
    def cancel_execution(self, command: CancelExecutionCommand) -> None:
        """Handle CancelExecutionCommand."""
        from aef_domain.contexts.workflows.slices.execute_workflow.ExecutionCancelledEvent import (
            ExecutionCancelledEvent,
        )

        if self._status not in (ExecutionStatus.RUNNING, ExecutionStatus.PAUSED):
            msg = f"Cannot cancel execution in status {self._status}"
            raise ValueError(msg)

        event = ExecutionCancelledEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            cancelled_at=datetime.now(UTC),
            reason=command.reason,
        )
        self._apply(event)  # type: ignore[arg-type]

    # =========================================================================
    # CONTROL PLANE EVENT SOURCING HANDLERS
    # =========================================================================

    @event_sourcing_handler("ExecutionPaused")
    def on_execution_paused(self, _event: Any) -> None:
        """Apply ExecutionPausedEvent."""
        self._status = ExecutionStatus.PAUSED

    @event_sourcing_handler("ExecutionResumed")
    def on_execution_resumed(self, _event: Any) -> None:
        """Apply ExecutionResumedEvent."""
        self._status = ExecutionStatus.RUNNING

    @event_sourcing_handler("ExecutionCancelled")
    def on_execution_cancelled(self, event: Any) -> None:
        """Apply ExecutionCancelledEvent."""
        if hasattr(event, "cancelled_at"):
            self._completed_at = event.cancelled_at
        else:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._completed_at = data.get("cancelled_at")
        self._status = ExecutionStatus.CANCELLED
