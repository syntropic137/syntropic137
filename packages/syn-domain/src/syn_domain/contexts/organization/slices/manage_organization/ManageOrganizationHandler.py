"""Manage Organization command handler.

Handles update and delete commands for organizations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.commands.DeleteOrganizationCommand import (
        DeleteOrganizationCommand,
    )
    from syn_domain.contexts.organization.domain.commands.UpdateOrganizationCommand import (
        UpdateOrganizationCommand,
    )

logger = logging.getLogger(__name__)


class ManageOrganizationHandler:
    def __init__(self, repository: Any) -> None:
        self._repository = repository

    async def update(self, command: UpdateOrganizationCommand) -> object | None:
        aggregate = await self._repository.get_by_id(command.organization_id)
        if aggregate is None:
            logger.warning(f"Organization not found: {command.organization_id}")
            return None
        try:
            aggregate.update(command)
        except ValueError:
            return None
        await self._repository.save(aggregate)
        logger.info(f"Updated organization {command.organization_id}")
        return True

    async def delete(self, command: DeleteOrganizationCommand) -> object | None:
        aggregate = await self._repository.get_by_id(command.organization_id)
        if aggregate is None:
            logger.warning(f"Organization not found: {command.organization_id}")
            return None
        try:
            aggregate.delete(command)
        except ValueError:
            return None
        await self._repository.save(aggregate)
        logger.info(f"Deleted organization {command.organization_id}")
        return True
