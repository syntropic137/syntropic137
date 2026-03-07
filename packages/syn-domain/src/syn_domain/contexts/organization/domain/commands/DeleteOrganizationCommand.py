"""Delete Organization command.

Command to soft-delete an organization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class DeleteOrganizationCommand:
    """Command to delete an organization.

    Attributes:
        organization_id: ID of the organization to delete.
        deleted_by: User or agent deleting the organization.
        command_id: Unique identifier for this command.
    """

    organization_id: str
    deleted_by: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        return self.organization_id

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.organization_id:
            raise ValueError("organization_id is required")
