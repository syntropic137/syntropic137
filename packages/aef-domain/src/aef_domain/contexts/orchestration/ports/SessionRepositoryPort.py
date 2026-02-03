"""Port interface for AgentSessionAggregate repository."""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from aef_domain.contexts.agent_sessions._shared import AgentSessionAggregate


class SessionRepositoryPort(Protocol):
    """Repository port for AgentSession aggregates.

    Tracks agent sessions for observability and token attribution.
    Each phase execution creates a session to track:
    - Token usage (input/output tokens)
    - Operation counts
    - Success/failure status
    - Duration
    """

    async def save(self, aggregate: "AgentSessionAggregate") -> None:
        """Save the session aggregate.

        Persists session events:
        - SessionStarted
        - OperationRecorded (for each message/operation)
        - SessionCompleted

        Args:
            aggregate: The agent session aggregate to persist.
        """
        ...

    async def get_by_id(self, session_id: str) -> "AgentSessionAggregate | None":
        """Retrieve session aggregate by ID.

        Args:
            session_id: The unique identifier of the session.

        Returns:
            AgentSessionAggregate if found, None otherwise.
        """
        ...

    async def exists(self, session_id: str) -> bool:
        """Check if a session exists.

        Args:
            session_id: The unique identifier of the session.

        Returns:
            True if session exists, False otherwise.
        """
        ...
