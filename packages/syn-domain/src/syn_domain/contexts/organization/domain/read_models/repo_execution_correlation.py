"""Repo-execution correlation read model.

Maps repositories to workflow executions (many-to-many).
Built from TriggerFired and WorkflowExecutionStarted events
rather than requiring repo_id on execution events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RepoExecutionCorrelation:
    """Correlation between a repository and a workflow execution.

    Attributes:
        repo_full_name: Full repository name (e.g. "owner/repo").
        repo_id: Linked RepoAggregate ID if the repo is registered, else None.
        execution_id: Workflow execution ID.
        workflow_id: Workflow template ID.
        correlation_source: How the correlation was established
            ("trigger", "template", or "manual").
        correlated_at: When the correlation was created.
    """

    repo_full_name: str
    repo_id: str | None
    execution_id: str
    workflow_id: str
    correlation_source: str
    correlated_at: datetime | str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoExecutionCorrelation:
        """Create from dictionary data."""
        return cls(
            repo_full_name=data.get("repo_full_name", ""),
            repo_id=data.get("repo_id"),
            execution_id=data.get("execution_id", ""),
            workflow_id=data.get("workflow_id", ""),
            correlation_source=data.get("correlation_source", ""),
            correlated_at=data.get("correlated_at", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        correlated_at = self.correlated_at
        if isinstance(correlated_at, datetime):
            correlated_at = correlated_at.isoformat()
        return {
            "repo_full_name": self.repo_full_name,
            "repo_id": self.repo_id,
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "correlation_source": self.correlation_source,
            "correlated_at": correlated_at,
        }
