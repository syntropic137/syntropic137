"""Manage System command handler.

Handles update and delete commands for systems.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.commands.DeleteSystemCommand import (
        DeleteSystemCommand,
    )
    from syn_domain.contexts.organization.domain.commands.UpdateSystemCommand import (
        UpdateSystemCommand,
    )

logger = logging.getLogger(__name__)


class ManageSystemHandler:
    def __init__(self, repository: Any) -> None:
        self._repository = repository

    async def update(self, command: UpdateSystemCommand) -> object | None:
        aggregate = await self._repository.get_by_id(command.system_id)
        if aggregate is None:
            logger.warning(f"System not found: {command.system_id}")
            return None
        try:
            aggregate.update(command)
        except ValueError:
            return None
        await self._repository.save(aggregate)
        logger.info(f"Updated system {command.system_id}")
        return True

    async def delete(self, command: DeleteSystemCommand) -> object | None:
        aggregate = await self._repository.get_by_id(command.system_id)
        if aggregate is None:
            logger.warning(f"System not found: {command.system_id}")
            return None
        try:
            aggregate.delete(command)
        except ValueError:
            return None
        await self._repository.save(aggregate)
        logger.info(f"Deleted system {command.system_id}")
        return True
