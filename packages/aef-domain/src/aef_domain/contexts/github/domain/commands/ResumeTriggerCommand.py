"""Resume Trigger command.

Command to resume a paused trigger rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class ResumeTriggerCommand:
    """Command to resume a paused trigger rule.

    Attributes:
        trigger_id: ID of the trigger rule to resume.
        resumed_by: User or agent resuming the trigger.
        command_id: Unique identifier for this command.
    """

    trigger_id: str
    resumed_by: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        return self.trigger_id

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.trigger_id:
            raise ValueError("trigger_id is required")
