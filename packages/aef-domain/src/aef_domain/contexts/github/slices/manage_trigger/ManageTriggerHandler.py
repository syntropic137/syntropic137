"""Manage Trigger command handler.

Handles pause, resume, and delete commands for trigger rules.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aef_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
        TriggerRuleAggregate,
    )
    from aef_domain.contexts.github.domain.commands.DeleteTriggerCommand import (
        DeleteTriggerCommand,
    )
    from aef_domain.contexts.github.domain.commands.PauseTriggerCommand import (
        PauseTriggerCommand,
    )
    from aef_domain.contexts.github.domain.commands.ResumeTriggerCommand import (
        ResumeTriggerCommand,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        TriggerQueryStore,
    )

logger = logging.getLogger(__name__)


class ManageTriggerHandler:
    def __init__(
        self,
        store: TriggerQueryStore,
        repository: Any | None = None,
    ) -> None:
        self._store = store
        self._repository = repository

    async def _load_aggregate(self, trigger_id: str) -> TriggerRuleAggregate | None:
        """Load aggregate from repository, or return None if not found."""
        if self._repository is not None:
            return await self._repository.get_by_id(trigger_id)
        # Fallback: check query store for existence
        indexed = await self._store.get(trigger_id)
        if indexed is None:
            return None
        # Without a repository, we can't load the aggregate
        return None

    async def pause(self, command: PauseTriggerCommand) -> object | None:
        """Pause an active trigger."""
        # Check if trigger exists in query store
        indexed = await self._store.get(command.trigger_id)
        if indexed is None:
            logger.warning(f"Trigger not found: {command.trigger_id}")
            return None

        if indexed.status != "active":
            return None

        if self._repository is not None:
            aggregate = await self._repository.get_by_id(command.trigger_id)
            if aggregate is None:
                return None
            try:
                aggregate.pause(command)
            except ValueError:
                return None
            await self._repository.save(aggregate)
        await self._store.update_status(command.trigger_id, "paused")

        logger.info(f"Paused trigger {command.trigger_id}")
        return True  # Indicate success

    async def resume(self, command: ResumeTriggerCommand) -> object | None:
        """Resume a paused trigger."""
        indexed = await self._store.get(command.trigger_id)
        if indexed is None:
            logger.warning(f"Trigger not found: {command.trigger_id}")
            return None

        if indexed.status != "paused":
            return None

        if self._repository is not None:
            aggregate = await self._repository.get_by_id(command.trigger_id)
            if aggregate is None:
                return None
            try:
                aggregate.resume(command)
            except ValueError:
                return None
            await self._repository.save(aggregate)
        await self._store.update_status(command.trigger_id, "active")

        logger.info(f"Resumed trigger {command.trigger_id}")
        return True

    async def delete(self, command: DeleteTriggerCommand) -> object | None:
        """Soft-delete a trigger."""
        indexed = await self._store.get(command.trigger_id)
        if indexed is None:
            logger.warning(f"Trigger not found: {command.trigger_id}")
            return None

        if indexed.status == "deleted":
            return None

        if self._repository is not None:
            aggregate = await self._repository.get_by_id(command.trigger_id)
            if aggregate is None:
                return None
            try:
                aggregate.delete(command)
            except ValueError:
                return None
            await self._repository.save(aggregate)
        await self._store.update_status(command.trigger_id, "deleted")

        logger.info(f"Deleted trigger {command.trigger_id}")
        return True
