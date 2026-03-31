"""Archive Workflow Template command.

Command to soft-delete (archive) a workflow template.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class ArchiveWorkflowTemplateCommand:
    """Command to archive a workflow template.

    Attributes:
        workflow_id: ID of the workflow template to archive.
        archived_by: User or agent archiving the template.
        command_id: Unique identifier for this command.
    """

    workflow_id: str
    archived_by: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        return self.workflow_id

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.workflow_id:
            raise ValueError("workflow_id is required")
