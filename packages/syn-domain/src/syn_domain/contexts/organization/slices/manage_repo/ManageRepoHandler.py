"""Manage Repo command handler.

Handles assign and unassign commands for repos.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.organization.domain import HandlerResult

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.commands.AssignRepoToSystemCommand import (
        AssignRepoToSystemCommand,
    )
    from syn_domain.contexts.organization.domain.commands.DeregisterRepoCommand import (
        DeregisterRepoCommand,
    )
    from syn_domain.contexts.organization.domain.commands.UnassignRepoFromSystemCommand import (
        UnassignRepoFromSystemCommand,
    )
    from syn_domain.contexts.organization.domain.commands.UpdateRepoCommand import (
        UpdateRepoCommand,
    )

logger = logging.getLogger(__name__)


class ManageRepoHandler:
    def __init__(self, repository: Any) -> None:
        self._repository = repository

    async def assign_to_system(self, command: AssignRepoToSystemCommand) -> HandlerResult | None:
        aggregate = await self._repository.get_by_id(command.repo_id)
        if aggregate is None:
            logger.warning(f"Repo not found: {command.repo_id}")
            return None
        try:
            aggregate.assign_to_system(command)
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))
        await self._repository.save(aggregate)
        logger.info(f"Assigned repo {command.repo_id} to system {command.system_id}")
        return HandlerResult(success=True)

    async def unassign_from_system(
        self, command: UnassignRepoFromSystemCommand
    ) -> HandlerResult | None:
        aggregate = await self._repository.get_by_id(command.repo_id)
        if aggregate is None:
            logger.warning(f"Repo not found: {command.repo_id}")
            return None
        try:
            aggregate.unassign_from_system(command)
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))
        await self._repository.save(aggregate)
        logger.info(f"Unassigned repo {command.repo_id} from system")
        return HandlerResult(success=True)

    async def update(self, command: UpdateRepoCommand) -> HandlerResult | None:
        aggregate = await self._repository.get_by_id(command.repo_id)
        if aggregate is None:
            logger.warning(f"Repo not found: {command.repo_id}")
            return None
        try:
            aggregate.update(command)
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))
        await self._repository.save(aggregate)
        logger.info(f"Updated repo {command.repo_id}")
        return HandlerResult(success=True)

    async def deregister(self, command: DeregisterRepoCommand) -> HandlerResult | None:
        aggregate = await self._repository.get_by_id(command.repo_id)
        if aggregate is None:
            logger.warning(f"Repo not found: {command.repo_id}")
            return None
        try:
            aggregate.deregister(command)
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))
        await self._repository.save(aggregate)
        logger.info(f"Deregistered repo {command.repo_id}")
        return HandlerResult(success=True)
