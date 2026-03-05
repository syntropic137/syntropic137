"""Update Organization command.

Command to update an existing organization's details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class UpdateOrganizationCommand:
    """Command to update an organization.

    Attributes:
        organization_id: ID of the organization to update.
        name: New name, or None to leave unchanged.
        slug: New slug, or None to leave unchanged.
        command_id: Unique identifier for this command.
    """

    organization_id: str
    name: str | None = None
    slug: str | None = None
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        return self.organization_id

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.organization_id:
            raise ValueError("organization_id is required")
        if self.name is None and self.slug is None:
            raise ValueError("at least one of name or slug must be provided")
