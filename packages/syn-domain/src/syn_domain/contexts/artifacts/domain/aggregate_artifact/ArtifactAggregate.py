"""Artifact aggregate root - stores phase outputs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from syn_domain.contexts.artifacts._shared.value_objects import (
    ArtifactType,
    ContentType,
    compute_content_hash,
)

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.commands.CreateArtifactCommand import (
        CreateArtifactCommand,
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
    from syn_domain.contexts.artifacts.domain.events.ArtifactCreatedEvent import (
        ArtifactCreatedEvent,
    )
    from syn_domain.contexts.artifacts.domain.events.ArtifactCreationTimeRecoveredEvent import (
        ArtifactCreationTimeRecoveredEvent,
    )
    from syn_domain.contexts.artifacts.domain.events.ArtifactDeletedEvent import (
        ArtifactDeletedEvent,
    )
    from syn_domain.contexts.artifacts.domain.events.ArtifactUpdatedEvent import (
        ArtifactUpdatedEvent,
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
        self._source_path: str | None = None  # #988: path under artifacts/output/
        # None only for artifacts written before ArtifactCreated v4 (#920).
        # The aggregate holds it so it can answer the one question the backfill
        # asks -- "is this row still undated?" -- from the event stream rather
        # than from the projection it is about to write to (#1215).
        self._created_at: datetime | None = None
        self._storage_uri: str | None = None  # Object storage reference (ADR-012)
        self._is_primary_deliverable: bool = True
        self._is_deleted: bool = False
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
    def source_path(self) -> str | None:
        """Path this file occupied under the producing workspace's output dir.

        None for artifacts created before ArtifactCreated v5 (issue #988).
        """
        return self._source_path

    @property
    def created_at(self) -> datetime | None:
        """When this artifact was created, or None if its event never said.

        Null for the artifacts written before ArtifactCreated v4 and not since
        recovered. Null is the honest answer for those and stays available; the
        list surfaces report how many rows they dropped for it (#1215) rather
        than papering over it with a plausible time.
        """
        return self._created_at

    @property
    def is_primary_deliverable(self) -> bool:
        """Check if this is the primary deliverable of its phase."""
        return self._is_primary_deliverable

    @property
    def is_deleted(self) -> bool:
        """Check if this artifact has been soft-deleted."""
        return self._is_deleted

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
        from syn_domain.contexts.artifacts.domain.events.ArtifactCreatedEvent import (
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
            source_path=command.source_path,  # #988: original relative path
            storage_uri=command.storage_uri,  # Object storage reference (ADR-012)
            is_primary_deliverable=command.is_primary_deliverable,
            derived_from=command.derived_from or [],
            metadata=command.metadata or {},
            # #920: the event must state its own time. Nothing downstream can
            # recover it otherwise - handlers get a flat payload, not the envelope.
            created_at=datetime.now(UTC),
        )

        self._apply(event)

    @command_handler("RecoverArtifactCreationTimeCommand")
    def recover_creation_time(self, command: RecoverArtifactCreationTimeCommand) -> None:
        """Record a creation time recovered for an artifact whose event lacked one.

        Emits nothing when the artifact already has one. That is what makes the
        backfill idempotent, and it is enforced here rather than in the script
        because "an artifact's creation time is written once" is a rule about
        artifacts, not about one script's ``WHERE`` clause. A second run, a
        concurrent run, or a hand-issued command all hit the same guard, and no
        recovered value can ever displace a real one.

        Silent rather than raising, because "already dated" is the expected
        outcome for most of the corpus and the normal end state of a re-run --
        not a failure. The caller learns which it was from
        ``uncommitted_events``.
        """
        from syn_domain.contexts.artifacts.domain.events.ArtifactCreationTimeRecoveredEvent import (
            ArtifactCreationTimeRecoveredEvent,
        )

        if self.id is None:
            msg = "Artifact does not exist"
            raise ValueError(msg)
        if self._created_at is not None:
            return

        self._apply(
            ArtifactCreationTimeRecoveredEvent(
                artifact_id=str(self.id),
                created_at=command.created_at,
                recovered_from=command.recovered_from,
            )
        )

    @command_handler("UpdateArtifactCommand")
    def update_artifact(self, command: UpdateArtifactCommand) -> None:
        """Handle UpdateArtifactCommand.

        Updates mutable artifact metadata (title, metadata, is_primary_deliverable).
        """
        from syn_domain.contexts.artifacts.domain.events.ArtifactUpdatedEvent import (
            ArtifactUpdatedEvent,
        )

        if self.id is None:
            msg = "Artifact does not exist"
            raise ValueError(msg)
        if self._is_deleted:
            msg = "Artifact is deleted"
            raise ValueError(msg)

        event = ArtifactUpdatedEvent(
            artifact_id=str(self.id),
            title=command.title,
            metadata=command.metadata,
            is_primary_deliverable=command.is_primary_deliverable,
        )
        self._apply(event)

    @command_handler("DeleteArtifactCommand")
    def delete_artifact(self, command: DeleteArtifactCommand) -> None:
        """Handle DeleteArtifactCommand.

        Soft-deletes the artifact.
        """
        from syn_domain.contexts.artifacts.domain.events.ArtifactDeletedEvent import (
            ArtifactDeletedEvent,
        )

        if self.id is None:
            msg = "Artifact does not exist"
            raise ValueError(msg)
        if self._is_deleted:
            msg = "Artifact is already deleted"
            raise ValueError(msg)

        event = ArtifactDeletedEvent(
            artifact_id=str(self.id),
            deleted_by=command.deleted_by,
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
        self._source_path = event.source_path
        self._created_at = event.created_at
        self._storage_uri = event.storage_uri  # Object storage reference (ADR-012)
        self._is_primary_deliverable = event.is_primary_deliverable
        self._derived_from = list(event.derived_from)
        self._metadata = dict(event.metadata)

    @event_sourcing_handler("ArtifactCreationTimeRecovered")
    def on_artifact_creation_time_recovered(
        self, event: ArtifactCreationTimeRecoveredEvent
    ) -> None:
        """Apply ArtifactCreationTimeRecoveredEvent."""
        self._created_at = event.created_at

    @event_sourcing_handler("ArtifactUpdated")
    def on_artifact_updated(self, event: ArtifactUpdatedEvent) -> None:
        """Apply ArtifactUpdatedEvent."""
        if event.title is not None:
            self._title = event.title
        if event.metadata is not None:
            self._metadata = dict(event.metadata)
        if event.is_primary_deliverable is not None:
            self._is_primary_deliverable = event.is_primary_deliverable

    @event_sourcing_handler("ArtifactDeleted")
    def on_artifact_deleted(self, _event: ArtifactDeletedEvent) -> None:
        """Apply ArtifactDeletedEvent."""
        self._is_deleted = True
