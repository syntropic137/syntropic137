"""WorkflowExecution aggregate - tracks execution lifecycle.

Each workflow execution is its own aggregate, allowing multiple
concurrent executions of the same workflow without conflicts.

The aggregate_id is the execution_id (not workflow_id).

Location: orchestration/domain/aggregate_execution/ (per ADR-020)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal  # noqa: TC003 - used at runtime for dataclass
from typing import TYPE_CHECKING, Any

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    PhaseDefinition,
)

if TYPE_CHECKING:
    pass  # Additional type hints as needed
    from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
        WorkflowCompletedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
        WorkflowExecutionStartedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
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
        phase_definitions: list[PhaseDefinition] | None = None,
    ) -> None:
        """Initialize command.

        Args:
            execution_id: Unique execution ID
            workflow_id: Workflow being executed
            workflow_name: Name of the workflow
            total_phases: Number of phases to execute
            inputs: Input parameters for the workflow
            expected_completion_at: When we expect this to complete (for stale detection)
            phase_definitions: Ordered phase definitions for aggregate sequencing.
                Optional for backward compatibility — when absent, the aggregate
                does not make sequencing decisions (legacy engine mode).
        """
        self.aggregate_id = execution_id
        self.workflow_id = workflow_id
        self.workflow_name = workflow_name
        self.total_phases = total_phases
        self.inputs = inputs
        self.expected_completion_at = expected_completion_at
        self.phase_definitions = phase_definitions


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


class InterruptExecutionCommand:
    """Command to forcefully interrupt a workflow execution mid-stream.

    Distinct from CancelExecutionCommand (cooperative cancel) — this command
    represents a forceful stop via SIGINT to the Claude CLI process, capturing
    partial state (git SHA, partial artifacts, partial token counts).
    """

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        git_sha: str | None = None,
        partial_artifact_ids: list[str] | None = None,
        reason: str | None = None,
        partial_input_tokens: int = 0,
        partial_output_tokens: int = 0,
    ) -> None:
        """Initialize command."""
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.git_sha = git_sha
        self.partial_artifact_ids = partial_artifact_ids or []
        self.reason = reason
        self.partial_input_tokens = partial_input_tokens
        self.partial_output_tokens = partial_output_tokens


class ProvisionWorkspaceCompletedCommand:
    """Command reported by WorkspaceProvisionHandler after workspace is ready."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        workspace_id: str,
        session_id: str = "",
    ) -> None:
        """Initialize command."""
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.workspace_id = workspace_id
        self.session_id = session_id


class AgentExecutionCompletedCommand:
    """Command reported by AgentExecutionHandler after agent finishes."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        session_id: str | None,
        exit_code: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Initialize command."""
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.session_id = session_id
        self.exit_code = exit_code
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class ArtifactsCollectedCommand:
    """Command reported by ArtifactCollectionHandler after outputs stored."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        artifact_ids: list[str],
        first_content_preview: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Initialize command."""
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.artifact_ids = artifact_ids
        self.first_content_preview = first_content_preview
        self.session_id = session_id


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
        # Phase intelligence (Processor To-Do List pattern, ISS-196)
        self._phase_definitions: list[PhaseDefinition] = []
        self._phase_order_map: dict[str, int] = {}  # phase_id → order index
        self._current_phase_workspace_id: str | None = None

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
        from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
            WorkflowExecutionStartedEvent,
        )

        if self.id is not None:
            msg = "Execution already started"
            raise ValueError(msg)

        self._initialize(command.aggregate_id)

        # Serialize phase definitions for event storage
        phase_defs_data: list[dict[str, Any]] | None = None
        if command.phase_definitions:
            phase_defs_data = [
                {
                    "phase_id": pd.phase_id,
                    "name": pd.name,
                    "order": pd.order,
                    "timeout_seconds": pd.timeout_seconds,
                }
                for pd in command.phase_definitions
            ]

        event = WorkflowExecutionStartedEvent(
            workflow_id=command.workflow_id,
            execution_id=command.aggregate_id,
            workflow_name=command.workflow_name,
            started_at=datetime.now(UTC),
            total_phases=command.total_phases,
            inputs=command.inputs,
            expected_completion_at=command.expected_completion_at,
            phase_definitions=phase_defs_data,
        )
        self._apply(event)

    @command_handler("CompleteExecutionCommand")
    def complete_execution(self, command: CompleteExecutionCommand) -> None:
        """Handle CompleteExecutionCommand."""
        from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
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
        self._apply(event)

    @command_handler("FailExecutionCommand")
    def fail_execution(self, command: FailExecutionCommand) -> None:
        """Handle FailExecutionCommand."""
        from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
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
        self._apply(event)

    @command_handler("StartPhaseCommand")
    def start_phase(self, command: StartPhaseCommand) -> None:
        """Handle StartPhaseCommand - emit PhaseStartedEvent."""
        from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import (
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
        self._apply(event)

    @command_handler("CompletePhaseCommand")
    def complete_phase(self, command: CompletePhaseCommand) -> None:
        """Handle CompletePhaseCommand - emit PhaseCompletedEvent."""
        from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
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
        self._apply(event)

    # =========================================================================
    # PROCESSOR TO-DO LIST COMMAND HANDLERS (ISS-196)
    # =========================================================================

    @command_handler("ProvisionWorkspaceCompletedCommand")
    def provision_workspace_completed(self, command: ProvisionWorkspaceCompletedCommand) -> None:
        """Handle workspace provisioned for a phase."""
        from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
            WorkspaceProvisionedForPhaseEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot provision workspace in status {self._status}"
            raise ValueError(msg)

        event = WorkspaceProvisionedForPhaseEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            workspace_id=command.workspace_id,
            session_id=command.session_id,
            provisioned_at=datetime.now(UTC),
        )
        self._apply(event)

    @command_handler("AgentExecutionCompletedCommand")
    def agent_execution_completed(self, command: AgentExecutionCompletedCommand) -> None:
        """Handle agent finished executing in workspace."""
        from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
            AgentExecutionCompletedEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot complete agent execution in status {self._status}"
            raise ValueError(msg)

        event = AgentExecutionCompletedEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            session_id=command.session_id,
            completed_at=datetime.now(UTC),
            exit_code=command.exit_code,
            input_tokens=command.input_tokens,
            output_tokens=command.output_tokens,
        )
        self._apply(event)

    @command_handler("ArtifactsCollectedCommand")
    def artifacts_collected(self, command: ArtifactsCollectedCommand) -> None:
        """Handle artifacts collected — aggregate decides if more phases exist."""
        from syn_domain.contexts.orchestration.domain.events.ArtifactsCollectedForPhaseEvent import (
            ArtifactsCollectedForPhaseEvent,
        )
        from syn_domain.contexts.orchestration.domain.events.NextPhaseReadyEvent import (
            NextPhaseReadyEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot collect artifacts in status {self._status}"
            raise ValueError(msg)

        event = ArtifactsCollectedForPhaseEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            artifact_ids=command.artifact_ids,
            collected_at=datetime.now(UTC),
            first_content_preview=command.first_content_preview,
            session_id=command.session_id,
        )
        self._apply(event)

        # Aggregate decides: is there a next phase?
        if self._phase_definitions:
            current_order = self._phase_order_map.get(command.phase_id)
            if current_order is not None:
                next_phase = self._find_next_phase(current_order)
                if next_phase is not None:
                    next_event = NextPhaseReadyEvent(
                        workflow_id=self._workflow_id or "",
                        execution_id=command.aggregate_id,
                        completed_phase_id=command.phase_id,
                        next_phase_id=next_phase.phase_id,
                        next_phase_order=next_phase.order,
                        decided_at=datetime.now(UTC),
                    )
                    self._apply(next_event)

    def _find_next_phase(self, current_order: int) -> PhaseDefinition | None:
        """Find the next phase after the given order, or None if this was the last."""
        for phase_def in self._phase_definitions:
            if phase_def.order > current_order:
                return phase_def
        return None

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
            # Phase definitions for aggregate sequencing (ISS-196)
            raw_defs: list[dict[str, Any]] = getattr(event, "phase_definitions", []) or []
            self._phase_definitions = sorted(
                [
                    PhaseDefinition(
                        phase_id=d["phase_id"],
                        name=d["name"],
                        order=d["order"],
                        timeout_seconds=d.get("timeout_seconds", 300),
                    )
                    for d in raw_defs
                ],
                key=lambda p: p.order,
            )
            self._phase_order_map = {p.phase_id: p.order for p in self._phase_definitions}
        else:
            # Dict-based event from gRPC
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._workflow_id = data.get("workflow_id")
            self._workflow_name = data.get("workflow_name")
            self._started_at = data.get("started_at")
            self._total_phases = data.get("total_phases", 0)
            self._expected_completion_at = data.get("expected_completion_at")
            raw_defs = data.get("phase_definitions", []) or []
            self._phase_definitions = sorted(
                [
                    PhaseDefinition(
                        phase_id=d["phase_id"],
                        name=d["name"],
                        order=d["order"],
                        timeout_seconds=d.get("timeout_seconds", 300),
                    )
                    for d in raw_defs
                ],
                key=lambda p: p.order,
            )
            self._phase_order_map = {p.phase_id: p.order for p in self._phase_definitions}

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

    @event_sourcing_handler("WorkspaceProvisionedForPhase")
    def on_workspace_provisioned_for_phase(self, event: Any) -> None:
        """Apply WorkspaceProvisionedForPhaseEvent — track current workspace."""
        if hasattr(event, "workspace_id"):
            self._current_phase_workspace_id = event.workspace_id
        else:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._current_phase_workspace_id = data.get("workspace_id")

    @event_sourcing_handler("AgentExecutionCompleted")
    def on_agent_execution_completed(self, _event: Any) -> None:
        """Apply AgentExecutionCompletedEvent — no state change needed."""

    @event_sourcing_handler("ArtifactsCollectedForPhase")
    def on_artifacts_collected_for_phase(self, event: Any) -> None:
        """Apply ArtifactsCollectedForPhaseEvent — track artifact IDs."""
        if hasattr(event, "artifact_ids"):
            self._artifact_ids.extend(event.artifact_ids)
        else:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._artifact_ids.extend(data.get("artifact_ids", []))

    @event_sourcing_handler("NextPhaseReady")
    def on_next_phase_ready(self, _event: Any) -> None:
        """Apply NextPhaseReadyEvent — no additional state change needed.

        The to-do list projection reacts to this event, not the aggregate.
        """

    # =========================================================================
    # CONTROL PLANE COMMAND HANDLERS
    # =========================================================================

    @command_handler("PauseExecutionCommand")
    def pause_execution(self, command: PauseExecutionCommand) -> None:
        """Handle PauseExecutionCommand."""
        from syn_domain.contexts.orchestration.domain.events.ExecutionPausedEvent import (
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
        self._apply(event)

    @command_handler("ResumeExecutionCommand")
    def resume_execution(self, command: ResumeExecutionCommand) -> None:
        """Handle ResumeExecutionCommand."""
        from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
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
        self._apply(event)

    @command_handler("CancelExecutionCommand")
    def cancel_execution(self, command: CancelExecutionCommand) -> None:
        """Handle CancelExecutionCommand."""
        from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
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
        self._apply(event)

    @command_handler("InterruptExecutionCommand")
    def interrupt_execution(self, command: InterruptExecutionCommand) -> None:
        """Handle InterruptExecutionCommand.

        Forceful interrupt: engine received CANCEL signal mid-streaming, sent SIGINT
        to Claude CLI, and captured partial state. Distinct from CancelExecutionCommand
        (cooperative user cancel via control plane).
        """
        from syn_domain.contexts.orchestration.domain.events.WorkflowInterruptedEvent import (
            WorkflowInterruptedEvent,
        )

        if self.id is None:
            msg = "Cannot interrupt execution that has not been started"
            raise ValueError(msg)
        if self._status is not ExecutionStatus.RUNNING:
            msg = f"Cannot interrupt execution in status {self._status}"
            raise ValueError(msg)

        event = WorkflowInterruptedEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            interrupted_at=datetime.now(UTC),
            reason=command.reason,
            git_sha=command.git_sha,
            partial_artifact_ids=command.partial_artifact_ids,
            partial_input_tokens=command.partial_input_tokens,
            partial_output_tokens=command.partial_output_tokens,
        )
        self._apply(event)

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

    @event_sourcing_handler("WorkflowInterrupted")
    def on_execution_interrupted(self, event: Any) -> None:
        """Apply WorkflowInterruptedEvent."""
        if hasattr(event, "interrupted_at"):
            self._completed_at = event.interrupted_at
        else:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._completed_at = data.get("interrupted_at")
        self._status = ExecutionStatus.INTERRUPTED
