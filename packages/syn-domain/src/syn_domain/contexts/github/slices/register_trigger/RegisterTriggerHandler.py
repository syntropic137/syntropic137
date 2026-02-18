"""Register Trigger command handler.

Handles the RegisterTriggerCommand by creating a new TriggerRuleAggregate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
    TriggerRuleAggregate,
)

if TYPE_CHECKING:
    from syn_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
        RegisterTriggerCommand,
    )
    from syn_domain.contexts.github.slices.register_trigger.trigger_store import (
        TriggerQueryStore,
    )

logger = logging.getLogger(__name__)


class RegisterTriggerHandler:
    def __init__(
        self,
        store: TriggerQueryStore,
        repository: Any,
    ) -> None:
        self._store = store
        self._repository = repository

    async def handle(self, command: RegisterTriggerCommand) -> TriggerRuleAggregate:
        aggregate = TriggerRuleAggregate()
        aggregate.register(command)

        # Persist via EventStoreRepository
        await self._repository.save(aggregate)

        logger.info(
            f"Registered trigger '{aggregate.name}' ({aggregate.trigger_id}) "
            f"for {aggregate.repository} on {aggregate.event}"
        )
        return aggregate
