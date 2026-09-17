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
    failed_phase_artifact_ids: list[str] = []

    # Partial progress
    completed_phases: int
    total_phases: int

    # Partial metrics (from completed phases — cost lives in Lane 2)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
