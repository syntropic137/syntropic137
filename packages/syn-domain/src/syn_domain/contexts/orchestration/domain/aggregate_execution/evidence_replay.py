"""How each evidence-gate event changes replayed state (plan §A.4, PR 5b).

The aggregate's `@event_sourcing_handler`s delegate here, so the gate's whole
replay lives beside its rules (`evidence_gate`) and decisions
(`evidence_steps`) rather than in the aggregate. Each function only folds an
event that was already decided; none of them decides anything.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    PatchRemoval,
    StepOutcome,
    StepRef,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_gate import (
    EvidenceAttempt,
    EvidenceGate,
    SettledStep,
    read_datetime,
    read_plan_steps,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.replay import evt

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_gate import (
        EvidenceGateRecord,
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


def requested(gates: EvidenceGateRecord, event: EvidenceRequestedEvent) -> tuple[str, ...]:
    """Record the gate and its plan; returns the held skips (they are decided, §A.3)."""
    skipped = tuple(evt(event, "skipped_phase_ids") or [])
    gates.request(
        EvidenceGate(
            gate_id=evt(event, "gate_id"),
            after_phase_id=evt(event, "after_phase_id"),
            next_phase_id=evt(event, "next_phase_id"),
            next_phase_order=evt(event, "next_phase_order"),
            skipped_phase_ids=skipped,
            plan=read_plan_steps(evt(event, "steps")),
        )
    )
    return skipped


def attempt_started(gates: EvidenceGateRecord, event: EvidenceAttemptStartedEvent) -> None:
    """This attempt is now the step's current one."""
    gate = gates.get(evt(event, "gate_id"))
    if gate is not None:
        gate.attempts[evt(event, "step")] = EvidenceAttempt(
            attempt=evt(event, "attempt"),
            dispatch_id=evt(event, "dispatch_id"),
            started_at=read_datetime(evt(event, "started_at")),
            not_after=read_datetime(evt(event, "not_after")),
        )


def run_adopted(gates: EvidenceGateRecord, event: EvidenceRunAdoptedEvent) -> None:
    gate = gates.get(evt(event, "gate_id"))
    attempt = gate.attempts.get(evt(event, "step")) if gate is not None else None
    if gate is not None and attempt is not None:
        gate.attempts[evt(event, "step")] = replace(
            attempt, run_id=evt(event, "run_id"), run_url=evt(event, "run_url")
        )


def patches_removed(gates: EvidenceGateRecord, event: MutationPatchesRemovedEvent) -> None:
    """S' is where later steps run."""
    gate = gates.get(evt(event, "gate_id"))
    if gate is not None:
        gate.removed = PatchRemoval(
            before_sha=evt(event, "before_sha"),
            after_sha=evt(event, "after_sha"),
            author=evt(event, "author"),
        )


def step_settled(gates: EvidenceGateRecord, event: EvidenceStepSettledEvent) -> None:
    gate = gates.get(evt(event, "gate_id"))
    if gate is not None:
        gate.settled[evt(event, "step")] = settled_step(event)


def settled_step(event: EvidenceStepSettledEvent) -> SettledStep:
    """The settlement an `EvidenceStepSettled` records, live or replayed."""
    reused = evt(event, "reused_from")
    return SettledStep(
        index=evt(event, "step"),
        outcome=StepOutcome(evt(event, "outcome")),
        reason=evt(event, "reason"),
        run_url=evt(event, "run_url"),
        head_sha_evidenced=evt(event, "head_sha_evidenced"),
        reused_from=None if reused is None else StepRef.model_validate(reused),
    )
