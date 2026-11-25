"""The aggregate's retained-workspace command and event handlers (#2321).

A mixin of `WorkflowExecutionAggregate`, which is the only class that may use
it, as `file_refusal_handlers` is: the handlers are discovered on the
aggregate's class and run against its state. The fact they record is about a
workspace the guard kept, so it is accepted in every status: the startup guard
reaches a run whose process died, whatever status it was left in.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from event_sourcing import command_handler, event_sourcing_handler

from syn_domain.contexts.orchestration.domain.aggregate_execution.replay import evt
from syn_domain.contexts.orchestration.domain.aggregate_execution.workspace_retention import (
    retained_event,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkspaceRetentionValueObjects import (
    WORK_UNPROVEN,
    RetainedReason,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from event_sourcing import DomainEvent

    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        RecordWorkspaceRetainedCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.PhaseWorkspaceRetainedEvent import (
        PhaseWorkspaceRetainedEvent,
    )


class WorkspaceRetentionHandlers:
    """Retained-workspace handlers over the aggregate's own replayed state."""

    # Both replaced, never mutated, so the class defaults are never shared state.
    #: The phase each provisioned workspace was for: the guards cannot know it.
    _workspace_phases: Mapping[str, str] = MappingProxyType({})
    #: Each (workspace, reason) already recorded as retained.
    _retained: frozenset[tuple[str, RetainedReason]] = frozenset()

    if TYPE_CHECKING:
        # Owned and initialised by `WorkflowExecutionAggregate`.
        _workflow_id: str | None

        @property
        def id(self) -> str | None: ...

        def _apply(self, event: DomainEvent) -> None: ...

    def _provisioned_for(self, workspace_id: str, phase_id: str) -> None:
        """Remember which phase a replayed `WorkspaceProvisionedForPhase` was for."""
        self._workspace_phases = {**self._workspace_phases, workspace_id: phase_id}

    @command_handler("RecordWorkspaceRetainedCommand")
    def record_workspace_retained(self, command: RecordWorkspaceRetainedCommand) -> None:
        """Record a workspace kept because its work is unproven, in any status.

        No event when this workspace was already recorded for this reason: a
        guard that keeps it again states the same fact. The phase is the one
        this run's own stream provisioned the workspace for; the guards that
        keep it cannot know it.
        """
        if self.id is None:
            msg = "Execution does not exist"
            raise ValueError(msg)
        if command.reason not in WORK_UNPROVEN:
            msg = f"{command.reason.value} says nothing about the work; it is not retained work"
            raise ValueError(msg)
        if (command.workspace_handle, command.reason) in self._retained:
            return
        phase_id = self._workspace_phases.get(command.workspace_handle)
        self._apply(retained_event(command, self._workflow_id or "", phase_id))

    @event_sourcing_handler("PhaseWorkspaceRetained")
    def on_phase_workspace_retained(self, event: PhaseWorkspaceRetainedEvent) -> None:
        """Apply PhaseWorkspaceRetainedEvent. A fact about the work, recorded once."""
        kept = (evt(event, "workspace_handle"), RetainedReason(evt(event, "reason")))
        self._retained = self._retained | {kept}
