"""The guard must hold on the path the STORE actually uses (#1471 review).

`legacy_event_shapes` was tested by calling it directly, which proved only
that the function works - not that anything reaches it. It does not: the
discriminator ran inside Pydantic validation, and `grpc_client` catches every
validation error and falls back to `GenericDomainEvent` with the event type
preserved. So a refused payload came back as a generic event, routed on its
type, and was applied anyway.

These tests build the envelope the store builds, and drive the two consumers
that act on it: the aggregate (which spends the parent's one resume) and the
process manager (which puts a start on the to-do list).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata, GenericDomainEvent

from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)

pytestmark = pytest.mark.unit

PARENT = "exec-parent-1"


def _generic(event_type: str, **payload: object) -> EventEnvelope[DomainEvent]:
    """An envelope exactly as `grpc_client` builds one when typed validation fails."""
    return EventEnvelope(
        event=GenericDomainEvent(**payload, event_type=event_type),
        metadata=EventMetadata(
            aggregate_id=PARENT,
            aggregate_type="WorkflowExecution",
            event_type=event_type,
            version=1,
            aggregate_nonce=1,
            global_nonce=1,
        ),
    )


def _unpause_payload():
    """The pre-rename `ExecutionResumed`: un-pausing, not resuming."""
    return {
        "workflow_id": "wf-1",
        "execution_id": PARENT,
        "phase_id": "plan",
        "resumed_at": datetime(2026, 9, 1, tzinfo=UTC).isoformat(),
    }


def _forked_payload():
    """The pre-rename `ExecutionForked`: a real resume under its old name."""
    return {
        "workflow_id": "wf-1",
        "execution_id": PARENT,
        "fork_execution_id": "exec-child-1",
        "inherited_phases": [],
        "resume_phase_id": "implement",
        "forked_at": datetime(2026, 9, 26, tzinfo=UTC).isoformat(),
    }


class TestALegacyUnpauseDoesNotSpendTheResume:
    """The damage this prevents is unrecoverable.

    An execution may be resumed ONCE. Applying an un-pause as a resume marks
    the parent resumed, pointing at no child, and a later genuine request is
    refused as "already resumed". Nothing can undo that.
    """

    def test_it_names_no_resume(self) -> None:
        aggregate = WorkflowExecutionAggregate()

        aggregate.rehydrate([_generic("ExecutionResumed", **_unpause_payload())])

        assert aggregate.resume_execution_id is None

    def test_the_resume_is_still_unspent(self) -> None:
        """The property an operator feels, read the way the domain reads it.

        The MESSAGE is asserted, not merely that it raises. Both the fixed and
        the broken build raise here - the broken one because the resume it
        thinks it admitted has no id ("cannot be named"), the fixed one because
        no resume was admitted at all. Only the wording tells them apart, so a
        bare `pytest.raises` would pass on the bug.
        """
        aggregate = WorkflowExecutionAggregate()

        aggregate.rehydrate([_generic("ExecutionResumed", **_unpause_payload())])

        with pytest.raises(ValueError, match="has not admitted a resume"):
            aggregate.resume_start_command()


class TestAPreRenameForkIsStillAResume:
    """Dropping it silently is the opposite failure, and just as bad.

    A parent whose resume was recorded as `ExecutionForked` would look
    unresumed, so a second resume would be admitted - two runs on one piece of
    work, which the one-resume rule exists to prevent.
    """

    def test_it_names_the_child_it_admitted(self) -> None:
        aggregate = WorkflowExecutionAggregate()

        aggregate.rehydrate([_generic("ExecutionForked", **_forked_payload())])

        assert aggregate.resume_execution_id == "exec-child-1"

    def test_the_child_start_it_owes_can_be_built(self) -> None:
        """Naming the child is not enough; the start must be buildable.

        `forked_at` -> `resumed_at` and the rest of the upcast only matter if
        what comes out the far side is a usable command.
        """
        aggregate = WorkflowExecutionAggregate()

        aggregate.rehydrate([_generic("ExecutionForked", **_forked_payload())])

        command = aggregate.resume_start_command()

        assert command.aggregate_id == "exec-child-1"
        assert command.resumed_from.parent_execution_id == PARENT
        assert command.resumed_from.resume_phase_id == "implement"


class TestAnAmbiguousPayloadIsRefusedNotGuessed:
    def test_both_markers_present_is_not_silently_accepted(self) -> None:
        """Codex #1471: a payload carrying BOTH markers passed the old check.

        It cannot be both an un-pause and a resume, so it is refused loudly
        rather than resolved by whichever branch happens to be tested first.
        """
        both = {**_unpause_payload(), "resume_execution_id": "exec-child-1"}
        aggregate = WorkflowExecutionAggregate()

        with pytest.raises(Exception, match=r"ambiguous|cannot be determined|both"):
            aggregate.rehydrate([_generic("ExecutionResumed", **both)])
