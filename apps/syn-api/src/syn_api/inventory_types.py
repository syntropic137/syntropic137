"""Session inventory API models, re-exported through the shared API type surface."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.agent_sessions import (
    InventoryFilter,
    InventoryItem,
    InventoryItemKeys,
    InventoryNode,
    InventorySnapshot,
    ItemKind,
    OwnerDeletionReason,
    RunIdentity,
    TranscriptBodyState,
    TranscriptDeletion,
)

ReconstructionStatus = Literal["not_started", "pending", "running", "current", "failed"]
CoverageStateValue = Literal[
    "unknown", "open", "reconciled", "missing", "unsupported", "conflicting"
]


class SessionInventoryNamespace(BaseModel):
    """Distinct sessions in one identity namespace (``platform``, ``invocation``,
    ``transcript:<harness>``). A native transcript id is only meaningful inside
    its harness namespace; it is never a platform session id."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    namespace: str
    kind: Literal["platform", "invocation", "transcript"]
    harness: str | None = None
    count: int = Field(ge=0)


class SessionInventorySummary(BaseModel):
    """Server-derived counts, completeness and display text every client shows verbatim.

    ``complete`` is the single completeness verdict: the published coverage
    contract is ``reconciled`` AND that revision is current. Every other
    coverage state (open, unknown, missing, unsupported, conflicting) or a
    pending/failed reconstruction is incomplete. Count fields are None when no
    revision is published, and the namespace split is None on revisions built
    before it was recorded.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    complete: bool
    coverage_state: CoverageStateValue
    coverage_display: str
    revision: str | None
    distinct_sessions: int | None = Field(ge=0)
    platform_sessions: int | None = Field(ge=0)
    invocations: int | None = Field(ge=0)
    native_transcripts: int | None = Field(ge=0)
    gaps: int | None = Field(ge=0)
    namespaces: tuple[SessionInventoryNamespace, ...] | None
    counts_display: str
    remote_replication: Literal["enabled", "disabled"]
    follow_up_command: str


_ARCHIVE_SHA256 = r"^[a-f0-9]{64}$"
_CONTENT_HASH = r"^sha256:[a-f0-9]{64}$"


class CaptureRevisionHashes(BaseModel):
    """Names the representation behind each hash one capture receipt carries.

    ``transcript_revision`` is not self-describing: a local receipt stores the
    archived byte SHA-256 there, a remote receipt the APSS original-content hash.
    ``transcript_revision_kind`` says which, or ``unqualified`` when the value
    matches neither known form. Never compare hashes of different kinds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    transcript_revision_kind: (
        Literal["archived_bytes_sha256", "source_content_hash", "unqualified"] | None
    ) = None
    archived_bytes_sha256: str | None = Field(
        default=None,
        pattern=_ARCHIVE_SHA256,
        description="SHA-256 of the exact archived bytes; the local transcript read key.",
    )
    source_content_hash: str | None = Field(
        default=None,
        pattern=_CONTENT_HASH,
        description="APSS original-content hash reported by a replica receipt.",
    )


class SessionInventoryResponse(BaseModel):
    """Published inventory and observed reconstruction progress, without read side effects."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    run: RunIdentity
    snapshot: InventorySnapshot | None
    reconstruction_status: ReconstructionStatus
    observed_evidence_watermark: int = Field(ge=0)
    later_evidence_pending: bool
    job_id: str | None = None
    summary: SessionInventorySummary


class SessionInventoryPageResponse(BaseModel):
    """One keyset page of a pinned revision plus current local restrictions.

    ``item_keys[i]`` names the qualified node keys ``items[i]`` references, so an
    edge endpoint on another page resolves through the node lookup route.
    ``next_cursor`` is opaque and bound to this run, revision, section and filters.
    Absent body overrides are unchecked. On capture pages ``capture_hashes[i]``
    names the hash representations of ``items[i]``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot: InventorySnapshot
    kind: ItemKind
    filters: InventoryFilter
    items: tuple[InventoryItem, ...]
    item_keys: tuple[InventoryItemKeys, ...]
    next_cursor: str | None = None
    body_overrides: tuple[TranscriptBodyState, ...] = ()
    capture_hashes: tuple[CaptureRevisionHashes, ...] = ()


class SessionInventoryCursorError(BaseModel):
    """Why a continuation cursor was refused. ``restart`` means re-read the head."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    code: Literal["cursor_invalid", "cursor_mismatch", "cursor_expired"]
    message: str
    mismatched: tuple[Literal["scope", "revision", "section", "filters"], ...] = ()
    restart: bool
    restart_snapshot_id: str | None = None


class SessionInventoryCursorErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    detail: SessionInventoryCursorError


class SessionInventoryNodeResponse(BaseModel):
    """A node-by-key lookup within one revision. Unknown keys disclose nothing."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot_id: str
    node_key: str
    status: Literal["resolved", "unresolved"]
    node: InventoryNode | None = None


class SessionInventoryRefreshRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=200, pattern=r"^[^\x00]+$")
    include_history: bool = False
    """Also backfill existing historical evidence first. Local reads only; no billing."""


class SessionHistoryBackfillSummary(BaseModel):
    """Receipts are reused across retries, so a resumed backfill reports the same total."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    receipts: int = Field(ge=0)
    materialized: int = Field(ge=0)
    evidence_watermark: int = Field(ge=0)


class SessionInventoryRefreshResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    job_id: str
    history: SessionHistoryBackfillSummary | None = None


class SessionInventoryBackfillRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=200, pattern=r"^[^\x00]+$")


class SessionInventoryBackfillResponse(BaseModel):
    """Durably queued per-execution backfills; the live inventory worker drains them."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    executions: int = Field(ge=0)
    enqueued: int = Field(ge=0)


class SessionInventoryJobResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    job_id: str
    run: RunIdentity
    stage: Literal["pending", "publishing", "completed", "failed"]
    evidence_watermark: int = Field(ge=0)
    snapshot_id: str
    resolver_version: str
    revision: str | None
    failure_code: str | None


class LocalTranscriptResponse(BaseModel):
    """Exact archive bytes, base64 encoded without parsing provider content.

    Redaction policy: the body is served exactly as archived. Any redaction was
    applied by the capturing source before archival; the server neither redacts,
    rewrites nor slices bytes, and never serves a partial range as the revision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["present", "not_captured", "missing", "expired", "deleted", "too_large"]
    archive_sha256: str = Field(
        pattern=_ARCHIVE_SHA256,
        description="SHA-256 of the exact archived bytes, not the APSS content hash.",
    )
    content_format: Literal["native", "envelope"] | None = None
    size: int | None = Field(default=None, ge=0, description="Archived byte length.")
    redaction: Literal["source"] = Field(
        default="source",
        description="Only source-applied redaction; the server serves archived bytes unchanged.",
    )
    content_base64: str | None = Field(default=None, repr=False)


class TranscriptIdentityRequest(BaseModel):
    """Qualified native identity of one archived revision in the addressed run."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    harness: str = Field(min_length=1, max_length=2048, pattern=r"^[^\x00]+$")
    native_id: str = Field(min_length=1, max_length=2048, pattern=r"^[^\x00]+$")


class TranscriptDeletionRequest(TranscriptIdentityRequest):
    reason: OwnerDeletionReason = "deletion"


class TranscriptDeletionResponse(BaseModel):
    """Durable tombstone for exact bytes shared by every membership of the object.

    ``created`` is false when a tombstone already existed; the original reason
    is kept. Session history remains discoverable with a deleted body state.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    deletion: TranscriptDeletion
    created: bool


class TranscriptRevocationResponse(BaseModel):
    """Access to the exact bytes is withheld; stored bytes are retained."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    archive_sha256: str = Field(
        pattern=_ARCHIVE_SHA256, description="SHA-256 of the exact archived bytes."
    )
    status: Literal["withheld"] = "withheld"
    created: bool
