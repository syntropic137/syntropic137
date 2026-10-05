"""The rules that decide whether a terminal execution may be resumed.

Resume is a RESUME, not a mutation of the run that failed (ADR-014 s7). The
parent decides, and these are the rules it decides by. They live here rather
than inside `WorkflowExecutionAggregate.resume_execution` for two reasons: the
handler was the most branch-dense one in the aggregate, and every rule below is
a pure function of the parent's replayed state, so it is testable without
building an aggregate at all.

Nothing here mutates anything or emits an event. The caller raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    InheritedPhase,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        ResumeExecutionCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        PhaseDefinition,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
        ExecutionResumedEvent,
    )

#: Terminal states a resume may be taken from on the request alone (ADR-014 s7).
#:
#: FAILED and INTERRUPTED ended without anyone deciding the work should stop,
#: so running the rest of it again is what the operator wanted all along.
#: CANCELLED is deliberately absent: a cancel IS that decision - it may have
#: been issued because the run targeted the wrong repository or its task held
#: a secret - so it is resumable only on `override_cancellation`, never merely
#: because it is terminal. COMPLETED is resumable only when it ended with
#: UNRESOLVED FINDINGS - its last review verdict `blocked` at the workflow's
#: repair bound (PC-63) - and then at the last round's fix, not at the first
#: unfinished phase (there is none); otherwise it has nothing left to run.
#: RUNNING is still live, and resuming it would put two runs on one piece of work; an
#: execution that never started has nothing to inherit.
RESUMABLE_STATUSES: Final[frozenset[ExecutionStatus]] = frozenset(
    {ExecutionStatus.FAILED, ExecutionStatus.INTERRUPTED}
)


def completed_prefix(
    phase_definitions: Sequence[PhaseDefinition],
    completed_phase_ids: frozenset[str] | set[str],
    phase_artifact_ids: Mapping[str, list[str]],
    *,
    execution_id: str,
    phase_owners: Mapping[str, str],
) -> tuple[list[InheritedPhase], str | None]:
    """The phases a resume inherits, and the phase it resumes at.

    The CONTIGUOUS prefix, in phase order, stopping at the first phase that did
    not complete. A phase completed AFTER that gap is not inherited: its output
    was built on a predecessor the resume is about to produce afresh, so handing
    it over would hand the child work resting on something that no longer
    holds.

    The resume phase is None when there is nothing left to run - every phase
    completed, or the execution recorded no phase definitions to walk.

    `phase_definitions` is trusted to be in phase order and to have one entry
    per phase. `WorkflowDefinition.from_yaml` is what makes that true: it
    rejects duplicate phase ids AND duplicate orders, so "phase order" is a
    total order by the time an execution can start. This function would be
    ambiguous without that, which is why the precondition is written down here
    rather than assumed.

    Every inherited phase names the execution that holds its artifacts (#1462):
    ``execution_id`` for a phase this run ran, or its owner from
    ``phase_owners`` for one this run itself inherited. Without that a resume of a
    resume asks its parent for artifacts only the grandparent ever stored.
    """
    inherited: list[InheritedPhase] = []
    for phase in phase_definitions:
        if phase.phase_id not in completed_phase_ids:
            return inherited, phase.phase_id
        inherited.append(
            InheritedPhase(
                phase_id=phase.phase_id,
                artifact_ids=list(phase_artifact_ids.get(phase.phase_id, [])),
                origin_execution_id=phase_owners.get(phase.phase_id, execution_id),
            )
        )
    return inherited, None


def refuse_resume(
    *,
    execution_id: str | None,
    status: ExecutionStatus,
    resumed: bool,
    resume_execution_id: str | None,
    requested_resume_id: str,
    override_cancellation: bool,
    repair_point: str | None = None,
) -> str | None:
    """Why this execution may not be resumed, or None if it may.

    ``repair_point`` is where a completed run with unresolved findings
    continues (`ReviewRecord.repair_point`); a completed run without one is
    refused.

    Returns the refusal MESSAGE rather than raising, so the whole admission
    decision is one expression the caller turns into a `ValueError`.

    `resumed` carries the at-most-once rule, NOT `resume_execution_id`. Under
    ADR-023 the store falls back to `GenericDomainEvent` when a stored event
    fails typed validation, and a field read off such an event comes back None -
    so a rule keyed on the child's id would fail OPEN on exactly the parent that
    has already been resumed. The id is only used to name it in the message.
    """
    if execution_id is None:
        return "Cannot resume an execution that has not been started"
    if status is ExecutionStatus.CANCELLED:
        if not override_cancellation:
            return (
                f"Cannot resume execution {execution_id}: it was cancelled, and "
                "resuming a cancelled execution needs an explicit override"
            )
    elif status is ExecutionStatus.COMPLETED:
        if repair_point is None:
            return f"Cannot resume execution in status {status}"
    elif status not in RESUMABLE_STATUSES:
        return f"Cannot resume execution in status {status}"
    if resumed:
        named = resume_execution_id or "an execution this stream does not name"
        return f"Execution {execution_id} has already been resumed as {named}"
    if not requested_resume_id or requested_resume_id == execution_id:
        return f"A resume needs an execution id of its own, got {requested_resume_id!r}"
    return None


def refuse_resume_point(
    *,
    execution_id: str,
    resume_phase_id: str | None,
    may_repeat_effects: bool,
    acknowledge_external_effects: bool,
) -> str | None:
    """Why the resume's resume point is not acceptable, or None if it is.

    Separate from `refuse_resume` because it needs the prefix computed first, and
    computing the prefix is only worthwhile once the parent is resumable at all.
    """
    if resume_phase_id is None:
        return f"Cannot resume execution {execution_id}: it has no unfinished phase to resume at"
    if may_repeat_effects and not acknowledge_external_effects:
        return (
            f"Cannot resume execution {execution_id}: phase {resume_phase_id} started "
            "and may have pushed or published something re-running it would "
            "repeat; the resume must acknowledge external effects"
        )
    return None


@dataclass(frozen=True)
class ResumeRefused:
    """The parent may not be resumed, and why."""

    reason: str


@dataclass(frozen=True)
class ResumeAdmitted:
    """The parent may be resumed, and the event that records it."""

    event: ExecutionResumedEvent


#: The whole outcome of asking to resume, as one value the caller matches on.
#:
#: Two types rather than a message plus an optional event, so "refused" and
#: "admitted" are not both representable at once and the caller cannot forget to
#: check. The caller RAISES - the decision is made here, the refusal is signalled
#: there, and the aggregate's handler keeps the precondition guard that every
#: command handler is required to have.
ResumeDecision = ResumeRefused | ResumeAdmitted


def decide_resume(
    *,
    execution_id: str | None,
    workflow_id: str,
    status: ExecutionStatus,
    resumed: bool,
    resume_execution_id: str | None,
    phase_definitions: Sequence[PhaseDefinition],
    completed_phase_ids: frozenset[str] | set[str],
    phase_artifact_ids: Mapping[str, list[str]],
    phase_owners: Mapping[str, str],
    started_phase_ids: Mapping[str, int] | frozenset[str] | set[str],
    command: ResumeExecutionCommand,
    repair_point: str | None = None,
) -> ResumeDecision:
    """Every rule above, applied in order.

    The ORDER matters: the prefix is only computed once the parent is resumable at
    all, and the resume point is judged only once there is a prefix to judge it
    against.

    A completed run with unresolved findings inherits only the phases before
    its ``repair_point``: the prefix stops there as if that phase had never
    completed, so the resume re-runs the last round and what follows it.
    """
    from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
        ExecutionResumedEvent,
    )

    refusal = refuse_resume(
        execution_id=execution_id,
        status=status,
        resumed=resumed,
        resume_execution_id=resume_execution_id,
        requested_resume_id=command.resume_execution_id,
        override_cancellation=command.override_cancellation,
        repair_point=repair_point,
    )
    if refusal is not None:
        return ResumeRefused(refusal)

    if status is ExecutionStatus.COMPLETED and repair_point is not None:
        ids = [p.phase_id for p in phase_definitions]
        completed_phase_ids = set(ids[: ids.index(repair_point)]) & set(completed_phase_ids)
    inherited, resume_phase_id = completed_prefix(
        phase_definitions,
        completed_phase_ids,
        phase_artifact_ids,
        execution_id=execution_id or "",
        phase_owners=phase_owners,
    )
    # Started means an agent may have acted. Nothing on this stream can show
    # that it did not: branch observations cover git refs only, and the evidence
    # the in-phase retry rests on (#1303) never reaches the event store. So any
    # started phase is re-run only on acknowledgement.
    may_repeat_effects = resume_phase_id in started_phase_ids
    refusal = refuse_resume_point(
        execution_id=execution_id or "",
        resume_phase_id=resume_phase_id,
        may_repeat_effects=may_repeat_effects,
        acknowledge_external_effects=command.acknowledge_external_effects,
    )
    if refusal is not None:
        return ResumeRefused(refusal)

    return ResumeAdmitted(
        ExecutionResumedEvent(
            workflow_id=workflow_id,
            execution_id=command.aggregate_id,
            resume_execution_id=command.resume_execution_id,
            inherited_phases=inherited,
            resume_phase_id=resume_phase_id or "",
            resumed_at=datetime.now(UTC),
            cancellation_overridden=status is ExecutionStatus.CANCELLED,
            external_effects_acknowledged=may_repeat_effects,
        )
    )
