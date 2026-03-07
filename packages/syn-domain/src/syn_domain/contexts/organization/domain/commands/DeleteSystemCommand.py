"""Delete System command.

Command to soft-delete a system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class DeleteSystemCommand:
    """Command to delete a system.

    Attributes:
        system_id: ID of the system to delete.
        deleted_by: User or agent deleting the system.
        command_id: Unique identifier for this command.
    """

    system_id: str
    deleted_by: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        return self.system_id

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.system_id:
            raise ValueError("system_id is required")
