"""Manage Artifact command handler.

Handles update and delete commands for artifacts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from syn_domain.contexts.artifacts.domain.commands.DeleteArtifactCommand import (
        DeleteArtifactCommand,
    )
    from syn_domain.contexts.artifacts.domain.commands.RecoverArtifactCreationTimeCommand import (
        RecoverArtifactCreationTimeCommand,
    )
    from syn_domain.contexts.artifacts.domain.commands.UpdateArtifactCommand import (
        UpdateArtifactCommand,
    )
    from syn_domain.repository import Repository

logger = logging.getLogger(__name__)


class ManageArtifactHandler:
    def __init__(self, repository: Repository[ArtifactAggregate]) -> None:
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

    async def recover_creation_time(self, command: RecoverArtifactCreationTimeCommand) -> bool:
        """Fill in a creation time for an artifact whose event carried none (#1215).

        Returns:
            True if a date was written, False if the artifact already had one.
            Both are successes -- the second is what a re-run looks like.

        Raises:
            KeyError: If artifact not found.
        """
        aggregate = await self._repository.get_by_id(command.aggregate_id)
        if aggregate is None:
            msg = f"Artifact not found: {command.aggregate_id}"
            raise KeyError(msg)
        if aggregate.created_at is not None:
            return False
        aggregate.recover_creation_time(command)
        await self._repository.save(aggregate)
        logger.info(
            f"Recovered created_at for artifact {command.aggregate_id} "
            f"from {command.recovered_from}"
        )
        return True
