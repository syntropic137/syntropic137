"""Read model for workflow TEMPLATE detail views.

NOTE: This is for workflow TEMPLATES (definitions), not executions.
Templates don't have status, started_at, completed_at, etc.
For execution details, see WorkflowExecutionDetail.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class PhaseDefinitionDetail:
    """Read model for phase DEFINITION within a workflow template.

    This represents the phase as defined in the template,
    NOT the execution state of a phase.
    """

    id: str
    """Phase identifier."""

    name: str
    """Display name of the phase."""

    description: str | None = None
    """Optional description of what this phase does."""

    agent_type: str = ""
    """Type of agent to use for this phase."""

    order: int = 0
    """Order in which this phase executes."""


@dataclass(frozen=True)
class WorkflowDetail:
    """Read model for workflow TEMPLATE detail view.

    This represents a workflow definition/template.
    Templates are reusable definitions that can be executed multiple times.
    Each execution creates a WorkflowExecution with its own status and metrics.
    """

    id: str
    """Unique identifier for the workflow template."""

    name: str
    """Display name of the workflow."""

    workflow_type: str
    """Type of workflow (e.g., 'research', 'implementation')."""

    classification: str
    """Classification category of the workflow."""

    description: str | None
    """Optional description of the workflow."""

    phases: list[PhaseDefinitionDetail] = field(default_factory=list)
    """List of phase definitions in the workflow."""

    created_at: datetime | None = None
    """When the workflow template was created."""

    runs_count: int = 0
    """Number of times this workflow has been executed."""

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowDetail":
        """Create from dictionary data."""
        phases_data = data.get("phases", [])
        phases = [
            PhaseDefinitionDetail(
                id=p.get("id", p.get("phase_id", "")),
                name=p.get("name", ""),
                description=p.get("description"),
                agent_type=p.get("agent_type", ""),
                order=p.get("order", i),
            )
            for i, p in enumerate(phases_data)
        ]

        return cls(
            id=data["id"],
            name=data["name"],
            workflow_type=data.get("workflow_type", ""),
            classification=data.get("classification", ""),
            description=data.get("description"),
            phases=phases,
            created_at=data.get("created_at"),
            runs_count=data.get("runs_count", 0),
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

        def phase_to_dict(p: PhaseDefinitionDetail | dict) -> dict:
            """Convert a phase to dict."""
            if isinstance(p, dict):
                return p
            return {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "agent_type": p.agent_type,
                "order": p.order,
            }

        return {
            "id": self.id,
            "name": self.name,
            "workflow_type": self.workflow_type,
            "classification": self.classification,
            "description": self.description,
            "phases": [phase_to_dict(p) for p in self.phases],
            "created_at": self._to_iso_string(self.created_at),
            "runs_count": self.runs_count,
        }
