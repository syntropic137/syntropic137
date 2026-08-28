"""DelegationBound event - a child's harness-native id became known (#895).

Separate from ``DelegationStarted`` by necessity rather than taste: the
platform mints the attempt id before launch, and the harness does not choose
its own session id until it starts. One event cannot carry both.

This is the join between the platform's id space and the harness's. Without it
a child transcript cannot be matched to the platform session it belongs to,
and concurrent children of one provider are indistinguishable.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event

# Runtime import: Pydantic builds the validator from this annotation, so it
# cannot live in a TYPE_CHECKING block.
from syn_domain.contexts.agent_sessions.domain.events._identifiers import (  # noqa: TC001
    NonBlankId,
)


@event("DelegationBound", "v1")
class DelegationBoundEvent(DomainEvent):
    """A delegation attempt was joined to the harness session it produced."""

    delegation_attempt_id: NonBlankId
    harness_session_id: NonBlankId
    """The id the harness gave itself, read from that child's own stream."""
