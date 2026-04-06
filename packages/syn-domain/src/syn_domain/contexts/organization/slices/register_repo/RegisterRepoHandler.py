"""Register Repo command handler."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.organization.domain.aggregate_repo.RepoAggregate import (
    RepoAggregate,
)

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.commands.RegisterRepoCommand import (
        RegisterRepoCommand,
    )

logger = logging.getLogger(__name__)


class RegisterRepoHandler:
    def __init__(self, repository: Any) -> None:  # noqa: ANN401
        self._repository = repository

    async def handle(self, command: RegisterRepoCommand) -> RepoAggregate:
        aggregate = RepoAggregate()
        aggregate.register(command)
        await self._repository.save(aggregate)
        logger.info(f"Registered repo '{aggregate.full_name}' ({aggregate.repo_id})")
        return aggregate
