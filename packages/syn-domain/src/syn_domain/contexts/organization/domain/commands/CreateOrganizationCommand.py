"""Create Organization command.

Command to create a new organization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class CreateOrganizationCommand:
    """Command to create a new organization.

    Attributes:
        name: Human-readable name for the organization.
        slug: URL-safe slug for the organization.
        created_by: User or agent creating the organization.
        aggregate_id: Optional pre-assigned aggregate ID.
        command_id: Unique identifier for this command.
    """

    name: str
    slug: str
    created_by: str = ""
    aggregate_id: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.name:
            raise ValueError("name is required")
        if not self.slug:
            raise ValueError("slug is required")
