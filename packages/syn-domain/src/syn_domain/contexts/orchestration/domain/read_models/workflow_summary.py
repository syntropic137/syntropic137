"""Read model for workflow list views.

NOTE: Workflow templates do NOT have status. Status belongs to WorkflowExecutions.
Templates are definitions - they're either "active" (usable) or "archived".
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WorkflowSummary:
    """Read model for workflow TEMPLATE list view.

    This is a lightweight DTO optimized for listing workflow templates.
    Templates are definitions - they don't have execution status.
    For execution status, see WorkflowExecutionSummary.
    """

    id: str
    """Unique identifier for the workflow template."""

    name: str
    """Display name of the workflow."""

    workflow_type: str
    """Type of workflow (e.g., 'research', 'implementation')."""

    classification: str
    """Classification category of the workflow."""

    phase_count: int
    """Number of phases in the workflow definition."""

    description: str | None
    """Optional description of the workflow."""

    created_at: datetime | None
    """When the workflow template was created."""

    runs_count: int = 0
    """Number of times this workflow has been executed."""

    is_archived: bool = False
    """Whether this workflow template has been archived."""

    requires_repos: bool = True
    """Whether this workflow requires repository access at execution time (ADR-058 #666)."""

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowSummary":
        """Create from dictionary data."""
        return cls(
            id=data["id"],
            name=data["name"],
            workflow_type=data.get("workflow_type", ""),
            classification=data.get("classification", ""),
            phase_count=data.get("phase_count", 0),
            description=data.get("description"),
            created_at=data.get("created_at"),
            runs_count=data.get("runs_count", 0),
            is_archived=data.get("is_archived", False),
            requires_repos=data.get("requires_repos", True),
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
            "phase_count": self.phase_count,
            "description": self.description,
            "created_at": created_at_str,
            "runs_count": self.runs_count,
            "is_archived": self.is_archived,
            "requires_repos": self.requires_repos,
        }
