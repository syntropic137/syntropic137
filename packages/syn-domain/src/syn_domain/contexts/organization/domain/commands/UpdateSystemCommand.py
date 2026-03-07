"""Update System command.

Command to update an existing system's details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class UpdateSystemCommand:
    """Command to update a system.

    Attributes:
        system_id: ID of the system to update.
        name: New name, or None to leave unchanged.
        description: New description, or None to leave unchanged.
        command_id: Unique identifier for this command.
    """

    system_id: str
    name: str | None = None
    description: str | None = None
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        return self.system_id

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.system_id:
            raise ValueError("system_id is required")
        if self.name is None and self.description is None:
            raise ValueError("at least one of name or description must be provided")
