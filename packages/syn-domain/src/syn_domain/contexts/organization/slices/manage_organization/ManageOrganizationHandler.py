"""Manage Organization command handler.

Handles update and delete commands for organizations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.organization.domain import HandlerResult

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.aggregate_organization.OrganizationAggregate import (
        OrganizationAggregate,
    )
    from syn_domain.contexts.organization.domain.commands.DeleteOrganizationCommand import (
        DeleteOrganizationCommand,
    )
    from syn_domain.contexts.organization.domain.commands.UpdateOrganizationCommand import (
        UpdateOrganizationCommand,
    )
    from syn_domain.repository import Repository

logger = logging.getLogger(__name__)


class ManageOrganizationHandler:
    def __init__(self, repository: Repository[OrganizationAggregate]) -> None:
        self._repository = repository

    async def update(self, command: UpdateOrganizationCommand) -> HandlerResult | None:
        aggregate = await self._repository.get_by_id(command.organization_id)
        if aggregate is None:
            logger.warning(f"Organization not found: {command.organization_id}")
            return None
        try:
            aggregate.update(command)
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))
        await self._repository.save(aggregate)
        logger.info(f"Updated organization {command.organization_id}")
        return HandlerResult(success=True)

    async def delete(self, command: DeleteOrganizationCommand) -> HandlerResult | None:
        aggregate = await self._repository.get_by_id(command.organization_id)
        if aggregate is None:
            logger.warning(f"Organization not found: {command.organization_id}")
            return None
        try:
            aggregate.delete(command)
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))
        await self._repository.save(aggregate)
        logger.info(f"Deleted organization {command.organization_id}")
        return HandlerResult(success=True)
