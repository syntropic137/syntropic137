"""ExecutionForked event - a terminal execution has admitted one fork."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event
from pydantic import SerializerFunctionWrapHandler, model_serializer, model_validator

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    INHERITED_PHASE_OWNERS,
    InheritedPhase,
    owners_to_carry,
    payload_with_owners_restored,
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

    @model_validator(mode="before")
    @classmethod
    def _restore_inherited_owners(cls, data: object) -> object:
        """Put each phase's carried owner back where it is read from (#1462)."""
        return payload_with_owners_restored(data)

    @model_serializer(mode="wrap")
    def _carry_inherited_owners(self, handler: SerializerFunctionWrapHandler) -> object:
        """Carry phase owners beside the phases, never inside them.

        See `INHERITED_PHASE_OWNERS`: an older reader can replay this event
        without them, and could not replay it with them nested. The owner is
        this execution for every phase it ran, so only phases it inherited
        from further up are written.
        """
        payload = handler(self)
        owners = owners_to_carry(self.inherited_phases, self.execution_id)
        return {**payload, INHERITED_PHASE_OWNERS: owners} if owners else payload
