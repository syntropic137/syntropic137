"""Register Trigger command handler.

Handles the RegisterTriggerCommand by creating a new TriggerRuleAggregate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aef_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
    TriggerRuleAggregate,
)

if TYPE_CHECKING:
    from aef_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
        RegisterTriggerCommand,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        TriggerQueryStore,
    )

logger = logging.getLogger(__name__)


class RegisterTriggerHandler:
    def __init__(
        self,
        store: TriggerQueryStore,
        repository: Any | None = None,
    ) -> None:
        self._store = store
        self._repository = repository

    async def handle(self, command: RegisterTriggerCommand) -> TriggerRuleAggregate:
        aggregate = TriggerRuleAggregate()
        aggregate.register(command)

        # Persist via EventStoreRepository if available
        if self._repository is not None:
            await self._repository.save(aggregate)

        # Index in query store for fast lookups
        await self._store.index_trigger(
            trigger_id=aggregate.trigger_id,
            name=aggregate.name,
            event=aggregate.event,
            repository=aggregate.repository,
            workflow_id=aggregate.workflow_id,
            conditions=[
                {"field": c.field, "operator": c.operator, "value": c.value}
                for c in aggregate.conditions
            ],
            input_mapping=aggregate.input_mapping,
            config=aggregate.config,
            installation_id=aggregate.installation_id,
            created_by=aggregate.created_by,
            status=aggregate.status.value,
        )

        logger.info(
            f"Registered trigger '{aggregate.name}' ({aggregate.trigger_id}) "
            f"for {aggregate.repository} on {aggregate.event}"
        )
        return aggregate
