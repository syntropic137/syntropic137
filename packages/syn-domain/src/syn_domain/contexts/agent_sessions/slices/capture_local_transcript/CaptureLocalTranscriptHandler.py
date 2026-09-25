"""Local durability precedes metadata acknowledgement; remote storage is optional."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    AcquisitionGapEvidence,
    CaptureEvidence,
    NativeTranscriptObservation,
    NodeEvidence,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    BodyAvailability,
    EvidenceReference,
    Identifier,
    InventoryGap,
    InventoryModel,
    InventoryNodeRef,
    RoutingIdentifier,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.ports.SessionCaptureCatalogPort import CataloguedCapture
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import EvidenceBatch
from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import (
    ArchivedTranscript,  # noqa: TC001 - runtime Pydantic field
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.ports.NativeSessionEvidencePort import (
        NativeSessionEvidencePort,
        NativeTranscriptFacts,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionCaptureCatalogPort import (
        SessionCaptureCatalogPort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
        SessionEvidenceWritePort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import (
        SessionTranscriptArchivePort,
    )


class LocalTranscriptCapture(InventoryModel):
    run: RunIdentity
    capture_id: RoutingIdentifier
    harness: Identifier
    receipt_sequence: int = Field(ge=0)
    content: bytes = Field(max_length=16 * 1024 * 1024, repr=False)
    content_format: Literal["native", "envelope"] = "native"
    producer_id: RoutingIdentifier = "local-native-capture"


class LocalCaptureResult(InventoryModel):
    archive: ArchivedTranscript
    native_id: Identifier | None
    evidence_watermark: int = Field(ge=1)
    issues: tuple[Identifier, ...]


def _node(request: LocalTranscriptCapture, native_id: str) -> InventoryNodeRef:
    return InventoryNodeRef(
        kind="transcript",
        source_instance_id=request.run.source_instance_id,
        harness=request.harness,
        local_id=native_id,
    )


def _base_evidence(
    request: LocalTranscriptCapture,
    facts: NativeTranscriptFacts,
    reference: EvidenceReference,
    archive: ArchivedTranscript,
) -> SessionEvidence:
    gaps = tuple(
        AcquisitionGapEvidence(
            gap=InventoryGap(reason=issue, evidence_ids=(reference.evidence_id,)),
            evidence=reference,
        )
        for issue in facts.issues
    )
    if facts.native_id is None:
        return SessionEvidence(run=request.run, acquisition_gaps=gaps)
    node = _node(request, facts.native_id)
    return SessionEvidence(
        run=request.run,
        nodes=(NodeEvidence(node=node, evidence=reference),),
        captures=(
            CaptureEvidence(
                node=node,
                availability=BodyAvailability.PRESENT,
                receipt_sequence=request.receipt_sequence,
                evidence=reference,
                transcript_revision=archive.sha256,
                archived_byte_hash=archive.sha256,
            ),
        ),
        acquisition_gaps=gaps,
    )


class CaptureLocalTranscriptHandler:
    def __init__(
        self,
        archive: SessionTranscriptArchivePort,
        evidence: SessionEvidenceWritePort,
        extractor: NativeSessionEvidencePort,
        *,
        catalog: SessionCaptureCatalogPort | None = None,
    ) -> None:
        self._archive, self._evidence, self._extractor = archive, evidence, extractor
        self._catalog = catalog

    async def handle(self, request: LocalTranscriptCapture) -> LocalCaptureResult:
        facts = (
            self._extractor.extract_envelope(request.harness, request.content)
            if request.content_format == "envelope"
            else self._extractor.extract(request.harness, request.content)
        )
        archive = await self._archive.put(request.content)
        if self._catalog is not None:
            await self._catalog.record(
                CataloguedCapture(
                    run=request.run,
                    producer_id=request.producer_id,
                    capture_id=request.capture_id,
                    harness=request.harness,
                    native_id=facts.native_id,
                    content_format=request.content_format,
                    archive=archive,
                )
            )
        reference = EvidenceReference(
            producer_id=request.producer_id,
            evidence_id=request.capture_id,
            source_revision=archive.sha256,
            locator=f"archive:sha256:{archive.sha256}",
            extractor_version=facts.extractor_version,
        )
        base = _base_evidence(request, facts, reference, archive)
        relationships = facts.relationships
        watermark = 0
        # Bounded journal pages; retry regenerates byte-equivalent immutable batches.
        pages = max(len(relationships), len(base.acquisition_gaps), 1)
        for start in range(0, pages, 200):
            payload = SessionEvidence(
                run=request.run,
                nodes=base.nodes if start == 0 else (),
                captures=base.captures if start == 0 else (),
                native_transcripts=(
                    NativeTranscriptObservation(
                        node=_node(request, facts.native_id),
                        facts=facts.model_copy(
                            update={
                                "relationships": relationships[start : start + 200],
                                "issues": (),
                            }
                        ),
                        evidence=reference,
                    ),
                )
                if facts.native_id is not None
                else (),
                acquisition_gaps=base.acquisition_gaps[start : start + 200],
            )
            batch_id = hashlib.sha256(f"{request.capture_id}:{start}".encode()).hexdigest()
            watermark = await self._evidence.append(
                EvidenceBatch(
                    batch_id=batch_id,
                    producer_id=reference.producer_id,
                    evidence=payload,
                )
            )
        return LocalCaptureResult(
            archive=archive,
            native_id=facts.native_id,
            evidence_watermark=watermark,
            issues=facts.issues,
        )
