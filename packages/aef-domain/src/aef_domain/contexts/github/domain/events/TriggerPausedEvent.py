"""Trigger Paused domain event.

Emitted when a trigger rule is paused.
"""

from __future__ import annotations

from typing import Any

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("github.TriggerPaused", "v1")
class TriggerPausedEvent(DomainEvent):
    """Event emitted when a trigger rule is paused.

    Attributes:
        trigger_id: Unique identifier for the trigger rule.
        paused_by: User or agent that paused the trigger.
        reason: Optional reason for pausing.
    """

    trigger_id: str
    paused_by: str = ""
    reason: Any = None

    @field_validator("trigger_id")
    @classmethod
    def validate_trigger_id(cls, v: str) -> str:
        """Ensure trigger_id is provided."""
        if not v:
            raise ValueError("trigger_id is required")
        return v
