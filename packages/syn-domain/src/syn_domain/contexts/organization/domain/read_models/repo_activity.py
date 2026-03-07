"""Repo activity read model.

Per-repo execution timeline entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RepoActivityEntry:
    """Single entry in a repo's execution timeline.

    Attributes:
        execution_id: Workflow execution ID.
        workflow_id: Workflow template ID.
        workflow_name: Human-readable workflow name.
        status: Execution status (started, completed, failed).
        started_at: ISO timestamp of execution start.
        completed_at: ISO timestamp of execution completion (empty if running).
        duration_seconds: Duration in seconds (0 if still running).
        trigger_source: What triggered the execution (webhook, manual, schedule).
    """

    execution_id: str
    workflow_id: str = ""
    workflow_name: str = ""
    status: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    trigger_source: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoActivityEntry:
        """Create from dictionary data."""
        return cls(
            execution_id=data.get("execution_id", ""),
            workflow_id=data.get("workflow_id", ""),
            workflow_name=data.get("workflow_name", ""),
            status=data.get("status", ""),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            duration_seconds=data.get("duration_seconds", 0.0),
            trigger_source=data.get("trigger_source", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "trigger_source": self.trigger_source,
        }
