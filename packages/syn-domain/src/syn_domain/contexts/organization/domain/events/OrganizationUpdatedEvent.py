"""Organization Updated domain event.

Emitted when an organization's details are updated.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.OrganizationUpdated", "v1")
class OrganizationUpdatedEvent(DomainEvent):
    """Event emitted when an organization is updated.

    Attributes:
        organization_id: Unique identifier for the organization.
        name: Updated name, or None if unchanged.
        slug: Updated slug, or None if unchanged.
    """

    organization_id: str
    name: str | None = None
    slug: str | None = None

    @field_validator("organization_id")
    @classmethod
    def validate_organization_id(cls, v: str) -> str:
        """Ensure organization_id is provided."""
        if not v:
            raise ValueError("organization_id is required")
        return v
