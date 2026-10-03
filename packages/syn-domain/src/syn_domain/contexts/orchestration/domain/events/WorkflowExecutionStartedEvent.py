"""WorkflowExecutionStarted event - emitted when workflow execution begins."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic
from typing import Any

from event_sourcing import DomainEvent, event
from pydantic import SerializerFunctionWrapHandler, model_serializer, model_validator

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    INHERITED_PHASE_OWNERS,
    AbandonedBranch,
    ContinuedBranch,
    ExecutablePhase,
    ResumeOrigin,
    SourceCommit,
    owners_to_carry,
    started_payload_for_replay,
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


#: Fields a release before #1513 does not know: omitted when None.
_WRITTEN_ONLY_WHEN_SET = frozenset({"continued_branches", "abandoned_branches"})


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
    #: resume runs what its parent WOULD have run rather than what the template
    #: says today. None on events written before the field existed, and a
    #: parent with none cannot be resumed.
    pinned_phases: list[ExecutablePhase] | None = None

    #: The commit each repository was at when this execution started (#1457).
    #: A resume copies its parent's, so the two record the same code.
    source_commits: list[SourceCommit] | None = None

    #: Set only on a resume: the parent, what it inherited and where it resumes
    #: (ADR-014 s7). The child's own record of "what was this a resume of".
    resumed_from: ResumeOrigin | None = None

    #: Set only on a resume (#1513): the branches its resumed phase continues -
    #: pushed by the parent's failing attempt at that phase and confirmed still
    #: where it left them - each with the PR open from it. Top-level rather than
    #: inside `resumed_from`, whose model forbids extra keys, so a release that
    #: predates the field still reads the event. None before the field existed.
    continued_branches: list[ContinuedBranch] | None = None

    #: Set only on a resume (#1513): branches it could have continued and
    #: started fresh instead, each with why - the recorded warning.
    abandoned_branches: list[AbandonedBranch] | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalise_stored_payload(cls, data: object) -> object:
        """Drop removed pinned-phase keys and restore carried owners (#1462)."""
        return started_payload_for_replay(data)

    @model_serializer(mode="wrap")
    def _carry_inherited_owners(self, handler: SerializerFunctionWrapHandler) -> object:
        """Carry phase owners beside `resumed_from`, never inside it.

        See `INHERITED_PHASE_OWNERS`: an older reader can replay this event
        without them, and could not replay it with them nested. Only phases the
        parent did not run itself are written, so neither a fresh start nor a
        first resume writes the key at all.

        The #1513 branch fields are likewise written only when set, so a run
        that continues nothing reads exactly as a pre-#1513 release wrote it.
        """
        payload = {
            k: v
            for k, v in handler(self).items()
            if not (k in _WRITTEN_ONLY_WHEN_SET and v is None)
        }
        origin = self.resumed_from
        owners = (
            {}
            if origin is None
            else owners_to_carry(origin.inherited_phases, origin.parent_execution_id)
        )
        return {**payload, INHERITED_PHASE_OWNERS: owners} if owners else payload
