"""StartSession command handler - VSA compliance wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from event_sourcing import Repository

    from .StartSessionCommand import StartSessionCommand


class StartSessionHandler:
    """Handler for StartSession command (VSA compliance).

    Delegates to AgentSessionAggregate for session lifecycle management.
    """

    def __init__(self, repository: Repository) -> None:
        """Initialize handler with repository."""
        self.repository = repository

    async def handle(self, command: StartSessionCommand) -> str:
        """Handle session start.

        Args:
            command: StartSessionCommand with session configuration

        Returns:
            session_id: ID of the started session
        """
        from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
            AgentSessionAggregate,
        )

        # Create new session aggregate
        session = AgentSessionAggregate()

        # Delegate to aggregate's command handler
        session.start_session(command)

        # Save to repository
        await self.repository.save(session)

        # Return session ID
        return str(session.id)
