"""Read model for workflow list views."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WorkflowSummary:
    """Read model for workflow list view.

    This is a lightweight DTO optimized for listing workflows.
    It contains only the fields needed for list displays and search.
    """

    id: str
    """Unique identifier for the workflow."""

    name: str
    """Display name of the workflow."""

    workflow_type: str
    """Type of workflow (e.g., 'sequential', 'parallel')."""

    classification: str
    """Classification category of the workflow."""

    status: str
    """Current status (pending, in_progress, completed, failed)."""

    phase_count: int
    """Number of phases in the workflow."""

    description: str | None
    """Optional description of the workflow."""

    created_at: datetime | None
    """When the workflow was created."""

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowSummary":
        """Create from dictionary data."""
        return cls(
            id=data["id"],
            name=data["name"],
            workflow_type=data.get("workflow_type", ""),
            classification=data.get("classification", ""),
            status=data.get("status", "pending"),
            phase_count=data.get("phase_count", 0),
            description=data.get("description"),
            created_at=data.get("created_at"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        # Handle created_at which could be datetime or already a string
        created_at_str = None
        if self.created_at:
            created_at_str = (
                self.created_at.isoformat()
                if isinstance(self.created_at, datetime)
                else str(self.created_at)
            )

        return {
            "id": self.id,
            "name": self.name,
            "workflow_type": self.workflow_type,
            "classification": self.classification,
            "status": self.status,
            "phase_count": self.phase_count,
            "description": self.description,
            "created_at": created_at_str,
        }
