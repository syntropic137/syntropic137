"""Artifact aggregate root - stores phase outputs."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from aef_domain.contexts.artifacts._shared.value_objects import (
    ArtifactType,
    ContentType,
    compute_content_hash,
)

if TYPE_CHECKING:
    from aef_domain.contexts.artifacts.create_artifact.ArtifactCreatedEvent import (
        ArtifactCreatedEvent,
    )
    from aef_domain.contexts.artifacts.create_artifact.CreateArtifactCommand import (
        CreateArtifactCommand,
    )


@aggregate("Artifact")
class ArtifactAggregate(AggregateRoot["ArtifactCreatedEvent"]):
    """Artifact aggregate root.

    Stores outputs produced by workflow phases. Each artifact has:
    - Context (workflow, phase, session)
    - Content and metadata
    - Lineage (derived_from parent artifacts)

    Uses event sourcing to track creation.
    """

    # Type hint for decorator-set attribute
    _aggregate_type: str

    def __init__(self) -> None:
        super().__init__()
        self._workflow_id: str | None = None
        self._phase_id: str | None = None
        self._execution_id: str | None = None  # Links to specific execution run
        self._session_id: str | None = None
        self._artifact_type: ArtifactType | None = None
        self._content_type: ContentType = ContentType.TEXT_MARKDOWN
        self._content: str = ""
        self._content_hash: str | None = None
        self._size_bytes: int = 0
        self._title: str | None = None
        self._storage_uri: str | None = None  # Object storage reference (ADR-012)
        self._is_primary_deliverable: bool = True
        self._derived_from: list[str] = []
        self._metadata: dict[str, str | int | float | bool | None] = {}

    def get_aggregate_type(self) -> str:
        """Return aggregate type name."""
        return self._aggregate_type

    # =========================================================================
    # PROPERTIES
    # =========================================================================

    @property
    def workflow_id(self) -> str | None:
        """Get the workflow this artifact belongs to."""
        return self._workflow_id

    @property
    def phase_id(self) -> str | None:
        """Get the phase that produced this artifact."""
        return self._phase_id

    @property
    def execution_id(self) -> str | None:
        """Get the execution run that produced this artifact."""
        return self._execution_id

    @property
    def session_id(self) -> str | None:
        """Get the session that produced this artifact."""
        return self._session_id

    @property
    def artifact_type(self) -> ArtifactType | None:
        """Get artifact type."""
        return self._artifact_type

    @property
    def content_type(self) -> ContentType:
        """Get content MIME type."""
        return self._content_type

    @property
    def content(self) -> str:
        """Get artifact content."""
        return self._content

    @property
    def content_hash(self) -> str | None:
        """Get content SHA-256 hash."""
        return self._content_hash

    @property
    def size_bytes(self) -> int:
        """Get content size in bytes."""
        return self._size_bytes

    @property
    def title(self) -> str | None:
        """Get artifact title."""
        return self._title

    @property
    def is_primary_deliverable(self) -> bool:
        """Check if this is the primary deliverable of its phase."""
        return self._is_primary_deliverable

    @property
    def storage_uri(self) -> str | None:
        """Get the object storage URI for this artifact's content."""
        return self._storage_uri

    @property
    def derived_from(self) -> list[str]:
        """Get list of parent artifact IDs."""
        return list(self._derived_from)

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    @command_handler("CreateArtifactCommand")
    def create_artifact(self, command: CreateArtifactCommand) -> None:
        """Handle CreateArtifactCommand.

        Creates a new artifact storing phase output.
        """
        from aef_domain.contexts.artifacts.create_artifact.ArtifactCreatedEvent import (
            ArtifactCreatedEvent,
        )

        # Validate: artifact must not already exist
        if self.id is not None:
            msg = "Artifact already exists"
            raise ValueError(msg)

        # Validate: must have content
        if not command.content:
            msg = "Artifact must have content"
            raise ValueError(msg)

        # Generate ID if not provided
        artifact_id = command.aggregate_id or str(uuid4())

        # Compute content hash and size
        content_hash = compute_content_hash(command.content)
        size_bytes = len(command.content.encode("utf-8"))

        # Initialize aggregate
        self._initialize(artifact_id)

        # Create and apply event
        event = ArtifactCreatedEvent(
            artifact_id=artifact_id,
            workflow_id=command.workflow_id,
            phase_id=command.phase_id,
            execution_id=command.execution_id,  # Link to execution run
            session_id=command.session_id,
            artifact_type=command.artifact_type,
            content_type=command.content_type or ContentType.TEXT_MARKDOWN,
            content=command.content,
            content_hash=content_hash,
            size_bytes=size_bytes,
            title=command.title,
            storage_uri=command.storage_uri,  # Object storage reference (ADR-012)
            is_primary_deliverable=command.is_primary_deliverable,
            derived_from=command.derived_from or [],
            metadata=command.metadata or {},
        )

        self._apply(event)

    # =========================================================================
    # EVENT SOURCING HANDLERS
    # =========================================================================

    @event_sourcing_handler("ArtifactCreated")
    def on_artifact_created(self, event: ArtifactCreatedEvent) -> None:
        """Apply ArtifactCreatedEvent."""
        self._workflow_id = event.workflow_id
        self._phase_id = event.phase_id
        self._execution_id = event.execution_id  # Capture execution context
        self._session_id = event.session_id
        self._artifact_type = event.artifact_type
        self._content_type = event.content_type
        self._content = event.content
        self._content_hash = event.content_hash
        self._size_bytes = event.size_bytes
        self._title = event.title
        self._storage_uri = event.storage_uri  # Object storage reference (ADR-012)
        self._is_primary_deliverable = event.is_primary_deliverable
        self._derived_from = list(event.derived_from)
        self._metadata = dict(event.metadata)
