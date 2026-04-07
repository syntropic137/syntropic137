"""Create System command handler."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.organization.domain.aggregate_system.SystemAggregate import (
    SystemAggregate,
)

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.commands.CreateSystemCommand import (
        CreateSystemCommand,
    )
    from syn_domain.repository import Repository

logger = logging.getLogger(__name__)


class CreateSystemHandler:
    def __init__(self, repository: Repository[SystemAggregate]) -> None:
        self._repository = repository

    async def handle(self, command: CreateSystemCommand) -> SystemAggregate:
        aggregate = SystemAggregate()
        aggregate.create(command)
        await self._repository.save(aggregate)
        logger.info(f"Created system '{aggregate.name}' ({aggregate.system_id})")
        return aggregate
