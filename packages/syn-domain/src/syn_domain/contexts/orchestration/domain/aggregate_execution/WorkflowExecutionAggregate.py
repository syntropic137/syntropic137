"""WorkflowExecution aggregate - tracks execution lifecycle.

Each workflow execution is its own aggregate (keyed by execution_id).
Location: orchestration/domain/aggregate_execution/ (per ADR-020)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from event_sourcing import (
    AggregateRoot,
    DomainEvent,
    aggregate,
    command_handler,
    event_sourcing_handler,
)

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (  # noqa: TC001 - re-exported + used at runtime by @command_handler
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
    CancelExecutionCommand,
    CompleteExecutionCommand,
    CompletePhaseCommand,
    FailExecutionCommand,
    InterruptExecutionCommand,
    PauseExecutionCommand,
    ProvisionWorkspaceCompletedCommand,
    ResumeExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    PhaseDefinition,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
        AgentExecutionCompletedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ArtifactsCollectedForPhaseEvent import (
        ArtifactsCollectedForPhaseEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
        ExecutionCancelledEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionPausedEvent import (
        ExecutionPausedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
        ExecutionResumedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.NextPhaseReadyEvent import (
        NextPhaseReadyEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
        PhaseCompletedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import (
        PhaseStartedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
        WorkflowCompletedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
        WorkflowExecutionStartedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
        WorkflowFailedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowInterruptedEvent import (
        WorkflowInterruptedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
        WorkspaceProvisionedForPhaseEvent,
    )


def _evt(event: DomainEvent, field: str, default: Any = None) -> Any:
    """Get field from event, handling both typed and GenericDomainEvent formats.

    Returns Any because the caller knows the concrete type based on the field name.
    """
    if hasattr(event, field):
        return getattr(event, field)
    data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
    return data.get(field, default)


def _parse_phase_definitions(raw_defs: list[dict[str, Any]]) -> list[PhaseDefinition]:
    """Parse raw phase definition dicts into sorted PhaseDefinition objects."""
    return sorted(
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


@aggregate("WorkflowExecution")
class WorkflowExecutionAggregate(AggregateRoot["WorkflowExecutionStartedEvent"]):
    """Aggregate for tracking workflow execution lifecycle."""

    _aggregate_type: str

    def __init__(self) -> None:
        """Initialize aggregate."""
        super().__init__()
        self._workflow_id: str | None = None
        self._workflow_name: str | None = None
        self._status: ExecutionStatus = ExecutionStatus.RUNNING
        self._started_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._expected_completion_at: datetime | None = None
        self._total_phases: int = 0
        self._completed_phases: int = 0
        self._current_phase_order: int = 0
        self._total_tokens: int = 0
        self._artifact_ids: list[str] = []
        self._error: str | None = None
        self._phase_definitions: list[PhaseDefinition] = []
        self._phase_order_map: dict[str, int] = {}
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

        event = WorkflowCompletedEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            completed_at=datetime.now(UTC),
            total_phases=command.total_phases,
            completed_phases=command.completed_phases,
            total_input_tokens=command.total_input_tokens,
            total_output_tokens=command.total_output_tokens,
            total_tokens=command.total_input_tokens + command.total_output_tokens,
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
        """Handle StartPhaseCommand."""
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
        """Handle CompletePhaseCommand."""
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
        """Handle InterruptExecutionCommand."""
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

    @event_sourcing_handler("WorkflowExecutionStarted")
    def on_execution_started(self, event: WorkflowExecutionStartedEvent) -> None:
        """Apply WorkflowExecutionStartedEvent."""
        self._workflow_id = _evt(event, "workflow_id")
        self._workflow_name = _evt(event, "workflow_name")
        self._started_at = _evt(event, "started_at")
        self._total_phases = _evt(event, "total_phases", 0)
        self._expected_completion_at = _evt(event, "expected_completion_at")
        raw_defs: list[dict[str, Any]] = _evt(event, "phase_definitions") or []
        self._phase_definitions = _parse_phase_definitions(raw_defs)
        self._phase_order_map = {p.phase_id: p.order for p in self._phase_definitions}
        self._status = ExecutionStatus.RUNNING

    @event_sourcing_handler("WorkflowCompleted")
    def on_execution_completed(self, event: WorkflowCompletedEvent) -> None:
        """Apply WorkflowCompletedEvent."""
        self._completed_at = _evt(event, "completed_at")
        self._completed_phases = _evt(event, "completed_phases", 0)
        self._total_tokens = _evt(event, "total_tokens", 0)
        self._artifact_ids = list(_evt(event, "artifact_ids", []))
        self._status = ExecutionStatus.COMPLETED

    @event_sourcing_handler("WorkflowFailed")
    def on_execution_failed(self, event: WorkflowFailedEvent) -> None:
        """Apply WorkflowFailedEvent."""
        self._completed_at = _evt(event, "failed_at")
        self._error = _evt(event, "error_message")
        self._status = ExecutionStatus.FAILED

    @event_sourcing_handler("PhaseStarted")
    def on_phase_started(self, event: PhaseStartedEvent) -> None:
        """Apply PhaseStartedEvent."""
        self._current_phase_order = _evt(event, "phase_order", 0)

    @event_sourcing_handler("PhaseCompleted")
    def on_phase_completed(self, _event: PhaseCompletedEvent) -> None:
        """Apply PhaseCompletedEvent."""
        self._completed_phases += 1

    @event_sourcing_handler("WorkspaceProvisionedForPhase")
    def on_workspace_provisioned_for_phase(self, event: WorkspaceProvisionedForPhaseEvent) -> None:
        """Apply WorkspaceProvisionedForPhaseEvent."""
        self._current_phase_workspace_id = _evt(event, "workspace_id")

    @event_sourcing_handler("AgentExecutionCompleted")
    def on_agent_execution_completed(self, _event: AgentExecutionCompletedEvent) -> None:
        """Apply AgentExecutionCompletedEvent — no state change needed."""

    @event_sourcing_handler("ArtifactsCollectedForPhase")
    def on_artifacts_collected_for_phase(self, event: ArtifactsCollectedForPhaseEvent) -> None:
        """Apply ArtifactsCollectedForPhaseEvent."""
        self._artifact_ids.extend(_evt(event, "artifact_ids", []))

    @event_sourcing_handler("NextPhaseReady")
    def on_next_phase_ready(self, _event: NextPhaseReadyEvent) -> None:
        """Apply NextPhaseReadyEvent — to-do list projection reacts, not aggregate."""

    @event_sourcing_handler("ExecutionPaused")
    def on_execution_paused(self, _event: ExecutionPausedEvent) -> None:
        """Apply ExecutionPausedEvent."""
        self._status = ExecutionStatus.PAUSED

    @event_sourcing_handler("ExecutionResumed")
    def on_execution_resumed(self, _event: ExecutionResumedEvent) -> None:
        """Apply ExecutionResumedEvent."""
        self._status = ExecutionStatus.RUNNING

    @event_sourcing_handler("ExecutionCancelled")
    def on_execution_cancelled(self, event: ExecutionCancelledEvent) -> None:
        """Apply ExecutionCancelledEvent."""
        self._completed_at = _evt(event, "cancelled_at")
        self._status = ExecutionStatus.CANCELLED

    @event_sourcing_handler("WorkflowInterrupted")
    def on_execution_interrupted(self, event: WorkflowInterruptedEvent) -> None:
        """Apply WorkflowInterruptedEvent."""
        self._completed_at = _evt(event, "interrupted_at")
        self._status = ExecutionStatus.INTERRUPTED
