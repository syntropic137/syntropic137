"""Read model for session list views."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class OperationRecord:
    """Individual operation recorded during a session."""

    operation_id: str
    operation_type: str
    timestamp: str | datetime | None
    duration_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    tool_name: str | None = None
    success: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "OperationRecord":
        """Create from dictionary."""
        return cls(
            operation_id=data.get("operation_id", ""),
            operation_type=data.get("operation_type", ""),
            timestamp=data.get("timestamp"),
            duration_seconds=data.get("duration_seconds"),
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
            total_tokens=data.get("total_tokens"),
            tool_name=data.get("tool_name"),
            success=data.get("success", True),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        ts = self.timestamp
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "timestamp": ts,
            "duration_seconds": self.duration_seconds,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "tool_name": self.tool_name,
            "success": self.success,
        }


@dataclass(frozen=True)
class SessionSummary:
    """Read model for session list view.

    This is a lightweight DTO optimized for listing sessions.
    """

    id: str
    """Unique identifier for the session."""

    workflow_id: str
    """ID of the workflow this session belongs to."""

    agent_type: str
    """Type of agent used in this session."""

    status: str
    """Current status (pending, in_progress, completed, failed)."""

    total_tokens: int
    """Total tokens used in this session."""

    total_cost_usd: Decimal
    """Total cost in USD for this session."""

    started_at: datetime | None
    """When the session started."""

    completed_at: datetime | None
    """When the session completed (if completed)."""

    # Enhanced fields for detailed metrics
    input_tokens: int = 0
    """Input tokens used in this session."""

    output_tokens: int = 0
    """Output tokens used in this session."""

    duration_seconds: float | None = None
    """Duration of the session in seconds."""

    phase_id: str | None = None
    """ID of the phase this session belongs to."""

    operations: tuple[OperationRecord, ...] = ()
    """Operations recorded during this session."""

    @classmethod
    def from_dict(cls, data: dict) -> "SessionSummary":
        """Create from dictionary data."""
        # Parse operations list
        ops_data = data.get("operations", [])
        operations = tuple(OperationRecord.from_dict(op) for op in ops_data)

        return cls(
            id=data["id"],
            workflow_id=data["workflow_id"],
            agent_type=data.get("agent_type", ""),
            status=data.get("status", "pending"),
            total_tokens=data.get("total_tokens", 0),
            total_cost_usd=Decimal(str(data.get("total_cost_usd", 0))),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            duration_seconds=data.get("duration_seconds"),
            phase_id=data.get("phase_id"),
            operations=operations,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        # Handle both datetime objects and ISO string format
        # (events from event store come back as strings after serialization)
        started_at_str = None
        if self.started_at:
            started_at_str = (
                self.started_at.isoformat()
                if isinstance(self.started_at, datetime)
                else str(self.started_at)
            )

        completed_at_str = None
        if self.completed_at:
            completed_at_str = (
                self.completed_at.isoformat()
                if isinstance(self.completed_at, datetime)
                else str(self.completed_at)
            )

        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "agent_type": self.agent_type,
            "status": self.status,
            "total_tokens": self.total_tokens,
            "total_cost_usd": str(self.total_cost_usd),
            "started_at": started_at_str,
            "completed_at": completed_at_str,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_seconds": self.duration_seconds,
            "phase_id": self.phase_id,
            "operations": [op.to_dict() for op in self.operations],
        }
