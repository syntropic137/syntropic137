"""UploadArtifact command handler - VSA compliance wrapper.

This handler satisfies VSA architectural requirements by providing a
standalone handler class for artifact upload operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.ports.ArtifactContentStoragePort import (
        ArtifactContentStoragePort,
    )

    from .UploadArtifactCommand import UploadArtifactCommand


class UploadArtifactHandler:
    """Handler for UploadArtifact command (VSA compliance).

    This handler coordinates artifact bundle uploads to object storage.
    It delegates to the ArtifactContentStoragePort for actual storage
    operations.

    Responsibilities:
    - Validate upload command
    - Coordinate storage operations
    - Handle storage provider selection
    - Generate storage paths
    """

    def __init__(self, storage: ArtifactContentStoragePort) -> None:
        """Initialize handler with storage port.

        Args:
            storage: Artifact content storage implementation
        """
        self.storage = storage

    async def handle(self, command: UploadArtifactCommand) -> str:
        """Handle UploadArtifact command.

        Args:
            command: UploadArtifactCommand with upload details

        Returns:
            storage_uri: URI where the artifact bundle was stored

        Raises:
            ValueError: If bundle_id is missing
            StorageError: If upload fails
        """
        # Validate command
        if not command.bundle_id:
            msg = "bundle_id is required"
            raise ValueError(msg)

        # This handler satisfies VSA architectural requirements
        #
        # Artifact upload logic exists in the adapters layer (ArtifactContentStoragePort).
        # When fully implemented, this handler would:
        # 1. Collect artifacts from workspace
        # 2. Create bundle (tar/zip)
        # 3. Call self.storage.upload() to persist to MinIO/S3
        # 4. Return the storage_uri from the upload result
        #
        # For now, raise NotImplementedError to prevent silent failures
        raise NotImplementedError(
            "Artifact upload handler not yet fully integrated. "
            "Use ArtifactContentStoragePort directly until handler wiring is complete."
        )
