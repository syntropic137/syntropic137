"""System Updated domain event.

Emitted when a system's details are updated.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.SystemUpdated", "v1")
class SystemUpdatedEvent(DomainEvent):
    """Event emitted when a system is updated.

    Attributes:
        system_id: Unique identifier for the system.
        name: Updated name, or None if unchanged.
        description: Updated description, or None if unchanged.
    """

    system_id: str
    name: str | None = None
    description: str | None = None

    @field_validator("system_id")
    @classmethod
    def validate_system_id(cls, v: str) -> str:
        """Ensure system_id is provided."""
        if not v:
            raise ValueError("system_id is required")
        return v
