"""The aggregate's evidence-gate command and event handlers (plan §A.3-§A.5, PR 5b).

A mixin of `WorkflowExecutionAggregate`, which is the only class that may use
it: the handlers are discovered on the aggregate's class like its own, and run
against its state. They are here so the gate's entry points sit with its rules
(`evidence_gate`), decisions (`evidence_steps`) and replay (`evidence_replay`)
instead of growing the aggregate. Every decision is still the aggregate's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import command_handler, event_sourcing_handler

from syn_domain.contexts.orchestration.domain.aggregate_execution import (
    evidence_replay,
    evidence_steps,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        ArtifactsCollectedCommand,
        RecordEvidenceRunAdoptedCommand,
        RecordMutationPatchesRemovedCommand,
        SettleEvidenceStepCommand,
        StartEvidenceAttemptCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_gate import (
        EvidenceGate,
        EvidenceGateRecord,
        SettledStep,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_record import (
        EvidenceRecord,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.review_rounds import (
        NextPhase,
        ReviewRecord,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        PhaseDefinition,
    )
    from syn_domain.contexts.orchestration.domain.events.EvidenceAttemptStartedEvent import (
        EvidenceAttemptStartedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.EvidenceRequestedEvent import (
        EvidenceRequestedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.EvidenceRunAdoptedEvent import (
        EvidenceRunAdoptedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.EvidenceStepSettledEvent import (
        EvidenceStepSettledEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.MutationPatchesRemovedEvent import (
        MutationPatchesRemovedEvent,
    )


class EvidenceGateHandlers:
    """Evidence-gate handlers over the aggregate's own replayed state."""

    if TYPE_CHECKING:
        # Owned and initialised by `WorkflowExecutionAggregate`.
        _gates: EvidenceGateRecord
        _evidence: EvidenceRecord
        _status: ExecutionStatus
        _phase_definitions: list[PhaseDefinition]
        _workflow_id: str | None
        _reviews: ReviewRecord

        def _apply(self, event: DomainEvent) -> None: ...

    def _hold_for_evidence(
        self, command: ArtifactsCollectedCommand, decided: NextPhase | None
    ) -> EvidenceRequestedEvent | None:
        """The gate to hold this transition with, or None: off unless the command carries a policy."""
        return evidence_steps.request_if_needed(
            policy=command.evidence_gate,
            decided=decided,
            phase_id=command.phase_id,
            definitions=self._phase_definitions,
            verdict=self._reviews.of(command.phase_id),
            evidence=self._evidence,
            gates=self._gates,
            observed=command.observed_heads,
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
        )

    def evidence_gate(self, gate_id: str) -> EvidenceGate | None:
        """An evidence gate as its events left it, for the handler that drives it."""
        return self._gates.get(gate_id)

    @command_handler("StartEvidenceAttemptCommand")
    def start_evidence_attempt(self, command: StartEvidenceAttemptCommand) -> None:
        """Record an attempt before its dispatch is posted (plan §A.5, B3)."""
        self._require_running("start an evidence attempt")
        self._apply(evidence_steps.start_attempt(self._gates, command))

    @command_handler("RecordEvidenceRunAdoptedCommand")
    def record_evidence_run_adopted(self, command: RecordEvidenceRunAdoptedCommand) -> None:
        """Record the forge run that answers a step's current attempt."""
        self._require_running("adopt an evidence run")
        self._apply(evidence_steps.adopt_run(self._gates, command))

    @command_handler("RecordMutationPatchesRemovedCommand")
    def record_mutation_patches_removed(self, command: RecordMutationPatchesRemovedCommand) -> None:
        """Record the platform's S -> S' commit and settle the removal step."""
        self._require_running("record a patch removal")
        removed, settled = evidence_steps.record_removal(self._gates, command)
        self._apply(removed)
        self._settle(settled)

    @command_handler("SettleEvidenceStepCommand")
    def settle_evidence_step(self, command: SettleEvidenceStepCommand) -> None:
        """Settle a gate's current step; the last settle releases the held phase."""
        self._require_running("settle an evidence step")
        self._settle(evidence_steps.settle(self._gates, command))

    def preview_evidence_settlement(self, command: SettleEvidenceStepCommand) -> SettledStep:
        """What ``command`` would record, by the same rule, without recording it (§A.6)."""
        return evidence_replay.settled_step(evidence_steps.settle(self._gates, command))

    def _require_running(self, action: str) -> None:
        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot {action} in status {self._status}"
            raise ValueError(msg)

    def _settle(self, settled: EvidenceStepSettledEvent) -> None:
        self._apply(settled)
        gate = self._gates.get(settled.gate_id)
        if gate is not None and gate.current is None:
            # The gate opens: the decision `EvidenceRequested` held, unchanged.
            self._apply(
                evidence_steps.released(gate, self._phase_definitions).event(
                    workflow_id=self._workflow_id or "",
                    execution_id=settled.execution_id,
                    completed_phase_id=gate.after_phase_id,
                )
            )

    @event_sourcing_handler("EvidenceRequested")
    def on_evidence_requested(self, event: EvidenceRequestedEvent) -> None:
        """Apply EvidenceRequested: the plan, and the held skips."""
        self._reviews.skipped.update(evidence_replay.requested(self._gates, event))

    @event_sourcing_handler("EvidenceAttemptStarted")
    def on_evidence_attempt_started(self, event: EvidenceAttemptStartedEvent) -> None:
        """Apply EvidenceAttemptStarted."""
        evidence_replay.attempt_started(self._gates, event)

    @event_sourcing_handler("EvidenceRunAdopted")
    def on_evidence_run_adopted(self, event: EvidenceRunAdoptedEvent) -> None:
        """Apply EvidenceRunAdopted."""
        evidence_replay.run_adopted(self._gates, event)

    @event_sourcing_handler("MutationPatchesRemoved")
    def on_mutation_patches_removed(self, event: MutationPatchesRemovedEvent) -> None:
        """Apply MutationPatchesRemoved."""
        evidence_replay.patches_removed(self._gates, event)

    @event_sourcing_handler("EvidenceStepSettled")
    def on_evidence_step_settled(self, event: EvidenceStepSettledEvent) -> None:
        """Apply EvidenceStepSettled."""
        evidence_replay.step_settled(self._gates, event)
