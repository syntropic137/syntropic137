"""Create Organization command handler."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.organization.domain.aggregate_organization.OrganizationAggregate import (
    OrganizationAggregate,
)

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.commands.CreateOrganizationCommand import (
        CreateOrganizationCommand,
    )
    from syn_domain.repository import Repository

logger = logging.getLogger(__name__)


class CreateOrganizationHandler:
    def __init__(self, repository: Repository[OrganizationAggregate]) -> None:
        self._repository = repository

    async def handle(self, command: CreateOrganizationCommand) -> OrganizationAggregate:
        aggregate = OrganizationAggregate()
        aggregate.create(command)
        await self._repository.save(aggregate)
        logger.info(f"Created organization '{aggregate.name}' ({aggregate.organization_id})")
        return aggregate
