"""Read model for workflow detail views."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class PhaseDetail:
    """Read model for phase information within a workflow."""

    id: str
    name: str
    agent_type: str
    status: str
    started_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    error_message: str | None = None

    # Phase metrics
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0
    cost_usd: str = "0"
    session_id: str | None = None


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

    phases: list[PhaseDetail] = field(default_factory=list)
    """List of phases in the workflow."""

    created_at: datetime | None = None
    """When the workflow was created."""

    started_at: datetime | None = None
    """When the workflow execution started."""

    completed_at: datetime | None = None
    """When the workflow completed (if completed)."""

    error_message: str | None = None
    """Error message if the workflow failed."""

    completed_phases: int = 0
    """Number of completed phases."""

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowDetail":
        """Create from dictionary data."""
        phases_data = data.get("phases", [])
        phases = [
            PhaseDetail(
                id=p.get("id", p.get("phase_id", "")),  # Support both id and phase_id
                name=p.get("name", ""),
                agent_type=p.get("agent_type", ""),
                status=p.get("status", "pending"),
                started_at=p.get("started_at"),
                completed_at=p.get("completed_at"),
                error_message=p.get("error_message"),
                input_tokens=p.get("input_tokens", 0),
                output_tokens=p.get("output_tokens", 0),
                total_tokens=p.get("total_tokens", 0),
                duration_seconds=p.get("duration_seconds", 0.0),
                cost_usd=str(p.get("cost_usd", "0")),
                session_id=p.get("session_id"),
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
            completed_phases=data.get("completed_phases", 0),
        )

    @staticmethod
    def _to_iso_string(value: datetime | str | None) -> str | None:
        """Convert datetime or string to ISO string."""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return value.isoformat()

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
                "started_at": WorkflowDetail._to_iso_string(p.started_at),
                "completed_at": WorkflowDetail._to_iso_string(p.completed_at),
                "error_message": p.error_message,
                "input_tokens": p.input_tokens,
                "output_tokens": p.output_tokens,
                "total_tokens": p.total_tokens,
                "duration_seconds": p.duration_seconds,
                "cost_usd": p.cost_usd,
                "session_id": p.session_id,
            }

        return {
            "id": self.id,
            "name": self.name,
            "workflow_type": self.workflow_type,
            "classification": self.classification,
            "status": self.status,
            "description": self.description,
            "phases": [phase_to_dict(p) for p in self.phases],
            "created_at": self._to_iso_string(self.created_at),
            "started_at": self._to_iso_string(self.started_at),
            "completed_at": self._to_iso_string(self.completed_at),
            "error_message": self.error_message,
            "completed_phases": self.completed_phases,
        }
