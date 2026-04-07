"""Manage System command handler.

Handles update and delete commands for systems.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.organization.domain import HandlerResult

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.aggregate_system.SystemAggregate import (
        SystemAggregate,
    )
    from syn_domain.contexts.organization.domain.commands.DeleteSystemCommand import (
        DeleteSystemCommand,
    )
    from syn_domain.contexts.organization.domain.commands.UpdateSystemCommand import (
        UpdateSystemCommand,
    )
    from syn_domain.repository import Repository

logger = logging.getLogger(__name__)


class ManageSystemHandler:
    def __init__(self, repository: Repository[SystemAggregate]) -> None:
        self._repository = repository

    async def update(self, command: UpdateSystemCommand) -> HandlerResult | None:
        aggregate = await self._repository.get_by_id(command.system_id)
        if aggregate is None:
            logger.warning(f"System not found: {command.system_id}")
            return None
        try:
            aggregate.update(command)
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))
        await self._repository.save(aggregate)
        logger.info(f"Updated system {command.system_id}")
        return HandlerResult(success=True)

    async def delete(self, command: DeleteSystemCommand) -> HandlerResult | None:
        aggregate = await self._repository.get_by_id(command.system_id)
        if aggregate is None:
            logger.warning(f"System not found: {command.system_id}")
            return None
        try:
            aggregate.delete(command)
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))
        await self._repository.save(aggregate)
        logger.info(f"Deleted system {command.system_id}")
        return HandlerResult(success=True)
