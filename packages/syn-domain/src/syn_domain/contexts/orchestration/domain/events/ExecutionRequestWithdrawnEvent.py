"""ExecutionRequestWithdrawn event (#1650)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves it at runtime

from event_sourcing import DomainEvent, event


@event("ExecutionRequestWithdrawn", "v1")
class ExecutionRequestWithdrawnEvent(DomainEvent):
    """An admitted direct start was withdrawn before its execution existed.

    Terminal for the request: nothing starts it after this, in this process or
    after a restart. It says nothing about an execution that already started;
    that one is cancelled, not withdrawn.
    """

    execution_id: str
    workflow_id: str
    reason: str | None = None
    withdrawn_at: datetime
