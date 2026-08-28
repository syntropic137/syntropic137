"""DelegationStarted event - a delegated child run was launched (issue #895).

Recorded BEFORE the child produces anything. That ordering is the point: a
child that dies immediately still leaves a session that can be reported as
failed, rather than being indistinguishable from a delegation that never
happened.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event

# Runtime import: Pydantic builds the validator from this annotation, so it
# cannot live in a TYPE_CHECKING block.
from syn_domain.contexts.agent_sessions.domain.events._identifiers import (  # noqa: TC001
    NonBlankId,
)


@event("DelegationStarted", "v1")
class DelegationStartedEvent(DomainEvent):
    """A parent session launched a delegated child."""

    delegation_attempt_id: NonBlankId
    """Minted by the EDGE ADAPTER before launch, unique platform-wide.

    The adapter that mints it also reads that child's stream, so one instance
    owns both the id and the stream it belongs to. Concurrent children of one
    provider therefore never need correlating by time or arrival order.
    """

    parent_session_id: NonBlankId
    """The platform session that delegated."""

    root_session_id: NonBlankId
    """The top of the delegation tree. REQUIRED, never derived.

    The session aggregate's fallback sets root = parent when root is omitted,
    which is correct only at depth 1. At depth 3 a child's root becomes its
    parent rather than the true root, and nothing downstream can detect it.
    Requiring it here means a malformed tree cannot be built at all.
    """

    child_session_id: NonBlankId
    """The platform session minted for the child."""

    provider: NonBlankId
    """Which harness the child runs, for selecting the right adapter later."""
