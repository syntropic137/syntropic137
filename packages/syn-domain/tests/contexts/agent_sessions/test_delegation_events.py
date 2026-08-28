"""The delegation edge, as three facts (#895).

The edge is recorded in two steps rather than one because the child's
harness-native id does not exist until the child starts, while the attempt id
must exist BEFORE launch or a child that dies immediately cannot be attributed
to anything.

Root is required ON THIS EVENT rather than derived. The aggregate's fallback
sets root = parent when root is omitted, which is right at depth 1 and wrong at
depth 3: C's root becomes B when the true root is A.

Be precise about what that buys, because the first draft of this file
overstated it: requiring root here closes ONE route. It does not make a
malformed tree impossible. A caller can still reach StartSessionCommand
directly with a parent and no root, and an explicitly WRONG root is accepted
by this event. Enforcing the shape is the invariant owner's job.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_domain.contexts.agent_sessions.domain.events.DelegationBoundEvent import (
    DelegationBoundEvent,
)
from syn_domain.contexts.agent_sessions.domain.events.DelegationFinishedEvent import (
    DelegationFinishedEvent,
    DelegationOutcome,
)
from syn_domain.contexts.agent_sessions.domain.events.DelegationStartedEvent import (
    DelegationStartedEvent,
)

_ATTEMPT = "01JB0000000000000000000ABC"


@pytest.mark.unit
def test_started_carries_the_whole_lineage() -> None:
    event = DelegationStartedEvent(
        delegation_attempt_id=_ATTEMPT,
        parent_session_id="B",
        root_session_id="A",
        child_session_id="C",
        provider="codex",
    )

    assert event.event_type == "DelegationStarted"
    assert (event.parent_session_id, event.root_session_id) == ("B", "A")


@pytest.mark.unit
def test_root_is_not_optional() -> None:
    """A depth-3 child whose root is allowed to default silently gets the wrong
    root, and nothing downstream can tell.
    """
    with pytest.raises(ValidationError):
        DelegationStartedEvent(
            delegation_attempt_id=_ATTEMPT,
            parent_session_id="B",
            child_session_id="C",
            provider="codex",
        )


@pytest.mark.unit
def test_root_may_equal_parent_at_depth_one() -> None:
    """Requiring root does not forbid the depth-1 case; it forbids OMITTING it."""
    event = DelegationStartedEvent(
        delegation_attempt_id=_ATTEMPT,
        parent_session_id="A",
        root_session_id="A",
        child_session_id="B",
        provider="claude",
    )

    assert event.root_session_id == event.parent_session_id


@pytest.mark.unit
@pytest.mark.parametrize("blank", ["", "   "])
def test_identifiers_may_not_be_blank(blank: str) -> None:
    """A blank id passes a None check while linking to nothing."""
    with pytest.raises(ValidationError):
        DelegationStartedEvent(
            delegation_attempt_id=blank,
            parent_session_id="B",
            root_session_id="A",
            child_session_id="C",
            provider="codex",
        )


@pytest.mark.unit
def test_bound_carries_only_the_join() -> None:
    """Binding is deliberately separate: the native id does not exist until the
    child starts, and the attempt id must exist before it.
    """
    event = DelegationBoundEvent(
        delegation_attempt_id=_ATTEMPT,
        harness_session_id="native-0001",
    )

    assert event.event_type == "DelegationBound"
    assert event.harness_session_id == "native-0001"


@pytest.mark.unit
def test_finished_records_the_delegate_own_outcome() -> None:
    """The delegate's outcome, NOT the enclosing shell's. #894 is a phase
    reporting success because the shell exited zero while the delegation it
    declared never happened.
    """
    event = DelegationFinishedEvent(
        delegation_attempt_id=_ATTEMPT,
        outcome=DelegationOutcome.FAILED,
        native_exit_code=1,
    )

    assert event.event_type == "DelegationFinished"
    assert event.outcome is DelegationOutcome.FAILED
    assert event.native_exit_code == 1


@pytest.mark.unit
def test_outcome_does_not_require_a_process() -> None:
    """Native same-harness fan-out has no process to exit, and cancellation and
    timeout have no natural integer either. A bare exit code would have forced
    every non-shell route to invent one.
    """
    event = DelegationFinishedEvent(
        delegation_attempt_id=_ATTEMPT, outcome=DelegationOutcome.CANCELLED
    )

    assert event.native_exit_code is None


@pytest.mark.unit
def test_an_identifier_is_stored_verbatim() -> None:
    """Opaque harness ids must match what the harness emitted, EXACTLY.

    An earlier draft stripped whitespace. That would silently rewrite the join
    key and make the binding it exists to protect unjoinable, so blankness is
    rejected without the value being normalised.
    """
    padded = " native-id-with-padding "
    event = DelegationBoundEvent(delegation_attempt_id=_ATTEMPT, harness_session_id=padded)

    assert event.harness_session_id == padded


@pytest.mark.unit
def test_events_are_immutable() -> None:
    """A recorded fact does not get edited after the fact."""
    event = DelegationBoundEvent(delegation_attempt_id=_ATTEMPT, harness_session_id="native-0001")

    with pytest.raises(ValidationError):
        event.harness_session_id = "someone-elses-session"
