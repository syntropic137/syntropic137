"""Read model for workflow execution (run) list views."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class WorkflowExecutionSummary:
    """Read model for workflow execution list view.

    This is a lightweight DTO optimized for listing workflow executions (runs).
    Each execution represents a single run of a workflow template.
    """

    execution_id: str
    """Unique identifier for this execution run."""

    workflow_id: str
    """ID of the workflow template being executed."""

    workflow_name: str
    """Display name of the workflow."""

    status: str
    """Current status (pending, running, completed, failed)."""

    started_at: datetime | str | None
    """When the execution started."""

    completed_at: datetime | str | None
    """When the execution completed (if completed)."""

    completed_phases: int
    """Number of phases completed so far."""

    total_phases: int
    """Total number of phases in the workflow."""

    total_tokens: int
    """Total tokens used across all phases."""

    total_cost_usd: Decimal | str
    """Total cost in USD."""

    error_message: str | None = None
    """Error message if execution failed."""

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowExecutionSummary":
        """Create from dictionary data."""
        cost = data.get("total_cost_usd", "0")
        if isinstance(cost, str):
            cost = Decimal(cost)

        return cls(
            execution_id=data["execution_id"],
            workflow_id=data["workflow_id"],
            workflow_name=data.get("workflow_name", ""),
            status=data.get("status", "pending"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            completed_phases=data.get("completed_phases", 0),
            total_phases=data.get("total_phases", 0),
            total_tokens=data.get("total_tokens", 0),
            total_cost_usd=cost,
            error_message=data.get("error_message"),
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
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "started_at": self._to_iso_string(self.started_at),
            "completed_at": self._to_iso_string(self.completed_at),
            "completed_phases": self.completed_phases,
            "total_phases": self.total_phases,
            "total_tokens": self.total_tokens,
            "total_cost_usd": str(self.total_cost_usd),
            "error_message": self.error_message,
        }
