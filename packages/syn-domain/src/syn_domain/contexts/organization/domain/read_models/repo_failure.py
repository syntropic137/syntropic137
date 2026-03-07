"""Repo failure read model.

Failed execution with error context and conversation tail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RepoFailure:
    """A failed execution for a repository.

    Attributes:
        execution_id: Workflow execution ID.
        workflow_id: Workflow template ID.
        workflow_name: Human-readable workflow name.
        failed_at: ISO timestamp of failure.
        error_message: Primary error message.
        error_type: Error classification (timeout, crash, permission, etc.).
        phase_name: Phase that failed (empty if pre-phase failure).
        conversation_tail: Last N lines of agent conversation for debugging.
    """

    execution_id: str
    workflow_id: str = ""
    workflow_name: str = ""
    failed_at: str = ""
    error_message: str = ""
    error_type: str = ""
    phase_name: str = ""
    conversation_tail: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoFailure:
        """Create from dictionary data."""
        return cls(
            execution_id=data.get("execution_id", ""),
            workflow_id=data.get("workflow_id", ""),
            workflow_name=data.get("workflow_name", ""),
            failed_at=data.get("failed_at", ""),
            error_message=data.get("error_message", ""),
            error_type=data.get("error_type", ""),
            phase_name=data.get("phase_name", ""),
            conversation_tail=data.get("conversation_tail", []),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "failed_at": self.failed_at,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "phase_name": self.phase_name,
            "conversation_tail": list(self.conversation_tail),
        }
