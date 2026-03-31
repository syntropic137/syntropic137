"""Manage Artifact command handler.

Handles update and delete commands for artifacts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.commands.DeleteArtifactCommand import (
        DeleteArtifactCommand,
    )
    from syn_domain.contexts.artifacts.domain.commands.UpdateArtifactCommand import (
        UpdateArtifactCommand,
    )

logger = logging.getLogger(__name__)


class ManageArtifactHandler:
    def __init__(self, repository: Any) -> None:
        self._repository = repository

    async def update(self, command: UpdateArtifactCommand) -> bool:
        """Update artifact metadata.

        Returns:
            True on success.

        Raises:
            KeyError: If artifact not found.
            ValueError: If domain rule violated (e.g. artifact is deleted).
        """
        aggregate = await self._repository.get_by_id(command.aggregate_id)
        if aggregate is None:
            msg = f"Artifact not found: {command.aggregate_id}"
            raise KeyError(msg)
        aggregate.update_artifact(command)
        await self._repository.save(aggregate)
        logger.info(f"Updated artifact {command.aggregate_id}")
        return True

    async def delete(self, command: DeleteArtifactCommand) -> bool:
        """Soft-delete an artifact.

        Returns:
            True on success.

        Raises:
            KeyError: If artifact not found.
            ValueError: If domain rule violated (e.g. already deleted).
        """
        aggregate = await self._repository.get_by_id(command.aggregate_id)
        if aggregate is None:
            msg = f"Artifact not found: {command.aggregate_id}"
            raise KeyError(msg)
        aggregate.delete_artifact(command)
        await self._repository.save(aggregate)
        logger.info(f"Deleted artifact {command.aggregate_id}")
        return True
