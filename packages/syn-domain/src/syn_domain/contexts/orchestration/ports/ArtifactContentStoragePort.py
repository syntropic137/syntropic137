"""Port interface for artifact content storage in object storage.

Per ADR-012 (Artifact Storage), artifact content is stored in:
1. Object storage (MinIO/S3) - for large content
2. Event store - for metadata and smaller content

This port handles the object storage layer.
"""

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.ArtifactValueObjects import (
        ArtifactUploadResult,
    )


class ArtifactContentStoragePort(Protocol):
    """Port for storing artifact content in object storage (MinIO/S3).

    Per ADR-012, large artifacts are stored in object storage rather than
    inline in events. This provides:
    - Efficient storage for large files
    - Direct download URLs
    - Versioning support
    - Cheaper storage costs
    """

    async def upload(
        self,
        artifact_id: str,
        content: bytes,
        workflow_id: str,
        phase_id: str,
        execution_id: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
    ) -> "ArtifactUploadResult":
        """Upload artifact content to object storage.

        Args:
            artifact_id: Unique identifier for the artifact.
            content: Binary content to upload.
            workflow_id: Parent workflow ID (for organization).
            phase_id: Phase that created this artifact.
            execution_id: Execution run ID.
            content_type: MIME type of the content.
            metadata: Optional metadata to store with the object.

        Returns once a read of ``storage_uri`` returns these exact bytes, never
        merely once the backend accepted the write and never on the strength of
        a size that matches. ``ArtifactCreatedEvent`` carries that URI, so a
        consumer reacting to the event fetches immediately; an implementation
        that returns early hands out a pointer to bytes that are not there, or
        to a previous object of the same length (#700). An implementation that
        cannot confirm readability must raise rather than return a URI it
        cannot stand behind.

        Readability, not durability - surviving the loss of a disk or a node is
        a property of the deployment and is not what a return from here means.

        Returns:
            ArtifactUploadResult with storage_uri and size_bytes.

        Example:
            result = await storage.upload(
                artifact_id="artifact-123",
                content=markdown_content.encode("utf-8"),
                workflow_id="workflow-456",
                phase_id="phase-789",
                execution_id="exec-abc",
                content_type="text/markdown",
                metadata={"title": "Research Summary"},
            )
            # result.storage_uri = "s3://bucket/artifacts/artifact-123.md"
            # result.size_bytes = 15234
        """
        ...

    async def download(self, artifact_id: str) -> bytes:
        """Download artifact content from object storage.

        Args:
            artifact_id: Unique identifier for the artifact.

        Returns:
            Binary content of the artifact.

        Raises:
            ArtifactNotFoundError: If artifact doesn't exist.
        """
        ...

    async def get_download_url(self, artifact_id: str, expires_in: int = 3600) -> str:
        """Get a presigned URL for downloading an artifact.

        Args:
            artifact_id: Unique identifier for the artifact.
            expires_in: URL expiration time in seconds (default: 1 hour).

        Returns:
            Presigned URL for direct download.
        """
        ...
