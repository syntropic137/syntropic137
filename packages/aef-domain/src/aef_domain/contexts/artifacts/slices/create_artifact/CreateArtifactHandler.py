"""CreateArtifact command handler - VSA compliance wrapper.

This handler satisfies VSA architectural requirements by providing a
standalone handler class. The actual business logic lives in the
ArtifactAggregate command handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from event_sourcing import Repository

    from .CreateArtifactCommand import CreateArtifactCommand


class CreateArtifactHandler:
    """Handler for CreateArtifact command (VSA compliance).

    This is a thin wrapper that delegates to the ArtifactAggregate's
    command handler. VSA requires this standalone handler class for
    architectural consistency.

    The aggregate handles the actual business logic:
    - Validation (content required, no duplicate IDs)
    - Content hash computation
    - Event creation and application
    """

    def __init__(self, repository: Repository) -> None:
        """Initialize handler with repository.

        Args:
            repository: Event sourcing repository for ArtifactAggregate
        """
        self.repository = repository

    async def handle(self, command: CreateArtifactCommand) -> str:
        """Handle CreateArtifact command.

        Args:
            command: CreateArtifactCommand with artifact details

        Returns:
            artifact_id: ID of the created artifact

        Raises:
            ValueError: If artifact already exists or content is missing
        """
        from aef_domain.contexts.artifacts._shared.ArtifactAggregate import ArtifactAggregate

        # Create new aggregate
        artifact = ArtifactAggregate()

        # Delegate to aggregate's command handler
        artifact.create_artifact(command)

        # Save to repository
        await self.repository.save(artifact)

        # Return artifact ID
        return str(artifact.id)
