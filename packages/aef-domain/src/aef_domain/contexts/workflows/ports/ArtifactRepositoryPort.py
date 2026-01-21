"""Port interface for ArtifactAggregate repository."""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from aef_domain.contexts.artifacts._shared import ArtifactAggregate


class ArtifactRepositoryPort(Protocol):
    """Repository port for Artifact aggregates.

    Manages phase output artifacts (markdown, code, reports, etc.).
    Artifacts are created after each phase execution and can be:
    - Stored in object storage (MinIO/S3) via ArtifactContentStoragePort
    - Queried for injection into subsequent phase prompts
    - Retrieved for display in dashboard/CLI
    """

    async def save(self, aggregate: "ArtifactAggregate") -> None:
        """Save the artifact aggregate.

        Persists artifact events:
        - ArtifactCreated (with content and metadata)

        Args:
            aggregate: The artifact aggregate to persist.
        """
        ...

    async def get_by_id(self, artifact_id: str) -> "ArtifactAggregate | None":
        """Retrieve artifact by ID.

        Args:
            artifact_id: The unique identifier of the artifact.

        Returns:
            ArtifactAggregate if found, None otherwise.
        """
        ...

    async def exists(self, artifact_id: str) -> bool:
        """Check if an artifact exists.

        Args:
            artifact_id: The unique identifier of the artifact.

        Returns:
            True if artifact exists, False otherwise.
        """
        ...


