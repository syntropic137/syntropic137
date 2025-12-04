"""Read model for session list views."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


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

    @classmethod
    def from_dict(cls, data: dict) -> "SessionSummary":
        """Create from dictionary data."""
        return cls(
            id=data["id"],
            workflow_id=data["workflow_id"],
            agent_type=data.get("agent_type", ""),
            status=data.get("status", "pending"),
            total_tokens=data.get("total_tokens", 0),
            total_cost_usd=Decimal(str(data.get("total_cost_usd", 0))),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
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
        }
