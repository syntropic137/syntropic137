"""DelegationFinished event - a delegated child exited (issue #895).

Carries the DELEGATE's own exit status, not the enclosing shell's. That
distinction is the whole of #894: a phase reported success because the shell
exited zero while the delegation it declared never happened, and the agent
narrated a hypothetical result the platform then recorded as a success.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event

# Runtime import: Pydantic builds the validator from this annotation, so it
# cannot live in a TYPE_CHECKING block.
from syn_domain.contexts.agent_sessions.domain.events._identifiers import (  # noqa: TC001
    NonBlankId,
)


@event("DelegationFinished", "v1")
class DelegationFinishedEvent(DomainEvent):
    """A delegated child run ended."""

    delegation_attempt_id: NonBlankId
    exit_status: int
    """The delegate's own exit status. Non-zero means the delegation failed,
    regardless of what the surrounding shell reported."""
