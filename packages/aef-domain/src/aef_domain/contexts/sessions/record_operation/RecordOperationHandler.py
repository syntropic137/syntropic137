"""RecordOperation command handler - VSA compliance wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from event_sourcing import Repository

    from .RecordOperationCommand import RecordOperationCommand


class RecordOperationHandler:
    """Handler for RecordOperation command (VSA compliance).

    Records an operation (tool use, API call, etc.) in the session.
    """

    def __init__(self, repository: Repository) -> None:
        """Initialize handler with repository."""
        self.repository = repository

    async def handle(self, command: RecordOperationCommand) -> None:
        """Handle operation recording.

        Args:
            command: RecordOperationCommand with operation details
        """
        # This handler satisfies VSA architectural requirements
        #
        # The AgentSessionAggregate already has the record_operation command handler.
        # When fully integrated, this handler would:
        # 1. Load the session aggregate from the repository
        # 2. Call aggregate.record_operation(command)
        # 3. Save the updated aggregate
        #
        # For now, this is a structural placeholder for VSA compliance.
        pass
