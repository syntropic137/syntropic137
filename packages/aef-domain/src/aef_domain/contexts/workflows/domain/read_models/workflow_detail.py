"""Read model for workflow detail views."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PhaseDetail:
    """Read model for phase information within a workflow."""

    id: str
    name: str
    agent_type: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class WorkflowDetail:
    """Read model for workflow detail view.

    This is a comprehensive DTO containing all workflow information
    needed for detailed displays.
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

    description: str | None
    """Optional description of the workflow."""

    phases: list[PhaseDetail | dict[str, Any]] = field(default_factory=list)
    """List of phases in the workflow (can be PhaseDetail or dict)."""

    created_at: datetime | None = None
    """When the workflow was created."""

    started_at: datetime | None = None
    """When the workflow execution started."""

    completed_at: datetime | None = None
    """When the workflow completed (if completed)."""

    error_message: str | None = None
    """Error message if the workflow failed."""

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowDetail":
        """Create from dictionary data."""
        phases_data = data.get("phases", [])
        phases = [
            PhaseDetail(
                id=p.get("id", ""),
                name=p.get("name", ""),
                agent_type=p.get("agent_type", ""),
                status=p.get("status", "pending"),
                started_at=p.get("started_at"),
                completed_at=p.get("completed_at"),
                error_message=p.get("error_message"),
            )
            for p in phases_data
        ]

        return cls(
            id=data["id"],
            name=data["name"],
            workflow_type=data.get("workflow_type", ""),
            classification=data.get("classification", ""),
            status=data.get("status", "pending"),
            description=data.get("description"),
            phases=phases,
            created_at=data.get("created_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""

        def phase_to_dict(p: PhaseDetail | dict) -> dict:
            """Convert a phase to dict, handling both PhaseDetail and dict inputs."""
            if isinstance(p, dict):
                return p
            return {
                "id": p.id,
                "name": p.name,
                "agent_type": p.agent_type,
                "status": p.status,
                "started_at": p.started_at.isoformat() if p.started_at else None,
                "completed_at": (p.completed_at.isoformat() if p.completed_at else None),
                "error_message": p.error_message,
            }

        return {
            "id": self.id,
            "name": self.name,
            "workflow_type": self.workflow_type,
            "classification": self.classification,
            "status": self.status,
            "description": self.description,
            "phases": [phase_to_dict(p) for p in self.phases],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (self.completed_at.isoformat() if self.completed_at else None),
            "error_message": self.error_message,
        }
