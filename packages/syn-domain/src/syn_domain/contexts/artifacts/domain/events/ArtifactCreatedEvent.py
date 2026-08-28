"""ArtifactCreated event - represents the fact that an artifact was created."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any

from event_sourcing import DomainEvent, event

from syn_domain.contexts.artifacts._shared.value_objects import (  # noqa: TC001
    ArtifactType,
    ContentType,
)


@event("ArtifactCreated", "v4")
class ArtifactCreatedEvent(DomainEvent):
    """Event emitted when an artifact is created.

    v2: Added execution_id to link artifacts to specific workflow execution runs.
    v3: Added storage_uri for two-tier storage (ADR-012).
    v4: Added created_at (issue #920).

    WHY v4 CARRIES ITS OWN TIMESTAMP. ``DomainEvent`` declares no timestamp -
    ``event_type`` and ``schema_version`` are ClassVars, and the envelope's time
    is not passed to projection handlers, which receive a flat payload dict. So
    an event that does not state when it happened has no recoverable time at
    all. The list_artifacts projection read ``event_data.get("created_at")``
    against a payload that never had the key, and every artifact came back with
    ``created_at`` null.

    That surfaced twice: the CLI rendered a ``Created`` column reading ``-`` for
    every row, and ``ListArtifactsQuery`` - which already defaults to
    ``-created_at`` - had nothing to sort on, so the order degraded to insertion
    order and a newly created artifact landed on the LAST page. It read as data
    loss; nothing was lost.

    Artifacts created before v4 keep a null ``created_at``. That is deliberate:
    the time was never recorded, and inventing one from replay or ingest would
    fabricate a fact the event store does not contain.
    """

    # Identity
    artifact_id: str

    # Context - links artifact to workflow execution
    workflow_id: str
    phase_id: str
    execution_id: str | None = None  # NEW in v2: Links to WorkflowExecution
    session_id: str | None = None

    # Type
    artifact_type: ArtifactType
    content_type: ContentType

    # Content
    content: str
    content_hash: str
    size_bytes: int
    title: str | None = None

    # Storage (ADR-012: Two-tier storage)
    storage_uri: str | None = None  # NEW in v3: URI to object storage

    # Classification
    is_primary_deliverable: bool = True

    # Lineage
    derived_from: list[str] = []  # noqa: RUF012

    # Metadata
    metadata: dict[str, Any] = {}  # noqa: RUF012

    # When the artifact was created (NEW in v4, issue #920). Server-side UTC;
    # clients format for their locale.
    # Optional, not because it is optional for NEW artifacts - the aggregate
    # always sets it - but because v3 events already in the store genuinely do
    # not have it. Typing it non-optional would be a lie that replay disproves.
    created_at: datetime | None = None
