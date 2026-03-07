"""System Deleted domain event.

Emitted when a system is soft-deleted.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.SystemDeleted", "v1")
class SystemDeletedEvent(DomainEvent):
    """Event emitted when a system is deleted.

    Attributes:
        system_id: Unique identifier for the system.
        deleted_by: User or agent that deleted the system.
    """

    system_id: str
    deleted_by: str = ""

    @field_validator("system_id")
    @classmethod
    def validate_system_id(cls, v: str) -> str:
        """Ensure system_id is provided."""
        if not v:
            raise ValueError("system_id is required")
        return v
