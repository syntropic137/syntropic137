"""WorkflowFailed event - emitted when workflow execution fails."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event
from pydantic import Field

# Runtime import needed for the Pydantic field type (noqa: TC001)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    BranchObservation,
    FailureClassification,
    ReportedFailureReason,
)


@event("WorkflowFailed", "v1")
class WorkflowFailedEvent(DomainEvent):
    """Event emitted when workflow execution fails.

    Contains information about the failure and any partial progress.
    Cost is Lane 2 telemetry — see execution_cost projection.
    """

    workflow_id: str
    execution_id: str
    failed_at: datetime

    # Failure information
    failed_phase_id: str | None = None
    error_message: str
    error_type: str | None = None

    # WHAT KIND OF FAILURE THIS WAS (#1357), and the field every failure
    # number is computed from.
    #
    # `error_type` is the exception's CLASS NAME and answers a different
    # question badly: `PhaseReportedFailureError` is what a correct refusal
    # raises AND what an unreadable report raises, `RuntimeError` is what a
    # non-zero exit raises, and no tally can be built on either. This names
    # the distinction instead of leaving it to be re-derived from prose -
    # which is what it was, inside `error_message`, readable by a human and
    # by nothing else.
    #
    # DEFAULTS TO `UNCLASSIFIED`, WHICH IS THE REPLAY CONTRACT. Every event
    # written before this field existed carries no such key, and pydantic
    # gives those exactly this value: they load, they do not crash, and they
    # claim nothing about a run nobody classified. A live failure never
    # reaches this default - `fail_execution` always states it - so
    # `unclassified` in the store means "written before #1357" and means
    # nothing else.
    #
    # WHY NOT A NEW TERMINAL STATUS instead. `failed` is what happened to the
    # run and stays true for every value here: it did not deliver, and every
    # consumer that branches on terminality - the realtime sentinel, the
    # trigger guards, reconciliation - is right to treat all of them alike.
    # Splitting the status would change the meaning of `status = failed` for
    # every one of them to fix a question none of them asks, and would leave
    # historical rows claiming a status the new vocabulary has no word for. A
    # field beside it adds the answer without moving the question.
    failure_classification: FailureClassification = FailureClassification.UNCLASSIFIED

    # WHAT THE FAILING PHASE SAID CAUSED IT (#1372), which is a different kind
    # of fact from the field above and is stored apart from it for exactly
    # that reason (#1392).
    #
    # The classification is a MEASUREMENT: the platform observed how the run
    # ended and recorded it, and every failure number is computed from it.
    # This is a REPORT: one of a closed set of words an agent chose to write
    # about itself, corroborated by nothing but the fact that the process it
    # was written by exited cleanly. Both belong in the record - an operator
    # asking why a run failed wants the phase's own word first - and the one
    # thing that must never happen is a number being computed from this one.
    # Folding them into a single field is what made that possible, because a
    # sink reading it could no longer tell which kind of fact it held.
    #
    # `None` for every failure that named no reason: the whole store before
    # #1372, every failure with no agent anywhere near it, and every report
    # whose word this reader does not know.
    reported_failure_reason: ReportedFailureReason | None = None

    # How long failed_phase_id had been running when the failure was caught.
    # None when no phase was in flight (e.g. failure between phases).
    failed_phase_duration_seconds: float | None = None

    # Where the failed phase's branches stood when it died (#1200).
    #
    # THREE-VALUED, and the two empty answers are not the same incident. A list
    # holds readings taken from git: which branch, where its remote ref is now,
    # where that ref was when the phase started, and how many local commits no
    # remote holds. `[]` means the workspace was read and no branch differs
    # from how the phase found it; `null` means nothing could read it - no
    # workspace, or one that stopped answering - and asserts nothing either
    # way. A failure whose branch moved is recoverable by fetching it; one that
    # left nothing anywhere is not, and reporting the first as the second is
    # what left three executions' work unfindable in one day.
    #
    # NOTHING HERE SAYS WHO PUSHED. A ref that differs from its starting point
    # moved, and git does not record whose push moved it. `[]` is about
    # DIFFERENCE, not authorship: the branch a phase is on is normally already
    # on a remote, so recording every branch would give every failure a
    # location, including the phase that did nothing at all.
    observed_branches: list[BranchObservation] | None = None

    # What failed_phase_id's process exited with (#1319).
    #
    # THE DURABLE COPY, and for a failed phase the only one. The status is
    # known inside the execution and nowhere else afterwards: the platform
    # REMOVES the workspace container when it reaps, so a watcher polling
    # `docker inspect` later finds nothing, and the container's own PID 1 is
    # `sleep infinity` anyway - its status would report the stop signal, not
    # what the agent did. Meanwhile `AgentExecutionCompleted`, the only other
    # event carrying a status, is written exclusively on the zero-exit path,
    # so every value that actually distinguishes the outcomes reached no
    # durable record at all until this field.
    #
    # It is on the EVENT rather than the read model on purpose: a frozen
    # projection (#1318) is exactly the circumstance in which someone needs
    # this, and Lane 1 is what an outage does not touch.
    #
    # None means nothing observed a status, which is not 0. 0 is a process
    # that ran and exited cleanly; None covers a phase stranded by a restart,
    # a failure with no process behind it, and every event written before this
    # field existed. 124 (budget reached) and -11 (killed) call for different
    # responses again, which is why the number is kept rather than a flag.
    exit_code: int | None = None
    # What the failed phase had already written, kept out of its workspace
    # before it was torn down (#1321). Empty when it wrote nothing collectable.
    #
    # A phase failing and the work it produced being thrown away were one
    # decision until this field existed: the workspace goes when the run does,
    # so a phase that wrote a 1322-line deliverable and then botched its
    # `TASK_RESULT` was refused - correctly, #1256 - and its deliverable went
    # with the container. This is how a failed phase names what survived it.
    #
    # THE PHASE STILL FAILED. Nothing here is a completion: these ids arrive
    # on the failure event, not through `ArtifactsCollectedEvent`, because
    # collecting artifacts is what a phase that finished does and emitting it
    # would tell the stream the next phase is ready in a run being failed.
    failed_phase_artifact_ids: list[str] = Field(default_factory=list)

    # What the failed phase itself had spent when it died (#1262), zeros when
    # its agent never ran.
    #
    # FLAT AND NAMED FOR THE PHASE, like `failed_phase_duration_seconds` above
    # and for the same reason: these describe the ONE phase that died, not the
    # run, and the `total_*` fields further down are the run's partial totals
    # from the phases that completed. Collapsing the two sets is how a failed
    # phase's spend would be read as the execution's.
    #
    # WHY THEY ARE ON THE EVENT AT ALL. Until they were, the only record of
    # them was the prose `(tokens=190+545)` inside `error_message`. A phase
    # killed at its 1200s cap having spent 735 tokens had stalled and should
    # not be retried as-is; phases killed the same day after 171 messages and
    # 133 tool calls needed a bigger cap. Both reported exit 124, and no
    # queryable field separated them - so the stalled one was retried, and the
    # retry was the one unblocking a performance fix.
    #
    # Zero is a measurement here, not "not provided": a phase whose agent never
    # launched spent nothing. Read them against
    # `failed_phase_duration_seconds` and the phase's budget, which is what
    # tells "ran to the cap" from "died early and reported 124".
    failed_phase_input_tokens: int = 0
    failed_phase_output_tokens: int = 0
    failed_phase_cache_creation_tokens: int = 0
    failed_phase_cache_read_tokens: int = 0

    # Partial progress
    completed_phases: int
    total_phases: int

    # Partial metrics (from completed phases — cost lives in Lane 2)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
