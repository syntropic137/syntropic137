"""Translate committed exporter acknowledgements into immutable journal evidence."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from apss_session_capture.inventory import QualifiedTranscript

from syn_domain.contexts.agent_sessions import (
    BodyAvailability,
    CaptureEvidence,
    EvidenceBatch,
    EvidenceReference,
    InventoryNodeRef,
    SessionEvidence,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import (
        CataloguedCapture,
        SessionEvidenceWritePort,
    )

    from .exporter_transport import ExporterCaptureReceipt


async def publish_capture_receipt(
    journal: SessionEvidenceWritePort,
    capture: CataloguedCapture,
    destination_id: str,
    receipt: ExporterCaptureReceipt,
    content_hash: str,
) -> int:
    """Record a receipt that acknowledges the archived bytes as a present replica.

    ``content_hash`` is the APSS original-content hash of the archived capture.
    A receipt for another identity or another revision (#946) acknowledges a
    body syn137 did not archive, so it is refused, never recorded as present.
    """
    if capture.native_id is None:
        raise ValueError("remote receipt requires a native transcript identity")
    identity = QualifiedTranscript(
        source_instance_id=capture.run.source_instance_id,
        harness=capture.harness,
        native_session_id=capture.native_id,
    )
    if receipt.storage_key != identity.storage_key():
        raise ValueError("remote receipt belongs to another transcript")
    if not receipt.validates_capture(identity, content_hash):
        raise ValueError("remote receipt acknowledges another revision of the transcript")
    # Duplicate HTTP acknowledgements are equivalent evidence. Do not include
    # the duplicate flag or receipt lookup time in the immutable batch identity.
    digest = hashlib.sha256()
    for part in (
        destination_id,
        capture.producer_id,
        capture.capture_id,
        receipt.storage_key,
        receipt.content_hash,
        receipt.stored_content_hash,
    ):
        encoded = part.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    evidence_id = digest.hexdigest()
    reference = EvidenceReference(
        producer_id="remote-capture-receipts",
        evidence_id=evidence_id,
        source_revision=receipt.content_hash,
        locator=f"capture-receipt:{evidence_id}",
        extractor_version="1",
    )
    return await journal.append(
        EvidenceBatch(
            producer_id=reference.producer_id,
            batch_id=evidence_id,
            evidence=SessionEvidence(
                run=capture.run,
                captures=(
                    CaptureEvidence(
                        node=InventoryNodeRef(
                            kind="transcript",
                            source_instance_id=identity.source_instance_id,
                            harness=identity.harness,
                            local_id=identity.native_session_id,
                        ),
                        availability=BodyAvailability.PRESENT,
                        destination="remote",
                        receipt_sequence=0,
                        transcript_revision=receipt.content_hash,
                        evidence=reference,
                    ),
                ),
            ),
        )
    )
