"""Read model for dashboard metrics.

Lane 1 domain truth — tokens only. Cost is Lane 2 telemetry and is merged in
at the API boundary from the execution_cost projection.
"""

from __future__ import annotations

from dataclasses import dataclass
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

    total_artifact_bytes: int = 0
    """Total artifact size in bytes."""

    total_tokens: int = 0
    """Total tokens used across all sessions."""

    total_input_tokens: int = 0
    """Total input tokens used across all sessions."""

    total_output_tokens: int = 0
    """Total output tokens used across all sessions."""

    total_cache_creation_tokens: int = 0
    """Total cache creation tokens used across all sessions."""

    total_cache_read_tokens: int = 0
    """Total cache read tokens used across all sessions."""

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
            total_artifact_bytes=data.get("total_artifact_bytes", 0),
            total_tokens=data.get("total_tokens", 0),
            total_input_tokens=data.get("total_input_tokens", 0),
            total_output_tokens=data.get("total_output_tokens", 0),
            total_cache_creation_tokens=data.get("total_cache_creation_tokens", 0),
            total_cache_read_tokens=data.get("total_cache_read_tokens", 0),
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
            "total_artifact_bytes": self.total_artifact_bytes,
            "total_tokens": self.total_tokens,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_creation_tokens": self.total_cache_creation_tokens,
            "total_cache_read_tokens": self.total_cache_read_tokens,
        }
