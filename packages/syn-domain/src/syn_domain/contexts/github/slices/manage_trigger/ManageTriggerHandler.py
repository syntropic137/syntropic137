"""Manage Trigger command handler.

Handles pause, resume, and delete commands for trigger rules.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_domain.contexts.github._shared.trigger_query_store import (
        TriggerQueryStore,
    )
    from syn_domain.contexts.github.domain.commands.DeleteTriggerCommand import (
        DeleteTriggerCommand,
    )
    from syn_domain.contexts.github.domain.commands.PauseTriggerCommand import (
        PauseTriggerCommand,
    )
    from syn_domain.contexts.github.domain.commands.ResumeTriggerCommand import (
        ResumeTriggerCommand,
    )

logger = logging.getLogger(__name__)


class ManageTriggerHandler:
    def __init__(
        self,
        store: TriggerQueryStore,
        repository: Any,  # noqa: ANN401
    ) -> None:
        self._store = store
        self._repository = repository

    async def pause(self, command: PauseTriggerCommand) -> object | None:
        """Pause an active trigger."""
        indexed = await self._store.get(command.trigger_id)
        if indexed is None:
            logger.warning(f"Trigger not found: {command.trigger_id}")
            return None

        if indexed.status != "active":
            return None

        aggregate = await self._repository.get_by_id(command.trigger_id)
        if aggregate is None:
            return None
        try:
            aggregate.pause(command)
        except ValueError:
            return None
        await self._repository.save(aggregate)

        logger.info(f"Paused trigger {command.trigger_id}")
        return True

    async def resume(self, command: ResumeTriggerCommand) -> object | None:
        """Resume a paused trigger."""
        indexed = await self._store.get(command.trigger_id)
        if indexed is None:
            logger.warning(f"Trigger not found: {command.trigger_id}")
            return None

        if indexed.status != "paused":
            return None

        aggregate = await self._repository.get_by_id(command.trigger_id)
        if aggregate is None:
            return None
        try:
            aggregate.resume(command)
        except ValueError:
            return None
        await self._repository.save(aggregate)

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

        aggregate = await self._repository.get_by_id(command.trigger_id)
        if aggregate is None:
            return None
        try:
            aggregate.delete(command)
        except ValueError:
            return None
        await self._repository.save(aggregate)

        logger.info(f"Deleted trigger {command.trigger_id}")
        return True
