"""Read model for dashboard metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class DashboardMetrics:
    """Read model for dashboard metrics.

    Contains aggregate metrics for the entire system.
    """

    total_workflows: int = 0
    """Total number of workflows."""

    active_workflows: int = 0
    """Number of currently running workflows."""

    completed_workflows: int = 0
    """Number of completed workflows."""

    failed_workflows: int = 0
    """Number of failed workflows."""

    total_sessions: int = 0
    """Total number of sessions."""

    total_artifacts: int = 0
    """Total number of artifacts."""

    total_tokens: int = 0
    """Total tokens used across all sessions."""

    total_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    """Total cost in USD."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DashboardMetrics:
        """Create from dictionary data."""
        return cls(
            total_workflows=data.get("total_workflows", 0),
            active_workflows=data.get("active_workflows", 0),
            completed_workflows=data.get("completed_workflows", 0),
            failed_workflows=data.get("failed_workflows", 0),
            total_sessions=data.get("total_sessions", 0),
            total_artifacts=data.get("total_artifacts", 0),
            total_tokens=data.get("total_tokens", 0),
            total_cost_usd=Decimal(str(data.get("total_cost_usd", 0))),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "total_workflows": self.total_workflows,
            "active_workflows": self.active_workflows,
            "completed_workflows": self.completed_workflows,
            "failed_workflows": self.failed_workflows,
            "total_sessions": self.total_sessions,
            "total_artifacts": self.total_artifacts,
            "total_tokens": self.total_tokens,
            "total_cost_usd": str(self.total_cost_usd),
        }
