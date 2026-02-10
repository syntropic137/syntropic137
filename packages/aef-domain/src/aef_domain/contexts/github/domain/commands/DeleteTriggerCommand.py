"""Delete Trigger command.

Command to soft-delete a trigger rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class DeleteTriggerCommand:
    """Command to delete a trigger rule.

    Attributes:
        trigger_id: ID of the trigger rule to delete.
        deleted_by: User or agent deleting the trigger.
        command_id: Unique identifier for this command.
    """

    trigger_id: str
    deleted_by: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.trigger_id:
            raise ValueError("trigger_id is required")
