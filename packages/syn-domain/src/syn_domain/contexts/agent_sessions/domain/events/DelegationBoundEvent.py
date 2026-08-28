"""DelegationBound event - a child's harness-native id became known (#895).

Separate from ``DelegationStarted`` by necessity: the platform mints the
attempt id before launch, and the harness does not choose its own session id
until it starts, so one event cannot carry both.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("DelegationBound", "v1")
class DelegationBoundEvent(DomainEvent):
    """A delegation attempt was associated with a harness session.

    WHAT THIS MODEL GUARANTEES: both ids are present and non-blank.

    WHAT IT DOES NOT, and what the invariant owner must therefore enforce:

    - that ``delegation_attempt_id`` refers to an attempt that was started.
      A Bound for an unknown attempt validates here;
    - that an attempt is bound only once. Two Bound events carrying DIFFERENT
      harness ids for one attempt both validate, and the later one would
      silently re-point a child at another stream;
    - an identical re-bind is a legitimate retry and must be tolerated, while
      a conflicting one must be refused. Those are different cases and only
      the owner can tell them apart.
    """

    delegation_attempt_id: str
    harness_session_id: str
    """The id the harness gave itself, read from that child's own stream.

    Stored verbatim. It is an opaque key that must match what the harness
    emitted, so it is never normalised.
    """

    @field_validator("delegation_attempt_id", "harness_session_id")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            msg = "identifier must not be blank"
            raise ValueError(msg)
        return value
