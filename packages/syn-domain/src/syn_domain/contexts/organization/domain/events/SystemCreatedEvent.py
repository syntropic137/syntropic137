"""System Created domain event.

Emitted when a new system is created within an organization.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.SystemCreated", "v1")
class SystemCreatedEvent(DomainEvent):
    """Event emitted when a system is created.

    Attributes:
        system_id: Unique identifier for the system.
        organization_id: ID of the organization this system belongs to.
        name: Human-readable name for the system.
        description: Optional description of the system.
        created_by: User or agent that created the system.
    """

    system_id: str
    organization_id: str
    name: str
    description: str = ""
    created_by: str = ""

    @field_validator("system_id")
    @classmethod
    def validate_system_id(cls, v: str) -> str:
        """Ensure system_id is provided."""
        if not v:
            raise ValueError("system_id is required")
        return v

    @field_validator("organization_id")
    @classmethod
    def validate_organization_id(cls, v: str) -> str:
        """Ensure organization_id is provided."""
        if not v:
            raise ValueError("organization_id is required")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure name is provided."""
        if not v:
            raise ValueError("name is required")
        return v
