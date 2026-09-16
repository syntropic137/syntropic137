"""RecordOperation command handler - the write path for session operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.RecordOperationCommand import (
        RecordOperationCommand,
    )
    from syn_domain.repository import Repository


class RecordOperationHandler:
    """Handler for RecordOperation command.

    Appends one operation (message, tool lifecycle, thinking, error) to an
    existing session's stream. The aggregate owns every rule about whether
    the operation is admissible - notably that a session which has already
    completed cannot record more - so this handler loads, delegates and
    persists, and decides nothing itself.
    """

    def __init__(self, repository: Repository[AgentSessionAggregate]) -> None:
        """Initialize handler with repository."""
        self.repository = repository

    async def handle(self, command: RecordOperationCommand) -> None:
        """Handle operation recording.

        Args:
            command: RecordOperationCommand with operation details

        Raises:
            ValueError: If no session exists for ``command.aggregate_id``, or
                the aggregate rejects the operation.
        """
        session = await self.repository.get_by_id(command.aggregate_id)
        if session is None:
            msg = f"Cannot record operation: session {command.aggregate_id} not found"
            raise ValueError(msg)

        session.record_operation(command)
        await self.repository.save(session)
