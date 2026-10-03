"""CompleteSession command handler - the write path for session completion."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.CompleteSessionCommand import (
        CompleteSessionCommand,
    )
    from syn_domain.repository import Repository


class CompleteSessionHandler:
    """Handler for CompleteSession command.

    Moves a running session to its terminal status. The aggregate decides
    what that status is and refuses a session that already reached one, so
    this handler loads, delegates and persists, and decides nothing itself.
    """

    def __init__(self, repository: Repository[AgentSessionAggregate]) -> None:
        """Initialize handler with repository."""
        self.repository = repository

    async def handle(self, command: CompleteSessionCommand) -> None:
        """Handle session completion.

        Args:
            command: CompleteSessionCommand with completion details

        Raises:
            ValueError: If no session exists for ``command.aggregate_id``, or
                the aggregate rejects the completion.
        """
        session = await self.repository.get_by_id(command.aggregate_id)
        if session is None:
            msg = f"Cannot complete session: session {command.aggregate_id} not found"
            raise ValueError(msg)

        session.complete_session(command)
        await self.repository.save(session)
