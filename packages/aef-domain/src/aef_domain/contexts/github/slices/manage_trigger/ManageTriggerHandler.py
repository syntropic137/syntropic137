"""Manage Trigger command handler.

Handles pause, resume, and delete commands for trigger rules.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aef_domain.contexts.github.domain.commands.DeleteTriggerCommand import (
        DeleteTriggerCommand,
    )
    from aef_domain.contexts.github.domain.commands.PauseTriggerCommand import (
        PauseTriggerCommand,
    )
    from aef_domain.contexts.github.domain.commands.ResumeTriggerCommand import (
        ResumeTriggerCommand,
    )
    from aef_domain.contexts.github.domain.events.TriggerDeletedEvent import (
        TriggerDeletedEvent,
    )
    from aef_domain.contexts.github.domain.events.TriggerPausedEvent import (
        TriggerPausedEvent,
    )
    from aef_domain.contexts.github.domain.events.TriggerResumedEvent import (
        TriggerResumedEvent,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        TriggerStore,
    )

logger = logging.getLogger(__name__)


class ManageTriggerHandler:
    """Handler for trigger lifecycle commands (pause/resume/delete)."""

    def __init__(self, store: TriggerStore) -> None:
        """Initialize the handler.

        Args:
            store: Trigger storage backend.
        """
        self._store = store

    async def pause(self, command: PauseTriggerCommand) -> TriggerPausedEvent | None:
        """Pause a trigger rule.

        Args:
            command: The PauseTriggerCommand.

        Returns:
            TriggerPausedEvent if trigger was paused, None if not found or invalid state.
        """
        aggregate = await self._store.get(command.trigger_id)
        if aggregate is None:
            logger.warning(f"Trigger not found: {command.trigger_id}")
            return None

        event = aggregate.pause(paused_by=command.paused_by, reason=command.reason)
        if event:
            await self._store.save(aggregate)
            logger.info(f"Paused trigger {command.trigger_id}")

        return event

    async def resume(self, command: ResumeTriggerCommand) -> TriggerResumedEvent | None:
        """Resume a paused trigger rule.

        Args:
            command: The ResumeTriggerCommand.

        Returns:
            TriggerResumedEvent if trigger was resumed, None if not found or invalid state.
        """
        aggregate = await self._store.get(command.trigger_id)
        if aggregate is None:
            logger.warning(f"Trigger not found: {command.trigger_id}")
            return None

        event = aggregate.resume(resumed_by=command.resumed_by)
        if event:
            await self._store.save(aggregate)
            logger.info(f"Resumed trigger {command.trigger_id}")

        return event

    async def delete(self, command: DeleteTriggerCommand) -> TriggerDeletedEvent | None:
        """Delete a trigger rule.

        Args:
            command: The DeleteTriggerCommand.

        Returns:
            TriggerDeletedEvent if trigger was deleted, None if not found or invalid state.
        """
        aggregate = await self._store.get(command.trigger_id)
        if aggregate is None:
            logger.warning(f"Trigger not found: {command.trigger_id}")
            return None

        event = aggregate.delete(deleted_by=command.deleted_by)
        if event:
            await self._store.save(aggregate)
            logger.info(f"Deleted trigger {command.trigger_id}")

        return event
