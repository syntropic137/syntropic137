"""Organization Created domain event.

Emitted when a new organization is created.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.OrganizationCreated", "v1")
class OrganizationCreatedEvent(DomainEvent):
    """Event emitted when an organization is created.

    Attributes:
        organization_id: Unique identifier for the organization.
        name: Human-readable name for the organization.
        slug: URL-safe slug for the organization.
        created_by: User or agent that created the organization.
    """

    organization_id: str
    name: str
    slug: str
    created_by: str = ""

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

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        """Ensure slug is provided."""
        if not v:
            raise ValueError("slug is required")
        return v
