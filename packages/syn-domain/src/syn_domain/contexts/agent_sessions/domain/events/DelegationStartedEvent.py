"""DelegationStarted event - a delegated child run was launched (issue #895).

Pure data, per the VSA rule that events import nothing: the blank-identifier
check is inline rather than shared, and is duplicated across the delegation
events deliberately.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("DelegationStarted", "v1")
class DelegationStartedEvent(DomainEvent):
    """A parent session launched a delegated child.

    WHAT THIS MODEL GUARANTEES: the fields below are present and non-blank.
    Nothing more. The properties the protocol relies on are stated on each
    field as REQUIREMENTS ON THE PRODUCER, because a Pydantic model cannot
    enforce them and describing them as guarantees would mislead whoever
    implements against this.
    """

    delegation_attempt_id: str
    """PRODUCER REQUIREMENT: minted by the edge adapter before it launches the
    child, and unique platform-wide. Not enforced here; nothing in this model
    can observe other attempts.

    The adapter that mints it also reads that child's stream, so one instance
    owns both the id and the stream it belongs to. That is what makes
    concurrent children of one provider safe without correlating by time.
    """

    parent_session_id: str
    """The platform session that delegated."""

    root_session_id: str
    """The top of the delegation tree.

    Required on THIS EVENT so it cannot be omitted here. That is a narrower
    claim than it may look: the session aggregate still has a root = parent
    fallback for omitted roots, and a caller can still reach
    StartSessionCommand directly with a parent and no root, or pass a wrong
    root explicitly. This event closes one route, not the shape.
    """

    child_session_id: str
    """The platform session minted for the child."""

    provider: str
    """Which harness the child runs, for selecting the right adapter later.
    A plain string rather than an enum so a new provider needs no v2."""

    @field_validator(
        "delegation_attempt_id",
        "parent_session_id",
        "root_session_id",
        "child_session_id",
        "provider",
    )
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        """Reject blank ids WITHOUT normalising the value.

        A blank id is worse than a missing one: it satisfies every None check
        downstream while linking to nothing, so the orphan looks like a
        successful binding.

        Deliberately does not strip. These are opaque identifiers that must
        later match a harness-provided string exactly, and silently rewriting
        one would make the binding it exists to protect unjoinable.
        """
        if not value.strip():
            msg = "identifier must not be blank"
            raise ValueError(msg)
        return value
