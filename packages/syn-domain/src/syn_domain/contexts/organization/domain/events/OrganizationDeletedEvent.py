"""Organization Deleted domain event.

Emitted when an organization is soft-deleted.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.OrganizationDeleted", "v1")
class OrganizationDeletedEvent(DomainEvent):
    """Event emitted when an organization is deleted.

    Attributes:
        organization_id: Unique identifier for the organization.
        deleted_by: User or agent that deleted the organization.
    """

    organization_id: str
    deleted_by: str = ""

    @field_validator("organization_id")
    @classmethod
    def validate_organization_id(cls, v: str) -> str:
        """Ensure organization_id is provided."""
        if not v:
            raise ValueError("organization_id is required")
        return v
