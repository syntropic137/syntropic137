"""ArtifactCreated event - represents the fact that an artifact was created."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any

from event_sourcing import DomainEvent, event

from syn_domain.contexts.artifacts._shared.value_objects import (  # noqa: TC001
    ArtifactType,
    ContentType,
)


@event("ArtifactCreated", "v5")
class ArtifactCreatedEvent(DomainEvent):
    """Event emitted when an artifact is created.

    v2: Added execution_id to link artifacts to specific workflow execution runs.
    v3: Added storage_uri for two-tier storage (ADR-012).
    v4: Added created_at (issue #920).
    v5: Added source_path (issue #988) - the path the file occupied under
    ``artifacts/output/`` in the producing phase's workspace. Before v5 the
    only record of it was interpolated into the display ``title`` as
    ``f"{phase_name}: {artifact_path}"``, so recovering it meant parsing a
    human-readable string on a separator (": ") that a phase name may itself
    contain. Storing it as a field is what lets a later phase receive the
    producing phase's whole output TREE at its original relative paths
    instead of one arbitrary file flattened to ``<phase-id>.md``.
    NOTE the version string here is
    decorator metadata only - it does not set ``DomainEvent.schema_version``,
    and the gRPC serializer writes ``event_version=1`` regardless. Deserialization
    resolves on event TYPE and ignores the stored version, so no upcaster runs
    (and v2/v3 shipped the same way). A new optional field with a default is
    safe under that scheme; a REQUIRED field or a renamed one would not be.

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

    Artifacts created before v4 keep a null ``created_at``. That is deliberate,
    but the reason is narrower than "the time was never recorded": the wire
    metadata DOES carry ``timestamp_unix_ms``. It is unreachable on the read
    path. ``_proto_to_envelope`` builds ``EventMetadata`` without a timestamp,
    so the field falls back to ``datetime.now(UTC)`` and a replayed event
    reports DECODE time rather than event time - plausible, current, and wrong.
    Backfilling from that would stamp every historical artifact with the moment
    of the rebuild.

    Recovering the real times therefore needs the decoder fixed as well as the
    dispatcher (#924), not just the dispatcher -- or a path that does not go
    through the decoder at all. ``scripts/backfill/backfill_artifact_created_at.py``
    takes the second: it reads ``events.timestamp_unix_ms`` directly in SQL and
    replays it back as ``ArtifactCreationTimeRecovered``, which is a separate
    fact with its own provenance rather than a rewrite of this one (#1215).
    Until that is run, these rows stay null, and the list surfaces now report
    how many they dropped for it instead of leaving an unexplained gap.
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

    # Where the file lived under artifacts/output/ in the producing workspace
    # (NEW in v5, issue #988). Example: "artifacts/output/raw-findings/f1.yaml".
    # Optional for the same reason created_at is: v4-and-earlier events already
    # in the store genuinely do not carry it, and no upcaster runs to add it.
    # Consumers MUST treat None as "path unknown" and fall back to the flat
    # artifacts/input/<phase-id>.md name rather than inventing a path.
    source_path: str | None = None

    # When the artifact was created (NEW in v4, issue #920). Server-side UTC;
    # clients format for their locale.
    # Optional, not because it is optional for NEW artifacts - the aggregate
    # always sets it - but because v3 events already in the store genuinely do
    # not have it. Typing it non-optional would be a lie that replay disproves.
    created_at: datetime | None = None
