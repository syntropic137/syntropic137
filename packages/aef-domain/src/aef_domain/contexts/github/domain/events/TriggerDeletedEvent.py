"""Trigger Deleted domain event.

Emitted when a trigger rule is soft-deleted.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("github.TriggerDeleted", "v1")
class TriggerDeletedEvent(DomainEvent):
    """Event emitted when a trigger rule is deleted.

    Attributes:
        trigger_id: Unique identifier for the trigger rule.
        deleted_by: User or agent that deleted the trigger.
    """

    trigger_id: str
    deleted_by: str = ""

    @field_validator("trigger_id")
    @classmethod
    def validate_trigger_id(cls, v: str) -> str:
        """Ensure trigger_id is provided."""
        if not v:
            raise ValueError("trigger_id is required")
        return v
