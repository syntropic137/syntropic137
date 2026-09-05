"""WorkflowFailed event - emitted when workflow execution fails."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event

# Runtime import needed for the Pydantic field type (noqa: TC001)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (  # noqa: TC001
    PushedWork,
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

    # Where the failed phase's work already is, when it had pushed any (#1200).
    #
    # THREE-VALUED, and the two empty answers are not the same incident. A list
    # names branches a remote was confirmed to hold; `[]` means the workspace
    # was asked and nothing THIS PHASE PRODUCED had reached a remote, so its
    # work died with the container; `null` means nothing could ask - no
    # workspace, or one that stopped answering - and asserts nothing either
    # way. A failure that pushed complete work is recoverable by fetching a
    # named branch; a failure that pushed nothing is not, and reporting the
    # first as the second is what left three executions' work unfindable in one
    # day.
    #
    # `[]` is about the PHASE, not about the repository: the branch it was
    # working on is normally on a remote already, and counting that as an
    # answer made a phase that produced nothing report the commit it inherited
    # as its own.
    pushed_work: list[PushedWork] | None = None

    # Partial progress
    completed_phases: int
    total_phases: int

    # Partial metrics (from completed phases — cost lives in Lane 2)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
