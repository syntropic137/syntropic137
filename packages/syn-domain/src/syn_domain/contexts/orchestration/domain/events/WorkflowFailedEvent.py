"""WorkflowFailed event - emitted when workflow execution fails."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event

# Runtime import needed for the Pydantic field type (noqa: TC001)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (  # noqa: TC001
    BranchObservation,
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

    # Partial progress
    completed_phases: int
    total_phases: int

    # Partial metrics (from completed phases — cost lives in Lane 2)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
