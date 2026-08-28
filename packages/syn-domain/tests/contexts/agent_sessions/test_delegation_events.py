"""The delegation edge, as three facts (#895).

The edge is recorded in two steps rather than one because the child's
harness-native id does not exist until the child starts, while the attempt id
must exist BEFORE launch or a child that dies immediately cannot be attributed
to anything.

Root is required rather than derived. The aggregate's existing fallback sets
root = parent when root is omitted, which is right at depth 1 and wrong at
depth 3: C's root becomes B when the true root is A. Requiring it here means a
malformed tree cannot be constructed in the first place.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_domain.contexts.agent_sessions.domain.events.DelegationBoundEvent import (
    DelegationBoundEvent,
)
from syn_domain.contexts.agent_sessions.domain.events.DelegationFinishedEvent import (
    DelegationFinishedEvent,
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
def test_finished_records_the_delegate_own_status() -> None:
    """The delegate's exit status, NOT the enclosing shell's. #894 is a phase
    reporting success because the shell exited zero while the delegation it
    declared never happened.
    """
    event = DelegationFinishedEvent(delegation_attempt_id=_ATTEMPT, exit_status=1)

    assert event.event_type == "DelegationFinished"
    assert event.exit_status == 1


@pytest.mark.unit
def test_events_are_immutable() -> None:
    """A recorded fact does not get edited after the fact."""
    event = DelegationBoundEvent(delegation_attempt_id=_ATTEMPT, harness_session_id="native-0001")

    with pytest.raises(ValidationError):
        event.harness_session_id = "someone-elses-session"
