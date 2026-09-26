"""The rules that decide whether a terminal execution may be forked.

Resume is a FORK, not a mutation of the run that failed (ADR-014 s7). The
parent decides, and these are the rules it decides by. They live here rather
than inside `WorkflowExecutionAggregate.fork_execution` for two reasons: the
handler was the most branch-dense one in the aggregate, and every rule below is
a pure function of the parent's replayed state, so it is testable without
building an aggregate at all.

Nothing here mutates anything or emits an event. The caller raises.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    InheritedPhase,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        ForkExecutionCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        PhaseDefinition,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionForkedEvent import (
        ExecutionForkedEvent,
    )

#: Terminal states a fork may be taken from on the request alone (ADR-014 s7).
#:
#: FAILED and INTERRUPTED ended without anyone deciding the work should stop,
#: so running the rest of it again is what the operator wanted all along.
#: CANCELLED is deliberately absent: a cancel IS that decision - it may have
#: been issued because the run targeted the wrong repository or its task held
#: a secret - so it is forkable only on `override_cancellation`, never merely
#: because it is terminal. COMPLETED has nothing left to run; RUNNING and
#: PAUSED are still live, and forking them would put two runs on one piece of
#: work; an execution that never started has nothing to inherit.
FORKABLE_STATUSES: Final[frozenset[ExecutionStatus]] = frozenset(
    {ExecutionStatus.FAILED, ExecutionStatus.INTERRUPTED}
)


def completed_prefix(
    phase_definitions: Sequence[PhaseDefinition],
    completed_phase_ids: frozenset[str] | set[str],
    phase_artifact_ids: Mapping[str, list[str]],
) -> tuple[list[InheritedPhase], str | None]:
    """The phases a fork inherits, and the phase it resumes at.

    The CONTIGUOUS prefix, in phase order, stopping at the first phase that did
    not complete. A phase completed AFTER that gap is not inherited: its output
    was built on a predecessor the fork is about to produce afresh, so handing
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
    """
    inherited: list[InheritedPhase] = []
    for phase in phase_definitions:
        if phase.phase_id not in completed_phase_ids:
            return inherited, phase.phase_id
        inherited.append(
            InheritedPhase(
                phase_id=phase.phase_id,
                artifact_ids=list(phase_artifact_ids.get(phase.phase_id, [])),
            )
        )
    return inherited, None


def refuse_fork(
    *,
    execution_id: str | None,
    status: ExecutionStatus,
    forked: bool,
    fork_execution_id: str | None,
    requested_fork_id: str,
    override_cancellation: bool,
) -> str | None:
    """Why this execution may not be forked, or None if it may.

    Returns the refusal MESSAGE rather than raising, so the whole admission
    decision is one expression the caller turns into a `ValueError`.

    `forked` carries the at-most-once rule, NOT `fork_execution_id`. Under
    ADR-023 the store falls back to `GenericDomainEvent` when a stored event
    fails typed validation, and a field read off such an event comes back None -
    so a rule keyed on the child's id would fail OPEN on exactly the parent that
    has already been forked. The id is only used to name it in the message.
    """
    if execution_id is None:
        return "Cannot fork an execution that has not been started"
    if status is ExecutionStatus.CANCELLED:
        if not override_cancellation:
            return (
                f"Cannot fork execution {execution_id}: it was cancelled, and "
                "forking a cancelled execution needs an explicit override"
            )
    elif status not in FORKABLE_STATUSES:
        return f"Cannot fork execution in status {status}"
    if forked:
        named = fork_execution_id or "an execution this stream does not name"
        return f"Execution {execution_id} has already been forked as {named}"
    if not requested_fork_id or requested_fork_id == execution_id:
        return f"A fork needs an execution id of its own, got {requested_fork_id!r}"
    return None


def refuse_resume_point(
    *,
    execution_id: str,
    resume_phase_id: str | None,
    may_repeat_effects: bool,
    acknowledge_external_effects: bool,
) -> str | None:
    """Why the fork's resume point is not acceptable, or None if it is.

    Separate from `refuse_fork` because it needs the prefix computed first, and
    computing the prefix is only worthwhile once the parent is forkable at all.
    """
    if resume_phase_id is None:
        return f"Cannot fork execution {execution_id}: it has no unfinished phase to resume at"
    if may_repeat_effects and not acknowledge_external_effects:
        return (
            f"Cannot fork execution {execution_id}: phase {resume_phase_id} started "
            "and may have pushed or published something re-running it would "
            "repeat; the fork must acknowledge external effects"
        )
    return None


def admit_fork(
    *,
    execution_id: str | None,
    workflow_id: str,
    status: ExecutionStatus,
    forked: bool,
    fork_execution_id: str | None,
    phase_definitions: Sequence[PhaseDefinition],
    completed_phase_ids: frozenset[str] | set[str],
    phase_artifact_ids: Mapping[str, list[str]],
    started_phase_ids: Mapping[str, int] | frozenset[str] | set[str],
    command: ForkExecutionCommand,
) -> ExecutionForkedEvent:
    """The whole fork decision: the event to record, or `ValueError`.

    Every rule above applied in order, so the aggregate's handler is the
    dispatch and this is the decision. The ORDER matters: the prefix is only
    computed once the parent is forkable at all, and the resume point is judged
    only once there is a prefix to judge it against.
    """
    from syn_domain.contexts.orchestration.domain.events.ExecutionForkedEvent import (
        ExecutionForkedEvent,
    )

    refusal = refuse_fork(
        execution_id=execution_id,
        status=status,
        forked=forked,
        fork_execution_id=fork_execution_id,
        requested_fork_id=command.fork_execution_id,
        override_cancellation=command.override_cancellation,
    )
    if refusal is not None:
        raise ValueError(refusal)

    inherited, resume_phase_id = completed_prefix(
        phase_definitions, completed_phase_ids, phase_artifact_ids
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
        raise ValueError(refusal)

    return ExecutionForkedEvent(
        workflow_id=workflow_id,
        execution_id=command.aggregate_id,
        fork_execution_id=command.fork_execution_id,
        inherited_phases=inherited,
        resume_phase_id=resume_phase_id or "",
        forked_at=datetime.now(UTC),
        cancellation_overridden=status is ExecutionStatus.CANCELLED,
        external_effects_acknowledged=may_repeat_effects,
    )
