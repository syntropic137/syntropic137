"""The aggregate's evidence-gate decisions, as events (plan §A.3-§A.5, PR 5b).

`evidence_gate` holds the rules; this turns a command plus replayed state into
the events the aggregate applies, or refuses it. Kept beside the aggregate, not
in it, for the same reason as `review_rounds`: each decision is testable from
the record alone. Every function here raises `ValueError` for a command the
gate's state forbids - no attempt for a settled step, no adoption for an
attempt that is not current, no settle twice or out of order, and no settle
that disagrees with an outcome the aggregate already decided.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    EvidenceKind,
    EvidenceStepKind,
    StepOutcome,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_gate import (
    MAX_ATTEMPTS,
    EvidenceGate,
    GateInputs,
    gate_opens,
    plan_steps,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ReviewVerdict,
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

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        RecordEvidenceRunAdoptedCommand,
        RecordMutationPatchesRemovedCommand,
        SettleEvidenceStepCommand,
        StartEvidenceAttemptCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_gate import (
        EvidenceGateRecord,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_record import (
        EvidenceRecord,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.review_rounds import (
        NextPhase,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        EvidenceGatePolicy,
        EvidencePlanStep,
        ObservedHead,
        PhaseDefinition,
    )


def request_if_needed(
    *,
    policy: EvidenceGatePolicy | None,
    decided: NextPhase | None,
    phase_id: str,
    definitions: Sequence[PhaseDefinition],
    verdict: ReviewVerdict | None,
    evidence: EvidenceRecord,
    gates: EvidenceGateRecord,
    observed: tuple[ObservedHead, ...],
    workflow_id: str,
    execution_id: str,
) -> EvidenceRequestedEvent | None:
    """`EvidenceRequested` to emit INSTEAD of `NextPhaseReady`, or None (§A.3).

    None whenever ``policy`` is None: the gate is off by default.
    """
    if policy is None or decided is None:
        return None
    inputs = GateInputs(
        declared=evidence.declared(phase_id),
        observed=observed,
        repositories=frozenset(policy.repositories),
        next_is_final=bool(definitions) and decided.phase.phase_id == definitions[-1].phase_id,
        certified=verdict is ReviewVerdict.CERTIFIED,
        passed=gates.passed(),
        earlier_mutation_tests=_earlier_mutation_tests(definitions, phase_id, evidence),
    )
    if not gate_opens(enabled=True, has_next_phase=True, inputs=inputs):
        return None
    return EvidenceRequestedEvent(
        workflow_id=workflow_id,
        execution_id=execution_id,
        gate_id=f"gate-{uuid.uuid4().hex[:12]}",
        after_phase_id=phase_id,
        next_phase_id=decided.phase.phase_id,
        next_phase_order=decided.phase.order,
        skipped_phase_ids=[p.phase_id for p in decided.skipped],
        steps=list(plan_steps(inputs)),
        requested_at=datetime.now(UTC),
    )


def start_attempt(
    gates: EvidenceGateRecord, command: StartEvidenceAttemptCommand
) -> EvidenceAttemptStartedEvent:
    gate, step = _current(gates, command.gate_id, command.step)
    if step.kind is EvidenceStepKind.REMOVE_MUTATION_PATCHES or gate.predetermined(step):
        msg = f"step {step.index} of {gate.gate_id} dispatches nothing; settle it instead"
        raise ValueError(msg)
    previous = gate.attempts.get(step.index)
    attempt = 1 if previous is None else previous.attempt + 1
    if attempt > MAX_ATTEMPTS:
        msg = f"step {step.index} of {gate.gate_id} has used its {MAX_ATTEMPTS} attempts"
        raise ValueError(msg)
    return EvidenceAttemptStartedEvent(
        execution_id=command.aggregate_id,
        gate_id=gate.gate_id,
        step=step.index,
        attempt=attempt,
        dispatch_id=command.dispatch_id,
        started_at=command.started_at,
        # Retries share the step's deadline (§A.5 4).
        not_after=command.not_after if previous is None else previous.not_after,
    )


def adopt_run(
    gates: EvidenceGateRecord, command: RecordEvidenceRunAdoptedCommand
) -> EvidenceRunAdoptedEvent:
    gate, step = _current(gates, command.gate_id, command.step)
    attempt = gate.attempts.get(step.index)
    if attempt is None or attempt.attempt != command.attempt:
        msg = f"attempt {command.attempt} is not the current attempt at step {step.index}"
        raise ValueError(msg)
    if attempt.run_id is not None:
        msg = f"attempt {command.attempt} at step {step.index} already adopted run {attempt.run_id}"
        raise ValueError(msg)
    return EvidenceRunAdoptedEvent(
        execution_id=command.aggregate_id,
        gate_id=gate.gate_id,
        step=step.index,
        attempt=attempt.attempt,
        run_id=command.run_id,
        run_url=command.run_url,
    )


def record_removal(
    gates: EvidenceGateRecord, command: RecordMutationPatchesRemovedCommand
) -> tuple[MutationPatchesRemovedEvent, EvidenceStepSettledEvent]:
    """The removal and the settle it implies, applied together (§A.5 5)."""
    gate, step = _current(gates, command.gate_id, command.step)
    if step.kind is not EvidenceStepKind.REMOVE_MUTATION_PATCHES:
        msg = f"step {step.index} of {gate.gate_id} is {step.kind.value}, not a removal"
        raise ValueError(msg)
    blocked = gate.predetermined(step)
    if blocked is not None:
        msg = f"removal at step {step.index} is not allowed: {blocked.reason}"
        raise ValueError(msg)
    if step.repository is None or step.branch is None or step.head_sha is None:
        msg = f"removal at step {step.index} has no planned head"
        raise ValueError(msg)
    if command.after_sha == step.head_sha:
        msg = "a patch removal must move the head"
        raise ValueError(msg)
    removed = MutationPatchesRemovedEvent(
        execution_id=command.aggregate_id,
        gate_id=gate.gate_id,
        step=step.index,
        repository=step.repository,
        branch=step.branch,
        before_sha=step.head_sha,
        after_sha=command.after_sha,
        author=command.author,
    )
    settled = EvidenceStepSettledEvent(
        execution_id=command.aggregate_id,
        gate_id=gate.gate_id,
        after_phase_id=gate.after_phase_id,
        step=step.index,
        next_step=_next_index(gate, step),
        outcome=StepOutcome.PASSED,
        head_sha_evidenced=command.after_sha,
    )
    return removed, settled


def settle(
    gates: EvidenceGateRecord, command: SettleEvidenceStepCommand
) -> EvidenceStepSettledEvent:
    gate, step = _current(gates, command.gate_id, command.step)
    decided = gate.predetermined(step)
    if decided is not None and (command.outcome, command.reason) != (
        decided.outcome,
        decided.reason,
    ):
        msg = (
            f"step {step.index} of {gate.gate_id} was decided as {decided.outcome.value} "
            f"({decided.reason}); it cannot settle {command.outcome.value}"
        )
        raise ValueError(msg)
    if (
        decided is None
        and step.kind is EvidenceStepKind.REMOVE_MUTATION_PATCHES
        and command.outcome is StepOutcome.PASSED
    ):
        msg = "a removal passes only by recording MutationPatchesRemoved"
        raise ValueError(msg)
    if command.outcome in (StepOutcome.VOID, StepOutcome.UNAVAILABLE) and not command.reason:
        msg = f"a {command.outcome.value} step must say why"
        raise ValueError(msg)
    return EvidenceStepSettledEvent(
        execution_id=command.aggregate_id,
        gate_id=gate.gate_id,
        after_phase_id=gate.after_phase_id,
        step=step.index,
        next_step=_next_index(gate, step),
        outcome=command.outcome,
        reason=command.reason,
        run_id=command.run_id,
        run_url=command.run_url,
        head_sha_evidenced=command.head_sha_evidenced,
        reused_from=decided.reused_from if decided is not None else command.reused_from,
        report_artifact_ids=command.report_artifact_ids,
        manifest_artifact_id=command.manifest_artifact_id,
    )


def _current(
    gates: EvidenceGateRecord, gate_id: str, index: int
) -> tuple[EvidenceGate, EvidencePlanStep]:
    gate = gates.get(gate_id)
    if gate is None:
        msg = f"no evidence gate {gate_id}"
        raise ValueError(msg)
    current = gate.current
    if current is None or current.index != index:
        msg = f"step {index} of {gate_id} is not its current step (settled, or out of order)"
        raise ValueError(msg)
    return gate, current


def _earlier_mutation_tests(
    definitions: Sequence[PhaseDefinition], phase_id: str, evidence: EvidenceRecord
) -> dict[str, tuple[str, ...]]:
    """Per repository, the latest mutation tests declared by a phase before ``phase_id``."""
    found: dict[str, tuple[str, ...]] = {}
    for definition in definitions:
        if definition.phase_id == phase_id:
            break
        for declared in evidence.declared(definition.phase_id):
            request = declared.request
            if request is not None and request.kind is EvidenceKind.MUTATION:
                found[request.repository] = request.tests
    return found


def _next_index(gate: EvidenceGate, step: EvidencePlanStep) -> int | None:
    """The step after ``step``, or None when it is the last. Steps settle in order."""
    following = step.index + 1
    return following if following < len(gate.plan) else None
