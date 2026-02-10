"""Trigger Resumed domain event.

Emitted when a paused trigger rule is resumed.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("github.TriggerResumed", "v1")
class TriggerResumedEvent(DomainEvent):
    """Event emitted when a trigger rule is resumed.

    Attributes:
        trigger_id: Unique identifier for the trigger rule.
        resumed_by: User or agent that resumed the trigger.
    """

    trigger_id: str
    resumed_by: str = ""

    @field_validator("trigger_id")
    @classmethod
    def validate_trigger_id(cls, v: str) -> str:
        """Ensure trigger_id is provided."""
        if not v:
            raise ValueError("trigger_id is required")
        return v
