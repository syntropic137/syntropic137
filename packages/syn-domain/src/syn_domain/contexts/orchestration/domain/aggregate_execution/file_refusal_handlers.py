"""The aggregate's file-refusal command and event handlers (#1913).

A mixin of `WorkflowExecutionAggregate`, which is the only class that may use
it, as `evidence_handlers` is: the handlers are discovered on the aggregate's
class and run against its state. A phase's refused output is recorded on
`ArtifactsCollectedForPhase` when it completes and on
`OutputFilesRefusedForPhase` when it does not; both land in `_refused_files`,
so `refused_files_for` answers the same way on either route.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from event_sourcing import command_handler, event_sourcing_handler

from syn_domain.contexts.orchestration._shared.FileRefusalValueObjects import read_refusals
from syn_domain.contexts.orchestration.domain.aggregate_execution.replay import evt
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.domain.events.OutputFilesRefusedForPhaseEvent import (
    OutputFilesRefusedForPhaseEvent,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

    from syn_domain.contexts.orchestration._shared.FileRefusalValueObjects import FileRefusal
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        RecordRefusedOutputCommand,
    )


class FileRefusalHandlers:
    """File-refusal handlers over the aggregate's own replayed state."""

    if TYPE_CHECKING:
        # Owned and initialised by `WorkflowExecutionAggregate`.
        _refused_files: dict[str, tuple[FileRefusal, ...]]
        _status: ExecutionStatus
        _running_phase_id: str | None
        _workflow_id: str | None

        def _apply(self, event: DomainEvent) -> None: ...

    # The output files the phase's collection was refused, by path and reason.
    def refused_files_for(self, phase_id: str) -> tuple[FileRefusal, ...]:
        return self._refused_files.get(phase_id, ())

    @command_handler("RecordRefusedOutputCommand")
    def record_refused_output(self, command: RecordRefusedOutputCommand) -> None:
        """Handle RecordRefusedOutputCommand - an unfinished phase's refused output.

        Refused for any phase but the running one, as a push is: the output
        kept on the way out is the running phase's, before its outcome is told.
        """
        if self._status != ExecutionStatus.RUNNING or self._running_phase_id != command.phase_id:
            msg = f"Cannot record refused output for {command.phase_id}: it is not running"
            raise ValueError(msg)
        self._apply(
            OutputFilesRefusedForPhaseEvent(
                workflow_id=self._workflow_id or "",
                execution_id=command.aggregate_id,
                phase_id=command.phase_id,
                refused_files=list(command.refused_files),
                refused_at=datetime.now(UTC),
            )
        )

    @event_sourcing_handler("OutputFilesRefusedForPhase")
    def on_output_files_refused_for_phase(self, event: OutputFilesRefusedForPhaseEvent) -> None:
        """Apply OutputFilesRefusedForPhaseEvent - read by `refused_files_for`."""
        self._refused_files[evt(event, "phase_id")] = read_refusals(evt(event, "refused_files", []))
