"""Create System command.

Command to create a new system within an organization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class CreateSystemCommand:
    """Command to create a new system.

    Attributes:
        organization_id: ID of the organization this system belongs to.
        name: Human-readable name for the system.
        description: Optional description of the system.
        created_by: User or agent creating the system.
        aggregate_id: Optional pre-assigned aggregate ID.
        command_id: Unique identifier for this command.
    """

    organization_id: str
    name: str
    description: str = ""
    created_by: str = ""
    aggregate_id: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.organization_id:
            raise ValueError("organization_id is required")
        if not self.name:
            raise ValueError("name is required")
