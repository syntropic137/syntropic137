"""Current restrictions on exact local bodies, separate from historical receipts."""

from typing import Literal

from pydantic import Field

from .session_inventory import InventoryModel


class TranscriptBodyState(InventoryModel):
    """A current restriction overlaid on an immutable inventory page.

    Each hash names its representation. ``archive_sha256`` is the SHA-256 of the
    exact archived bytes (a local receipt's ``archived_byte_hash``).
    ``source_content_hash`` is the APSS original-content hash a remote receipt
    reports as its ``transcript_revision``; it is absent until known.
    """

    archive_sha256: str = Field(
        pattern=r"^[a-f0-9]{64}$",
        description="SHA-256 of the exact archived bytes, not the APSS content hash.",
    )
    source_content_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[a-f0-9]{64}$",
        description="APSS original-content hash of the same revision, when recorded.",
    )
    status: Literal["expired", "deleted", "withheld"] = Field(
        description="expired: retention removed the body. deleted: an owner deleted or "
        "retracted it. withheld: access was revoked while bytes are retained."
    )


BodyDeletionReason = Literal["retention_age", "retention_quota", "deletion", "retraction"]
OwnerDeletionReason = Literal["deletion", "retraction"]


class TranscriptDeletionReplica(InventoryModel):
    """Propagation of one body deletion to one configured replication destination."""

    destination_id: str = Field(description="Server-derived opaque destination identity.")
    status: Literal["pending", "queued", "propagated", "unresolvable"] = Field(
        description="pending: not yet handed to the exporter. queued: durably queued, "
        "not yet acknowledged. propagated: the replica acknowledged deletion. "
        "unresolvable: a legacy delivery recorded no content hash to delete by."
    )


class TranscriptDeletion(InventoryModel):
    """A durable body tombstone. Catalog and inventory history remain discoverable."""

    archive_sha256: str = Field(
        pattern=r"^[a-f0-9]{64}$",
        description="SHA-256 of the exact archived bytes this tombstone covers.",
    )
    source_content_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[a-f0-9]{64}$",
        description="APSS original-content hash used to delete replicated envelopes.",
    )
    reason: BodyDeletionReason
    local_status: Literal["pending", "deleted"]
    requested_at: str = Field(description="ISO 8601 UTC time the tombstone was recorded.")
    deleted_at: str | None = Field(
        default=None, description="ISO 8601 UTC time local bytes were erased."
    )
    replication: Literal["disabled", "propagate", "not_applicable"]
    replicas: tuple[TranscriptDeletionReplica, ...] = ()
