"""TicketPullRequestStateChanged event (ADR-076). Ids and hashes only: never reporter text."""

from __future__ import annotations

from datetime import datetime

from event_sourcing import DomainEvent, event
from pydantic import Field

from syn_domain.contexts.feedback._shared.value_objects import PullRequestState


@event("TicketPullRequestStateChanged", "v1")
class TicketPullRequestStateChangedEvent(DomainEvent):
    """A linked pull request was observed in a new state."""

    ticket_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    number: int = Field(gt=0)
    state: PullRequestState
    merge_commit: str | None = None
    observed_at: datetime
