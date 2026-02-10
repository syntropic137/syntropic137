"""Register Trigger command handler.

Handles the RegisterTriggerCommand by creating a new TriggerRuleAggregate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aef_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
    TriggerRuleAggregate,
)

if TYPE_CHECKING:
    from aef_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
        RegisterTriggerCommand,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        TriggerStore,
    )

logger = logging.getLogger(__name__)


class RegisterTriggerHandler:
    """Handler for RegisterTriggerCommand.

    Creates a new TriggerRuleAggregate and persists it.
    """

    def __init__(self, store: TriggerStore) -> None:
        """Initialize the handler.

        Args:
            store: Trigger storage backend.
        """
        self._store = store

    async def handle(self, command: RegisterTriggerCommand) -> TriggerRuleAggregate:
        """Handle the register trigger command.

        Args:
            command: The RegisterTriggerCommand.

        Returns:
            The created TriggerRuleAggregate.
        """
        aggregate = TriggerRuleAggregate.register(command)

        await self._store.save(aggregate)

        logger.info(
            f"Registered trigger '{aggregate.name}' ({aggregate.trigger_id}) "
            f"for {aggregate.repository} on {aggregate.event}"
        )

        return aggregate
