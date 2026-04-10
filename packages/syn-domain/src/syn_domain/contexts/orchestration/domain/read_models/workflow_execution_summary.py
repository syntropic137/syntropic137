"""Read model for workflow execution (run) list views."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class WorkflowExecutionSummary:
    """Read model for workflow execution list view.

    This is a lightweight DTO optimized for listing workflow executions (runs).
    Each execution represents a single run of a workflow template.
    """

    workflow_execution_id: str
    """Unique identifier for this workflow execution run."""

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

    tool_call_count: int = 0
    """Total number of tool calls across all phases."""

    expected_completion_at: datetime | str | None = None
    """When we expect this execution to complete (for stale detection)."""

    error_message: str | None = None
    """Error message if execution failed."""

    repos: tuple[str, ...] = field(default_factory=tuple)
    """Full GitHub URLs of repositories cloned for this execution (ADR-058)."""

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowExecutionSummary":
        """Create from dictionary data.

        Supports both new naming (workflow_execution_id) and legacy (execution_id).
        """
        cost = data.get("total_cost_usd", "0")
        if isinstance(cost, str):
            cost = Decimal(cost)

        # Support both new and legacy naming for backward compatibility
        execution_id = data.get("workflow_execution_id") or data.get("execution_id", "")

        return cls(
            workflow_execution_id=execution_id,
            workflow_id=data["workflow_id"],
            workflow_name=data.get("workflow_name", ""),
            status=data.get("status", "pending"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            completed_phases=data.get("completed_phases", 0),
            total_phases=data.get("total_phases", 0),
            total_tokens=data.get("total_tokens", 0),
            total_cost_usd=cost,
            tool_call_count=data.get("tool_call_count", 0),
            expected_completion_at=data.get("expected_completion_at"),
            error_message=data.get("error_message"),
            repos=tuple(data.get("repos", [])),
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
            "workflow_execution_id": self.workflow_execution_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "started_at": self._to_iso_string(self.started_at),
            "completed_at": self._to_iso_string(self.completed_at),
            "completed_phases": self.completed_phases,
            "total_phases": self.total_phases,
            "total_tokens": self.total_tokens,
            "total_cost_usd": str(self.total_cost_usd),
            "tool_call_count": self.tool_call_count,
            "expected_completion_at": self._to_iso_string(self.expected_completion_at),
            "error_message": self.error_message,
            "repos": list(self.repos),
        }
