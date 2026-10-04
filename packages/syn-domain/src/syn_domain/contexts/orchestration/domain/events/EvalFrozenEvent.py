"""EvalFrozen event (evals plan, #967)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event


@event("EvalFrozen", "v1")
class EvalFrozenEvent(DomainEvent):
    """The eval's goal and baseline are fixed from here on."""

    eval_id: str
    frozen_at: datetime
