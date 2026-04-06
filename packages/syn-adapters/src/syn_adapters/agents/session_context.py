"""Session context for agent instrumentation.

Provides context information that is attached to all hook events
emitted by an instrumented agent.

Example:
    context = SessionContext(
        session_id="session-123",
        workflow_id="workflow-456",
        phase_id="research",
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SessionContext:
    """Context for an agent session.

    This context is attached to all hook events emitted during
    the session, enabling correlation of events across a workflow.

    Attributes:
        session_id: Unique identifier for this agent session.
        workflow_id: Optional workflow this session belongs to.
        phase_id: Optional phase within the workflow.
        milestone_id: Optional milestone within the phase.
        metadata: Additional context metadata.
    """

    session_id: str
    workflow_id: str | None = None
    phase_id: str | None = None
    milestone_id: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for event data.

        Returns:
            Dictionary with non-None values.
        """
        data: dict[str, Any] = {"session_id": self.session_id}
        if self.workflow_id is not None:
            data["workflow_id"] = self.workflow_id
        if self.phase_id is not None:
            data["phase_id"] = self.phase_id
        if self.milestone_id is not None:
            data["milestone_id"] = self.milestone_id
        if self.metadata is not None:
            data["metadata"] = self.metadata
        return data

    def with_metadata(self, **kwargs: Any) -> SessionContext:  # noqa: ANN401
        """Create new context with additional metadata.

        Args:
            **kwargs: Metadata key-value pairs.

        Returns:
            New SessionContext with merged metadata.
        """
        new_metadata = {**(self.metadata or {}), **kwargs}
        return SessionContext(
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            phase_id=self.phase_id,
            milestone_id=self.milestone_id,
            metadata=new_metadata,
        )
