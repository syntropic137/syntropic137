"""WorkflowExecutionStarted event - emitted when workflow execution begins."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic
from typing import Any

from event_sourcing import DomainEvent, event

# Runtime import needed for the Pydantic field type (noqa: TC001)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (  # noqa: TC001
    ResumePoint,
)


@event("WorkflowExecutionStarted", "v1")
class WorkflowExecutionStartedEvent(DomainEvent):
    """Event emitted when workflow execution starts.

    Marks the beginning of the execution lifecycle.

    The expected_completion_at field is used for stale execution detection.
    If an execution is still "running" past this time, it may be stuck.
    """

    workflow_id: str
    execution_id: str
    workflow_name: str
    started_at: datetime
    total_phases: int
    inputs: dict[str, Any]

    # Expected completion time (for stale detection)
    # Calculated as: started_at + sum of all phase timeouts + buffer
    expected_completion_at: datetime | None = None

    # Phase definitions for aggregate-level sequencing (ISS-196)
    # Optional for backward compatibility — when absent, aggregate does not sequence.
    phase_definitions: list[dict[str, Any]] | None = None

    # Set when this execution is a retry of a failed one (#1335): the phase it
    # starts at, and the earlier phases whose outputs it inherits rather than
    # re-running. None is a first attempt, which is every event written before
    # this field existed.
    #
    # ON THE STARTED EVENT, not held by whoever launched the retry, because
    # every consumer of it is a different process or a later one: the to-do
    # projection reads it to put the FIRST work item on the resumed phase
    # instead of phase one, and the aggregate reads it on every rebuild to
    # know which phases count as done and which executions hold their
    # artifacts. A retry whose resume point lived only in the launching call
    # would restart as a fresh run at phase one after any restart.
    resumed_from: ResumePoint | None = None
