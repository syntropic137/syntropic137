"""WorkflowExecutionStarted event - emitted when workflow execution begins."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic
from typing import Any

from event_sourcing import DomainEvent, event

from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    ForkOrigin,  # noqa: TC001 - needed at runtime for Pydantic
    SourceCommit,  # noqa: TC001 - needed at runtime for Pydantic
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,  # noqa: TC001 - needed at runtime for Pydantic
)

#: Where the dispatched task lives inside ``inputs``.
#:
#: A run is dispatched with a task and a set of inputs, and the task is folded
#: into the inputs under this key before the event is written -- it is what
#: ``$ARGUMENTS`` resolves to in a phase prompt. Named here, beside the event
#: whose payload carries it, because the side that writes it and the side that
#: reads it back out have to agree; a second literal spelled somewhere else is
#: how they stop agreeing.
TASK_INPUT_KEY = "task"


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

    #: The full runnable config of every phase, as this execution runs it
    #: (#1454): provider, model resolved at start, prompt, sandbox, tools,
    #: plugins, skills. The workflow template is mutable and this is not, so a
    #: fork runs what its parent WOULD have run rather than what the template
    #: says today. None on events written before the field existed, and a
    #: parent with none cannot be forked.
    pinned_phases: list[ExecutablePhase] | None = None

    #: The commit each repository was at when this execution started (#1457).
    #: A fork copies its parent's, so the two record the same code.
    source_commits: list[SourceCommit] | None = None

    #: Set only on a fork: the parent, what it inherited and where it resumes
    #: (ADR-014 s7). The child's own record of "what was this a fork of".
    forked_from: ForkOrigin | None = None
