"""Passage-of-time signal for recovering durable inventory work after silence."""

from datetime import datetime

from event_sourcing import DomainEvent, event
from pydantic import ConfigDict


@event("InventoryReconciliationSweep", "v1")
class InventoryReconciliationSweepEvent(DomainEvent):
    model_config = ConfigDict(frozen=True, extra="forbid")
    observed_at: datetime
