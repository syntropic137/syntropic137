"""What a phase reports when it ends, on either path.

Both halves live here because they are one concern seen twice: a phase that
finished and a phase that died both have to say how long they ran, what tokens
they burned, and what result the aggregate should record. Keeping them apart
is what let the failure half go uncomputed for so long - the success path had
the logic and nothing mirrored it.

A phase that fails never reaches `_handle_complete_phase`, so nothing on the
success path computes its duration and it reports 0.0 downstream. That is the
least plausible value available: a phase killed at its timeout ran for exactly
its budget, and 0.0 points a reader at provisioning rather than at the limit.

Extracted from `WorkflowExecutionProcessor`, which carries a `max-loc-file`
exception whose own history names `_handle_complete_phase` as one of the parts
that "genuinely belong elsewhere" (#934). Adding the failure half pushed the file
past that ceiling, so the success half came out with it rather than the ceiling
going up. Growing an excepted file is how an exception becomes permanent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionMetrics,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    describe_exception,
    describe_observed_branches,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

if TYPE_CHECKING:
    from datetime import datetime as DateTime

    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        CompletePhaseCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        BranchObservation,
        PhaseResult,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.errors import ObservedBranches


def failed_phase_elapsed_seconds(
    started_at: DateTime | None,
    *,
    now: DateTime | None = None,
) -> float | None:
    """Seconds a failed phase ran, or None when it never started.

    None and 0.0 mean different things and must stay distinguishable: None is
    "this phase never began, so there is no duration to report", while 0.0 would
    claim it began and took no time. Callers persist None as absent rather than
    coercing it.
    """
    if started_at is None:
        return None
    return ((now or datetime.now(UTC)) - started_at).total_seconds()


@dataclass(frozen=True)
class PhaseFailure:
    """Everything a dying execution records about the exception that killed it.

    Four sinks describe one failure - the phase's `PhaseResult`, the session's
    `session_error` observation, the `FailExecutionCommand` the aggregate
    stores, and the execution result handed back to the caller - and each used
    to spell the description itself as `str(error)`. That is "" for an
    exception raised with no arguments, so the four went blank together; #1196
    is what one of them looked like by the time it reached a user.

    Deciding it here is what stops a fifth sink deciding it again. A caller
    reads `reason` and cannot tell whether the exception named itself, which is
    the point: that is not a question a call site should be answering.

    `reason` and `error_type` describe the failure and are always present.
    `duration_seconds` and `result` describe the phase and are None together
    when the execution died before any phase started - there is no phase to
    report on, but there is still a failure to describe.

    `observed_branches` describes where the phase's repositories STAND, which
    is a different question from why it failed and is answered here so that the
    four sinks above cannot answer it four ways (#1200).
    """

    reason: str
    error_type: str
    duration_seconds: float | None
    result: PhaseResult | None
    observed_branches: tuple[BranchObservation, ...] | None = None
    """Branches read from git at failure time, `()` for "read, and none of them
    differs from how the phase found it", and None for "nothing could tell us".
    Straight from `ObservedBranches.recorded`, because deciding it twice is how
    the two would come to disagree."""


def failed_phase_outcome(
    error: BaseException,
    phase_id: str | None,
    started_at_by_phase: Mapping[str, DateTime],
    session_id_by_phase: Mapping[str, str],
    now: DateTime | None = None,
    observed: ObservedBranches | None = None,
) -> PhaseFailure:
    """What a failed run reports, derived from the exception that ended it.

    One call rather than three lookups and a description at the call site: the
    processor is at its file-size threshold, and the caller does not need to
    know that "how long did it run" and "what result does it produce" share a
    start timestamp, nor how an exception with nothing to say gets named.

    Takes the exception rather than a rendered message so that the rendering
    happens once. The processor used to do it and hand the string in, which put
    the decision back at the call site the moment a second call site appeared.

    `observed` is what git showed about where this workspace's branches stood,
    and it is APPENDED to the reason rather than replacing any of it: #1167
    saying the output contract was unmet stays exactly as loud, and where the
    branches stand follows it as a separate paragraph (#1200). None - nothing
    could be read - reads the same as it did before this existed.
    """
    started_at = started_at_by_phase.get(phase_id) if phase_id else None
    # ONE clock reading. The duration and the result's completed_at describe the
    # same instant, so reading twice made them disagree.
    ended_at = now or datetime.now(UTC)
    reason = describe_exception(error)
    if observed is not None:
        reason = f"{reason}\n\n{describe_observed_branches(observed)}"
    return PhaseFailure(
        reason=reason,
        error_type=type(error).__name__,
        observed_branches=observed.recorded if observed is not None else None,
        duration_seconds=failed_phase_elapsed_seconds(started_at, now=ended_at),
        result=failed_phase_result(
            phase_id,
            started_at,
            session_id_by_phase.get(phase_id or "", ""),
            reason,
            ended_at=ended_at,
        ),
    )


def failed_phase_result(
    phase_id: str | None,
    started_at: DateTime | None,
    session_id: str,
    error_message: str,
    ended_at: DateTime,
) -> PhaseResult | None:
    """The `PhaseResult` for a phase that failed, or None if it never started.

    A phase with no recorded start produces no result: inventing one would put a
    phase into the execution's results that never ran.
    """
    if phase_id is None or started_at is None:
        return None

    from syn_domain.contexts.orchestration.slices.execute_workflow.PhaseResultBuilder import (
        PhaseResultBuilder,
    )

    return PhaseResultBuilder.failure(
        phase_id=phase_id,
        started_at=started_at,
        session_id=session_id,
        error_message=error_message,
        completed_at=ended_at,
    )


@dataclass(frozen=True)
class CompletedPhase:
    """Everything a successfully completed phase reports.

    Returned as one value because the caller needs all of it and none of it
    independently: the result goes to the execution's result list, the command
    to the aggregate, and the tokens and duration to observability.
    """

    result: PhaseResult
    command: CompletePhaseCommand
    duration_seconds: float
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_tokens: int


def completed_phase(
    *,
    execution_id: str,
    workflow_id: str,
    phase_id: str,
    session_id: str | None,
    started_at: DateTime,
    artifact_ids: list[str],
    auth_tokens: tuple[int, int, int, int] | None,
    now: DateTime | None = None,
) -> CompletedPhase:
    """Build what a completed phase reports.

    `auth_tokens` are the authoritative counts from the CLI result event. They
    are absent for a partial or interrupted phase, and fall back to zeros rather
    than to an estimate: Lane 2 observability holds the definitive cost either
    way, and a guessed count here would be indistinguishable from a measured one.
    """
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        CompletePhaseCommand,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.PhaseResultBuilder import (
        PhaseResultBuilder,
    )

    inp, out, cache_creation, cache_read = auth_tokens or (0, 0, 0, 0)
    total = inp + out + cache_creation + cache_read

    # ONE clock reading, not one per use. The command's duration goes to the
    # aggregate and the event; the returned duration goes to observability. Two
    # `datetime.now()` calls would put two different numbers on one phase - the
    # exact class of split-truth this module exists to remove.
    ended_at = now or datetime.now(UTC)
    elapsed = (ended_at - started_at).total_seconds()

    # Health signals, not errors: a phase can legitimately produce neither, and
    # the dashboard shows them so a silently empty phase is visible as such.
    #
    # `no_artifacts` narrowed in meaning with #1167 and is no longer the only
    # thing standing between an empty phase and a green run. A phase that
    # DECLARED output and produced none now fails at collection and never
    # reaches here, so reaching here with no artifacts means the phase declared
    # none - legitimately empty. The warning stays because "legitimate" is not
    # the same as "expected" and an operator still wants to see it.
    warnings: list[str] = []
    if inp == 0 and out == 0:
        warnings.append("zero_tokens")
    if not artifact_ids:
        warnings.append("no_artifacts")

    return CompletedPhase(
        result=PhaseResultBuilder.success(
            phase_id=phase_id,
            started_at=started_at,
            session_id=session_id or "",
            artifact_ids=artifact_ids,
            input_tokens=inp,
            output_tokens=out,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            total_tokens=total,
            warnings=warnings,
        ),
        command=CompletePhaseCommand(
            execution_id=execution_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            session_id=session_id,
            artifact_id=artifact_ids[0] if artifact_ids else None,
            input_tokens=inp,
            output_tokens=out,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            total_tokens=total,
            duration_seconds=elapsed,
        ),
        duration_seconds=elapsed,
        input_tokens=inp,
        output_tokens=out,
        cache_creation_tokens=cache_creation,
        cache_read_tokens=cache_read,
        total_tokens=total,
    )


def failed_execution_result(
    *,
    workflow_id: str,
    execution_id: str,
    started_at: DateTime,
    phase_results: list[PhaseResult],
    artifact_ids: list[str],
    error_message: str,
    now: DateTime | None = None,
) -> WorkflowExecutionResult:
    """Assemble the result an execution returns when it dies.

    Pure assembly, so it lives beside `completed_phase` rather than in the
    processor: the two are the same statement made on opposite paths, and the
    failure half is the one that historically drifted.
    """
    return WorkflowExecutionResult(
        workflow_id=workflow_id,
        execution_id=execution_id,
        status="failed",
        started_at=started_at,
        completed_at=now or datetime.now(UTC),
        phase_results=phase_results,
        artifact_ids=artifact_ids,
        metrics=ExecutionMetrics.from_results(phase_results),
        error_message=error_message,
    )
