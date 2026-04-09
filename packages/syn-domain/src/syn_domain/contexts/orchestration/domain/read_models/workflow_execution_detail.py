"""Read model for workflow execution detail view."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class PhaseExecutionDetail:
    """Detailed metrics for a phase within an execution."""

    workflow_phase_id: str
    """Phase identifier within the workflow execution."""

    name: str
    """Human-readable phase name."""

    status: str
    """Status: pending, running, completed, failed."""

    session_id: str | None = None
    """Session ID that executed this phase."""

    agent_session_id: str | None = None
    """Claude CLI agent session ID for OTel correlation (ADR-028)."""

    artifact_id: str | None = None
    """Artifact ID produced by this phase."""

    input_tokens: int = 0
    """Input tokens used."""

    output_tokens: int = 0
    """Output tokens used."""

    cache_creation_tokens: int = 0
    """Cache creation (write) tokens used."""

    cache_read_tokens: int = 0
    """Cache read tokens used."""

    total_tokens: int = 0
    """Total tokens used."""

    duration_seconds: float = 0.0
    """Duration of phase execution."""

    cost_usd: Decimal | str = Decimal("0")
    """Cost in USD."""

    started_at: datetime | str | None = None
    """When the phase started."""

    completed_at: datetime | str | None = None
    """When the phase completed."""

    error_message: str | None = None
    """Error message if phase failed."""

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
            "workflow_phase_id": self.workflow_phase_id,
            "name": self.name,
            "status": self.status,
            "session_id": self.session_id,
            "agent_session_id": self.agent_session_id,
            "artifact_id": self.artifact_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "total_tokens": self.total_tokens,
            "duration_seconds": self.duration_seconds,
            "cost_usd": str(self.cost_usd),
            "started_at": self._to_iso_string(self.started_at),
            "completed_at": self._to_iso_string(self.completed_at),
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PhaseExecutionDetail":
        """Create from dictionary data.

        Supports both new naming (workflow_phase_id) and legacy (phase_id).
        """
        cost = data.get("cost_usd", "0")
        if isinstance(cost, str):
            cost = Decimal(cost)

        # Support both new and legacy naming for backward compatibility
        phase_id = data.get("workflow_phase_id") or data.get("phase_id", "")

        return cls(
            workflow_phase_id=phase_id,
            name=data.get("name", ""),
            status=data.get("status", "pending"),
            session_id=data.get("session_id"),
            agent_session_id=data.get("agent_session_id"),
            artifact_id=data.get("artifact_id"),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cache_creation_tokens=data.get("cache_creation_tokens", 0),
            cache_read_tokens=data.get("cache_read_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            duration_seconds=data.get("duration_seconds", 0.0),
            cost_usd=cost,
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message"),
        )


@dataclass(frozen=True)
class WorkflowExecutionDetail:
    """Full detail of a workflow execution including per-phase metrics."""

    workflow_execution_id: str
    """Unique identifier for this workflow execution run."""

    workflow_id: str
    """ID of the workflow template being executed."""

    workflow_name: str
    """Display name of the workflow."""

    status: str
    """Current status (pending, running, completed, failed)."""

    started_at: datetime | str | None = None
    """When the execution started."""

    completed_at: datetime | str | None = None
    """When the execution completed (if completed)."""

    phases: tuple[PhaseExecutionDetail, ...] = field(default_factory=tuple)
    """Per-phase execution details with metrics."""

    total_input_tokens: int = 0
    """Total input tokens across all phases."""

    total_output_tokens: int = 0
    """Total output tokens across all phases."""

    total_cost_usd: Decimal | str = Decimal("0")
    """Total cost in USD."""

    total_duration_seconds: float = 0.0
    """Total duration of the execution."""

    artifact_ids: tuple[str, ...] = field(default_factory=tuple)
    """IDs of all artifacts produced."""

    error_message: str | None = None
    """Error message if execution failed."""

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowExecutionDetail":
        """Create from dictionary data.

        Supports both new naming (workflow_execution_id) and legacy (execution_id).
        """
        phases_data = data.get("phases", [])
        phases = tuple(PhaseExecutionDetail.from_dict(p) for p in phases_data)

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
            phases=phases,
            total_input_tokens=data.get("total_input_tokens", 0),
            total_output_tokens=data.get("total_output_tokens", 0),
            total_cost_usd=cost,
            total_duration_seconds=data.get("total_duration_seconds", 0.0),
            artifact_ids=tuple(data.get("artifact_ids", [])),
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
            "workflow_execution_id": self.workflow_execution_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "started_at": self._to_iso_string(self.started_at),
            "completed_at": self._to_iso_string(self.completed_at),
            "phases": [p.to_dict() for p in self.phases],
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": str(self.total_cost_usd),
            "total_duration_seconds": self.total_duration_seconds,
            "artifact_ids": list(self.artifact_ids),
            "error_message": self.error_message,
        }
