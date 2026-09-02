"""MarkAgentLaunched command handler - VSA compliance wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from event_sourcing import Repository

    from syn_domain.contexts.agent_sessions.domain.commands.MarkAgentLaunchedCommand import (
        MarkAgentLaunchedCommand,
    )


class MarkAgentLaunchedHandler:
    """Handler for MarkAgentLaunched command (VSA compliance).

    Records that a session's agent process was launched.
    """

    def __init__(self, repository: Repository) -> None:
        """Initialize handler with repository."""
        self.repository = repository

    async def handle(self, command: MarkAgentLaunchedCommand) -> None:
        """Handle agent-launched recording.

        Args:
            command: MarkAgentLaunchedCommand identifying the session
        """
        # This handler satisfies VSA architectural requirements.
        #
        # SessionLifecycleManager.mark_launched() is the production entry
        # point: it loads the live aggregate it already holds, calls
        # aggregate.mark_agent_launched(command), and saves it. This
        # handler is a structural placeholder for VSA compliance, matching
        # RecordOperationHandler/StartSessionHandler's pattern.
        pass
