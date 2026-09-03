"""Protocol for conversation storage.

Defines the interface for storing full conversation logs.
See ADR-035: Agent Output Data Model and Storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003
from typing import Any, Protocol, runtime_checkable


@dataclass
class SessionContext:
    """Context for session storage.

    Contains metadata about the session for indexing and correlation.
    """

    # Correlation IDs
    execution_id: str | None = None
    phase_id: str | None = None
    workflow_id: str | None = None

    # Agent metadata
    model: str | None = None

    # Metrics (from SessionSummary)
    event_count: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # Timestamps
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Outcome
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "execution_id": self.execution_id,
            "phase_id": self.phase_id,
            "workflow_id": self.workflow_id,
            "model": self.model,
            "event_count": self.event_count,
            "tool_counts": self.tool_counts,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "success": self.success,
        }


class ConversationStoreUnavailable(RuntimeError):
    """The store could not answer, so nothing was learned about the session.

    Distinct from every "nothing here" answer this port can give - ``None``
    for a log, ``None`` for metadata, ``[]`` for a listing. Those are facts
    about a session, and callers state them to users: no log was ever
    recorded, this session has no metadata, this execution ran nothing. A
    store that is down, unreachable or unconfigured supports none of those
    statements, so it must not be able to produce them (#1065).
    """


@runtime_checkable
class ConversationStoragePort(Protocol):
    """Port for storing full conversation logs.

    Implementations store JSONL conversation files in object storage
    and maintain an index in the database for querying.
    """

    async def store_session(
        self,
        session_id: str,
        lines: list[str],
        context: SessionContext,
    ) -> str:
        """Store a session's conversation log.

        Args:
            session_id: Unique session identifier
            lines: List of JSONL lines (full conversation)
            context: Session context for indexing

        Returns:
            Object key where conversation was stored
        """
        ...

    async def retrieve_session(
        self,
        session_id: str,
    ) -> list[str] | None:
        """Retrieve a session's conversation log.

        Args:
            session_id: Session identifier

        Returns:
            List of JSONL lines, or None if the object genuinely does not exist.

        Raises:
            Exception: if the store could not answer. ``None`` means "no log
                was ever stored for this session" and callers state that to
                users; an outage must not be able to produce it (#1065).
        """
        ...

    async def get_session_metadata(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Get session metadata from index.

        Args:
            session_id: Session identifier

        Returns:
            Session metadata dict, or None if the index genuinely holds no
            row for this session.

        Raises:
            ConversationStoreUnavailable: if the index could not be queried.
                ``None`` is reported to users as "no metadata for this
                session", which an outage does not establish (#1065).
        """
        ...

    async def list_sessions_for_execution(
        self,
        execution_id: str,
    ) -> list[str]:
        """Get session IDs for an execution.

        Args:
            execution_id: Execution identifier

        Returns:
            Session IDs for the execution; empty when it genuinely has none.

        Raises:
            ConversationStoreUnavailable: if the index could not be queried.
                An empty list says the execution recorded no sessions, and an
                outage cannot support that either (#1065).
        """
        ...
