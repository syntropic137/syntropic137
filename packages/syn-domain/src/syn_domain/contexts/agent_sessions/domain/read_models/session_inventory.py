"""Qualified identities and immutable reconstruction results (#1398).

Platform sessions retain their existing lifecycle and billing identity. Native
transcripts may be discovered without any evidence of a registered invocation.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _opaque_identifier(value: str) -> str:
    if not value.strip() or "\x00" in value:
        raise ValueError("identifier must be non-blank and contain no NUL")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("identifier must contain valid Unicode scalar values") from exc
    return value


Identifier = Annotated[str, Field(max_length=2048), AfterValidator(_opaque_identifier)]
# Host/source routing IDs are bounded separately from opaque native IDs. Four
# UTF-8 bytes per character still fit the compound PostgreSQL btree keys.
RoutingIdentifier = Annotated[str, Field(max_length=128), AfterValidator(_opaque_identifier)]


class InventoryModel(BaseModel):
    """Wire-safe, immutable inventory records; reject unknown schema fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RunIdentity(InventoryModel):
    source_instance_id: RoutingIdentifier
    execution_id: RoutingIdentifier


class InventoryNodeRef(InventoryModel):
    """A reference never changes the native ID or its source-content hash."""

    kind: Literal["platform", "invocation", "transcript"]
    source_instance_id: RoutingIdentifier
    local_id: Identifier
    harness: Identifier | None = None

    @model_validator(mode="after")
    def _harness_namespace(self) -> InventoryNodeRef:
        if (self.kind == "transcript") != (self.harness is not None):
            raise ValueError("harness is required only for a native transcript reference")
        return self

    @property
    def key(self) -> str:
        """Versioned storage key, distinct from the APSS envelope session_id."""
        parts = (
            "syn-inventory-node/1",
            self.kind,
            self.source_instance_id,
            self.harness,
            self.local_id,
        )
        encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


class EvidenceClass(StrEnum):
    REGISTERED = "registered"
    CORROBORATED = "corroborated"
    CANDIDATE = "candidate"
    CONFLICTING = "conflicting"


class BodyAvailability(StrEnum):
    PRESENT = "present"
    PENDING = "pending"
    MISSING = "missing"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class CoverageState(StrEnum):
    UNKNOWN = "unknown"
    OPEN = "open"
    RECONCILED = "reconciled"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"
    CONFLICTING = "conflicting"


class EvidenceReference(InventoryModel):
    evidence_id: Identifier
    producer_id: Identifier
    source_revision: Identifier
    locator: Identifier
    extractor_version: Identifier


class EvidenceRetraction(InventoryModel):
    """An explicit producer correction; it cannot revoke another producer's facts."""

    target: EvidenceReference
    evidence: EvidenceReference

    @model_validator(mode="after")
    def _authority(self) -> EvidenceRetraction:
        if self.target.producer_id != self.evidence.producer_id:
            raise ValueError("a producer cannot retract another producer's evidence")
        if self.target.evidence_id == self.evidence.evidence_id:
            raise ValueError("a correction requires its own evidence identity")
        return self


class CaptureReceipt(InventoryModel):
    node: InventoryNodeRef
    availability: BodyAvailability
    receipt_sequence: int = Field(ge=0)
    evidence: EvidenceReference
    destination: Literal["local", "remote"] = "local"
    transcript_revision: Identifier | None = None
    archived_byte_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None

    @model_validator(mode="after")
    def _present_has_archive_proof(self) -> CaptureReceipt:
        if (
            self.destination == "local"
            and self.availability is BodyAvailability.PRESENT
            and self.archived_byte_hash is None
        ):
            raise ValueError("present local transcript requires its durable archive byte hash")
        return self


class InventoryNode(InventoryModel):
    ref: InventoryNodeRef
    evidence: tuple[EvidenceReference, ...] = ()


class Membership(InventoryModel):
    node: InventoryNodeRef
    run: RunIdentity
    phase_id: Identifier | None = None
    attempt_id: Identifier | None = None
    segment: Identifier | None = None
    confidence: EvidenceClass
    evidence: tuple[EvidenceReference, ...]


class LineageEdge(InventoryModel):
    parent: InventoryNodeRef
    child: InventoryNodeRef
    relation: Literal["spawn", "resume", "fork"]
    confidence: EvidenceClass
    evidence: tuple[EvidenceReference, ...]
    parent_segment: Identifier | None = None
    child_segment: Identifier | None = None


class IdentityBinding(InventoryModel):
    """A platform session or registered invocation represents native transcript work."""

    owner: InventoryNodeRef
    transcript: InventoryNodeRef
    segment: Identifier | None = None
    confidence: EvidenceClass
    evidence: tuple[EvidenceReference, ...]

    @model_validator(mode="after")
    def _identity_kinds(self) -> IdentityBinding:
        if (
            self.owner.kind not in ("platform", "invocation")
            or self.transcript.kind != "transcript"
        ):
            raise ValueError(
                "identity binding requires a platform/invocation owner and a native transcript"
            )
        return self


class InventoryGap(InventoryModel):
    reason: Identifier
    node_keys: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class InventoryCoverage(InventoryModel):
    state: CoverageState
    contract_id: Identifier | None = None
    expected_count: int | None = Field(default=None, ge=0)
    missing_keys: tuple[str, ...] = ()


class ResolvedInventory(InventoryModel):
    schema_version: Literal[1] = 1
    resolver_version: str
    run: RunIdentity
    revision: str
    nodes: tuple[InventoryNode, ...]
    memberships: tuple[Membership, ...]
    edges: tuple[LineageEdge, ...]
    gaps: tuple[InventoryGap, ...]
    coverage: InventoryCoverage
    bindings: tuple[IdentityBinding, ...] = ()
    captures: tuple[CaptureReceipt, ...] = ()
    retractions: tuple[EvidenceRetraction, ...] = ()
