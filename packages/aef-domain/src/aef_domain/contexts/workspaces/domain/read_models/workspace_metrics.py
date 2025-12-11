"""Workspace metrics read model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class WorkspaceMetrics:
    """Metrics for a single workspace lifecycle.

    Tracks timing and execution details for observability.
    """

    # Identity
    workspace_id: str
    session_id: str

    # Context
    workflow_id: str | None = None
    execution_id: str | None = None
    isolation_backend: str = "unknown"

    # Status
    status: str = "creating"

    # Timing (milliseconds)
    create_duration_ms: float | None = None
    destroy_duration_ms: float | None = None
    total_lifetime_ms: float | None = None

    # Execution stats
    commands_executed: int = 0
    commands_succeeded: int = 0
    commands_failed: int = 0
    artifacts_collected: int = 0

    # Timestamps
    created_at: datetime | None = None
    destroyed_at: datetime | None = None

    # Error info (if any)
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "workflow_id": self.workflow_id,
            "execution_id": self.execution_id,
            "isolation_backend": self.isolation_backend,
            "status": self.status,
            "create_duration_ms": self.create_duration_ms,
            "destroy_duration_ms": self.destroy_duration_ms,
            "total_lifetime_ms": self.total_lifetime_ms,
            "commands_executed": self.commands_executed,
            "commands_succeeded": self.commands_succeeded,
            "commands_failed": self.commands_failed,
            "artifacts_collected": self.artifacts_collected,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "destroyed_at": self.destroyed_at.isoformat() if self.destroyed_at else None,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceMetrics:
        """Create from dictionary."""
        created_at = data.get("created_at")
        destroyed_at = data.get("destroyed_at")

        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if isinstance(destroyed_at, str):
            destroyed_at = datetime.fromisoformat(destroyed_at.replace("Z", "+00:00"))

        return cls(
            workspace_id=data.get("workspace_id", ""),
            session_id=data.get("session_id", ""),
            workflow_id=data.get("workflow_id"),
            execution_id=data.get("execution_id"),
            isolation_backend=data.get("isolation_backend", "unknown"),
            status=data.get("status", "creating"),
            create_duration_ms=data.get("create_duration_ms"),
            destroy_duration_ms=data.get("destroy_duration_ms"),
            total_lifetime_ms=data.get("total_lifetime_ms"),
            commands_executed=data.get("commands_executed", 0),
            commands_succeeded=data.get("commands_succeeded", 0),
            commands_failed=data.get("commands_failed", 0),
            artifacts_collected=data.get("artifacts_collected", 0),
            created_at=created_at,
            destroyed_at=destroyed_at,
            error_type=data.get("error_type"),
            error_message=data.get("error_message"),
        )


@dataclass
class WorkspaceMetricsSummary:
    """Aggregated workspace metrics across multiple workspaces.

    Used for dashboard views and performance monitoring.
    """

    # Counts
    total_workspaces: int = 0
    workspaces_by_backend: dict[str, int] = field(default_factory=dict)
    workspaces_by_status: dict[str, int] = field(default_factory=dict)

    # Timing aggregates (milliseconds)
    avg_create_duration_ms: float = 0.0
    avg_destroy_duration_ms: float = 0.0
    avg_total_lifetime_ms: float = 0.0
    p95_create_duration_ms: float = 0.0
    p95_destroy_duration_ms: float = 0.0

    # Error stats
    error_count: int = 0
    error_rate: float = 0.0

    # Command stats
    total_commands_executed: int = 0
    command_success_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_workspaces": self.total_workspaces,
            "workspaces_by_backend": self.workspaces_by_backend,
            "workspaces_by_status": self.workspaces_by_status,
            "avg_create_duration_ms": self.avg_create_duration_ms,
            "avg_destroy_duration_ms": self.avg_destroy_duration_ms,
            "avg_total_lifetime_ms": self.avg_total_lifetime_ms,
            "p95_create_duration_ms": self.p95_create_duration_ms,
            "p95_destroy_duration_ms": self.p95_destroy_duration_ms,
            "error_count": self.error_count,
            "error_rate": self.error_rate,
            "total_commands_executed": self.total_commands_executed,
            "command_success_rate": self.command_success_rate,
        }
