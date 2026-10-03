"""MarkAgentLaunched command handler - the write path for the launch fact."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.MarkAgentLaunchedCommand import (
        MarkAgentLaunchedCommand,
    )
    from syn_domain.repository import Repository


class MarkAgentLaunchedHandler:
    """Handler for MarkAgentLaunched command.

    Records that a session's agent process demonstrably existed. The
    aggregate makes this idempotent, so a defensive re-dispatch after a
    crash costs an extra load and save and changes nothing else.
    """

    def __init__(self, repository: Repository[AgentSessionAggregate]) -> None:
        """Initialize handler with repository."""
        self.repository = repository

    async def handle(self, command: MarkAgentLaunchedCommand) -> None:
        """Handle agent-launched recording.

        Args:
            command: MarkAgentLaunchedCommand identifying the session

        Raises:
            ValueError: If no session exists for ``command.aggregate_id``.
        """
        session = await self.repository.get_by_id(command.aggregate_id)
        if session is None:
            msg = f"Cannot mark agent launched: session {command.aggregate_id} not found"
            raise ValueError(msg)

        session.mark_agent_launched(command)
        await self.repository.save(session)
