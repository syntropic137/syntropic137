"""Historical evidence normalized for backfill, independent of any source format (#1398).

Legacy telemetry has no durable record identity. A backfill materializes each
distinct legacy record once, under a stable snapshot and row ordinal, and every
later run reuses that receipt instead of minting a new fact.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID  # noqa: TC003 - runtime Pydantic field

from pydantic import Field, model_validator

from .native_session_evidence import NativeTranscriptFacts  # noqa: TC001 - runtime Pydantic field
from .session_inventory import (
    EvidenceReference,
    Identifier,
    InventoryModel,
    RoutingIdentifier,
    RunIdentity,
)

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class LegacyCaptureObservation(InventoryModel):
    """One historical capture verdict for a host-assigned phase session.

    ``native_session_ids`` is None when the recorded payload cannot say which
    native sessions it saw (older or unsupported schema). That stays unknown;
    it is never read as "confirmed none".
    """

    platform_session_id: Identifier
    phase_id: Identifier | None = None
    observed_at: Identifier
    schema_version: int | None = None
    native_session_ids: tuple[Identifier, ...] | None = None


class LegacyDelegateAlias(InventoryModel):
    """A delegated native session already billed to this execution.

    Read-only: the backfill derives the platform identity with the fixed
    import namespace and never touches the ledger that recorded the charge.
    """

    native_session_id: Identifier


class ArchivedTranscriptFacts(InventoryModel):
    """Facts re-extracted from a catalogued local archive by the harness adapter."""

    producer_id: RoutingIdentifier
    capture_id: RoutingIdentifier
    harness: Identifier
    archive_sha256: Sha256
    catalogued_native_id: Identifier | None = None
    """The identity recorded when the bytes were acquired, kept after they expire."""
    facts: NativeTranscriptFacts | None
    """None when the catalogued bytes are no longer present in the archive."""


class HistoricalAcquisition(InventoryModel):
    run: RunIdentity
    observations: tuple[LegacyCaptureObservation, ...] = ()
    delegate_aliases: tuple[LegacyDelegateAlias, ...] = ()
    archives: tuple[ArchivedTranscriptFacts, ...] = ()


class QualifiedNative(InventoryModel):
    """A native ID with every harness namespace the acquired evidence places it in.

    Zero harnesses is unqualified, more than one is ambiguous. Neither is guessed.
    """

    native_id: Identifier
    harnesses: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def _canonical(self) -> QualifiedNative:
        if self.harnesses != tuple(sorted(set(self.harnesses))):
            raise ValueError("harness namespaces must be sorted and unique")
        return self


class LegacyObservationRecord(InventoryModel):
    kind: Literal["capture_observation"] = "capture_observation"
    platform_session_id: Identifier
    phase_id: Identifier | None = None
    observed_at: Identifier
    schema_version: int | None = None
    chunk: int = Field(default=0, ge=0)
    natives: tuple[QualifiedNative, ...] | None = None


class LegacyDelegateRecord(InventoryModel):
    kind: Literal["delegate_alias"] = "delegate_alias"
    native: QualifiedNative


class LegacyArchiveRecord(InventoryModel):
    kind: Literal["archived_transcript"] = "archived_transcript"
    producer_id: RoutingIdentifier
    capture_id: RoutingIdentifier
    harness: Identifier
    archive_sha256: Sha256
    catalogued_native_id: Identifier | None = None
    chunk: int = Field(ge=0)
    facts: NativeTranscriptFacts | None


LegacyRecord = Annotated[
    LegacyObservationRecord | LegacyDelegateRecord | LegacyArchiveRecord,
    Field(discriminator="kind"),
]


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def record_fingerprint(record: LegacyRecord) -> str:
    """Content identity. Exact duplicate deliveries collapse to one receipt."""
    return _digest(record.model_dump_json())


def record_key(record: LegacyRecord) -> str:
    """Source identity without derived qualification.

    A later acquisition that qualifies the same source record differently gets
    a new receipt that explicitly supersedes the earlier one.
    """
    if isinstance(record, LegacyObservationRecord):
        natives = None if record.natives is None else [item.native_id for item in record.natives]
        parts: list[object] = [
            record.kind,
            record.platform_session_id,
            record.phase_id,
            record.observed_at,
            record.schema_version,
            record.chunk,
            natives,
        ]
    elif isinstance(record, LegacyDelegateRecord):
        parts = [record.kind, record.native.native_id]
    else:
        parts = [
            record.kind,
            record.producer_id,
            record.capture_id,
            record.archive_sha256,
            record.chunk,
            # Losing bytes later must never retract facts extracted earlier.
            record.facts is not None,
        ]
    return _digest(json.dumps(parts, ensure_ascii=False, separators=(",", ":")))


BACKFILL_PRODUCER = "session-history-backfill"


class BackfillReceipt(InventoryModel):
    """A legacy record materialized once, under a stable snapshot and row ordinal."""

    run: RunIdentity
    snapshot_id: UUID
    ordinal: int = Field(ge=1)
    record_key: Sha256
    fingerprint: Sha256
    record: LegacyRecord
    supersedes: tuple[EvidenceReference, ...] = ()

    @model_validator(mode="after")
    def _identity(self) -> BackfillReceipt:
        if self.fingerprint != record_fingerprint(self.record):
            raise ValueError("receipt fingerprint does not match its record")
        if self.record_key != record_key(self.record):
            raise ValueError("receipt key does not match its record")
        return self

    @property
    def reference(self) -> EvidenceReference:
        record = self.record
        version = f"legacy-{record.kind}/1"
        if isinstance(record, LegacyArchiveRecord) and record.facts is not None:
            version = f"{version}+{record.facts.extractor_version}"
        return EvidenceReference(
            producer_id=BACKFILL_PRODUCER,
            evidence_id=f"{self.snapshot_id}:{self.ordinal}",
            source_revision=self.fingerprint,
            locator=f"{BACKFILL_PRODUCER}:{record.kind}:{self.record_key}",
            extractor_version=version,
        )
