"""Replayable management facts. No dependencies on aggregates or read models."""

from typing import Literal
from uuid import UUID

from event_sourcing import DomainEvent, event
from pydantic import ConfigDict, Field


@event("InventoryReconciliationChanged", "v1")
class InventoryReconciliationChangedEvent(DomainEvent):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_instance_id: str
    execution_id: str
    evidence_watermark: int = Field(ge=0)
    expected_head: UUID | None = None
    snapshot_id: UUID
    resolver_version: str
    stage: Literal["pending", "publishing", "completed", "failed"]
    revision: str | None = None
    failure_code: str | None = None
