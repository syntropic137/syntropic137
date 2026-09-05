"""Read model for workflow execution detail view.

Lane 1 domain truth — tokens only. Cost is Lane 2 telemetry and is merged in
at the API boundary from the execution_cost projection.
"""

from dataclasses import dataclass, field
from datetime import datetime

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import PushedWork


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

    duration_seconds: float | None = None
    """Seconds this phase took, or ``None`` when nothing has measured it yet.

    Mirrors ``PhaseDetail.duration_seconds`` in the projection that writes this
    read model: unknown must stay distinguishable from a measured zero all the
    way to the API boundary, which is the only place that can decide what to
    show for a phase still in flight.
    """

    started_at: datetime | str | None = None
    """When the phase started."""

    completed_at: datetime | str | None = None
    """When the phase completed."""

    error_message: str | None = None
    """Error message if phase failed."""

    pushed_work: tuple[PushedWork, ...] | None = None
    """Branches a remote was confirmed to hold for this failed phase (#1200).

    THREE-VALUED, and the API boundary passes all three through unchanged:
    records are where the work is, `()` means the workspace was asked and
    nothing in it had reached a remote, and `None` means nothing could ask -
    including every phase that did not fail and every event written before this
    field existed. A phase whose work is sitting on a branch and one whose work
    died with its container are different incidents; flattening the empties
    would merge them again.
    """

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
            "started_at": self._to_iso_string(self.started_at),
            "completed_at": self._to_iso_string(self.completed_at),
            "error_message": self.error_message,
            "pushed_work": (
                None if self.pushed_work is None else [w.model_dump() for w in self.pushed_work]
            ),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PhaseExecutionDetail":
        """Create from dictionary data.

        Supports both new naming (workflow_phase_id) and legacy (phase_id).
        """
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
            duration_seconds=data.get("duration_seconds"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message"),
            pushed_work=_pushed_work(data.get("pushed_work")),
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

    total_cache_creation_tokens: int = 0
    """Total cache creation tokens across all phases."""

    total_cache_read_tokens: int = 0
    """Total cache read tokens across all phases."""

    total_duration_seconds: float = 0.0
    """Total duration of the execution."""

    artifact_ids: tuple[str, ...] = field(default_factory=tuple)
    """IDs of all artifacts produced."""

    error_message: str | None = None
    """Error message if execution failed."""

    repos: tuple[str, ...] = field(default_factory=tuple)
    """Full GitHub URLs of repositories cloned for this execution (ADR-058)."""

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowExecutionDetail":
        """Create from dictionary data.

        Supports both new naming (workflow_execution_id) and legacy (execution_id).
        """
        phases_data = data.get("phases", [])
        phases = tuple(PhaseExecutionDetail.from_dict(p) for p in phases_data)

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
            total_cache_creation_tokens=data.get("total_cache_creation_tokens", 0),
            total_cache_read_tokens=data.get("total_cache_read_tokens", 0),
            total_duration_seconds=data.get("total_duration_seconds", 0.0),
            artifact_ids=tuple(data.get("artifact_ids", [])),
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
            "phases": [p.to_dict() for p in self.phases],
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_creation_tokens": self.total_cache_creation_tokens,
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "total_duration_seconds": self.total_duration_seconds,
            "artifact_ids": list(self.artifact_ids),
            "error_message": self.error_message,
            "repos": list(self.repos),
        }


def _pushed_work(stored: object) -> tuple[PushedWork, ...] | None:
    """Rebuild the pushed-work records a projection stored, keeping None as None.

    The store round-trips these as plain data, so this is the hop where they
    become the value object again - and the hop where a defaulted `[]` would
    turn "nobody looked" into "looked and found nothing" (#1200). Anything that
    is not a list is treated as absent: a malformed row is not evidence about a
    remote either.
    """
    if not isinstance(stored, list):
        return None
    return tuple(PushedWork.model_validate(entry) for entry in stored)
