"""RecordSandboxSpool command handler - the write path for the sandbox spool route."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.RecordSandboxSpoolCommand import (
        RecordSandboxSpoolCommand,
    )
    from syn_domain.repository import Repository


class RecordSandboxSpoolHandler:
    """Loads the session, records where its sandbox spool lives, saves.

    The aggregate makes a repeat for the same sandbox a no-op, so a
    re-dispatch after a crash costs one load and save.
    """

    def __init__(self, repository: Repository[AgentSessionAggregate]) -> None:
        self.repository = repository

    async def handle(self, command: RecordSandboxSpoolCommand) -> None:
        """Raises ValueError if no session exists for ``command.aggregate_id``."""
        session = await self.repository.get_by_id(command.aggregate_id)
        if session is None:
            msg = f"Cannot record a sandbox spool: session {command.aggregate_id} not found"
            raise ValueError(msg)
        session.record_sandbox_spool(command)
        await self.repository.save(session)
