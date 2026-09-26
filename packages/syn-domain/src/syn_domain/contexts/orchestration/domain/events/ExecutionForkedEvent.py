"""ExecutionForked event - a terminal execution has admitted one fork."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    InheritedPhase,  # noqa: TC001 - needed at runtime for Pydantic
)


@event("ExecutionForked", "v1")
class ExecutionForkedEvent(DomainEvent):
    """A terminal execution admitted a fork, recorded on the PARENT's stream (ADR-014 s7).

    The parent's decision and nothing more. The parent stays terminal - this
    event changes none of its status - and the fork does not exist yet: its
    own stream, its to-do list and its start are a later step that reads this
    event. What is fixed here is everything that step must not decide for
    itself, because by then the parent's stream is the only witness to it.

    Written once per parent. "Already forked" is a fact about the parent, so
    the parent stream's optimistic concurrency is what makes two concurrent
    forks resolve to one.
    """

    workflow_id: str
    #: The PARENT - the stream this event is on.
    execution_id: str
    fork_execution_id: str

    #: The parent's contiguous prefix of completed phases, in phase order,
    #: each with the artifact ids the fork inherits. Stops at the first phase
    #: that did not complete, so a phase completed after a gap is NOT here:
    #: the fork re-runs the gap, and a later phase's output was built on a
    #: predecessor the fork will produce afresh.
    inherited_phases: list[InheritedPhase]

    #: The phase the fork begins at - the first one not inherited.
    resume_phase_id: str
    forked_at: datetime

    #: Set when the parent was CANCELLED and the request said, separately and
    #: explicitly, to fork it anyway. Recorded so that overriding a cancel is
    #: never indistinguishable from forking a failure.
    cancellation_overridden: bool = False

    #: Set when `resume_phase_id` had started in the parent without leaving
    #: evidence that it changed nothing outside the workspace, and the request
    #: acknowledged that re-running it may repeat what it did.
    external_effects_acknowledged: bool = False
