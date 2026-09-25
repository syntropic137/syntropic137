"""Pure normalization of historical records into the live evidence vocabulary.

No inference lives here. Qualification only records which harness namespaces
the acquired evidence itself places a native ID in. Membership from a capture
sweep stays a candidate, unknown stays unknown, and completeness is never
declared: no coverage contract is emitted for legacy data.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.read_models.legacy_evidence import (
    BACKFILL_PRODUCER,
    BackfillReceipt,
    LegacyArchiveRecord,
    LegacyDelegateRecord,
    LegacyObservationRecord,
    LegacyRecord,
    QualifiedNative,
    record_fingerprint,
    record_key,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    AcquisitionGapEvidence,
    IdentityBindingEvidence,
    MembershipEvidence,
    NativeTranscriptObservation,
    NodeEvidence,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceClass,
    EvidenceReference,
    EvidenceRetraction,
    InventoryGap,
    InventoryNodeRef,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.import_identity import platform_session_id_for
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import EvidenceBatch

if TYPE_CHECKING:
    from uuid import UUID

    from syn_domain.contexts.agent_sessions.domain.read_models.legacy_evidence import (
        ArchivedTranscriptFacts,
        HistoricalAcquisition,
    )
    from syn_domain.contexts.agent_sessions.domain.read_models.native_session_evidence import (
        NativeTranscriptFacts,
    )

#: Claims per legacy record. Keeps every receipt inside one bounded journal batch.
CHUNK = 200


def _fact_ids(facts: NativeTranscriptFacts | None) -> list[str]:
    if facts is None or not facts.supported:
        return []
    ids = [facts.native_id, facts.root_native_id]
    for link in facts.relationships:
        ids.extend((link.parent_native_id, link.child_native_id))
    return [native for native in ids if native is not None]


def _harness_index(
    archives: tuple[ArchivedTranscriptFacts, ...], prior: tuple[BackfillReceipt, ...]
) -> dict[str, set[str]]:
    """Namespaces only grow: expired bytes never un-qualify an earlier receipt."""
    sources: list[tuple[str, list[str]]] = [
        (archive.harness, _fact_ids(archive.facts)) for archive in archives
    ]
    sources.extend(
        (archive.harness, [archive.catalogued_native_id])
        for archive in archives
        if archive.catalogued_native_id is not None
    )
    sources.extend(
        (receipt.record.harness, _fact_ids(receipt.record.facts))
        for receipt in prior
        if isinstance(receipt.record, LegacyArchiveRecord)
    )
    index: dict[str, set[str]] = defaultdict(set)
    for harness, natives in sources:
        for native in natives:
            index[native].add(harness)
    return index


def _qualified(native: str, index: dict[str, set[str]]) -> QualifiedNative:
    return QualifiedNative(native_id=native, harnesses=tuple(sorted(index.get(native, ()))))


def _archive_records(archive: ArchivedTranscriptFacts) -> list[LegacyArchiveRecord]:
    facts = archive.facts

    def record(chunk: int, part: NativeTranscriptFacts | None) -> LegacyArchiveRecord:
        return LegacyArchiveRecord(
            producer_id=archive.producer_id,
            capture_id=archive.capture_id,
            harness=archive.harness,
            archive_sha256=archive.archive_sha256,
            catalogued_native_id=archive.catalogued_native_id,
            chunk=chunk,
            facts=part,
        )

    if facts is None:
        return [record(0, None)]
    chunks = max(-(-len(facts.relationships) // CHUNK), -(-len(facts.issues) // CHUNK), 1)
    return [
        record(
            index,
            facts.model_copy(
                update={
                    "relationships": facts.relationships[index * CHUNK : (index + 1) * CHUNK],
                    "issues": facts.issues[index * CHUNK : (index + 1) * CHUNK],
                }
            ),
        )
        for index in range(chunks)
    ]


def qualify(
    acquisition: HistoricalAcquisition, prior: tuple[BackfillReceipt, ...] = ()
) -> tuple[LegacyRecord, ...]:
    """Deterministic in the acquired set; source order and duplicates do not matter."""
    index = _harness_index(acquisition.archives, prior)
    records: list[LegacyRecord] = []
    for archive in acquisition.archives:
        records.extend(_archive_records(archive))
    for observation in acquisition.observations:
        natives = observation.native_session_ids
        ordered = sorted(set(natives or ()))
        records.extend(
            LegacyObservationRecord(
                platform_session_id=observation.platform_session_id,
                phase_id=observation.phase_id,
                observed_at=observation.observed_at,
                schema_version=observation.schema_version,
                chunk=start // CHUNK,
                natives=None
                if natives is None
                else tuple(_qualified(item, index) for item in ordered[start : start + CHUNK]),
            )
            for start in range(0, max(len(ordered), 1), CHUNK)
        )
    records.extend(
        LegacyDelegateRecord(native=_qualified(alias.native_session_id, index))
        for alias in acquisition.delegate_aliases
    )
    unique = {record_fingerprint(item): item for item in records}
    return tuple(unique[key] for key in sorted(unique))


def plan_receipts(
    run: RunIdentity,
    snapshot_id: UUID,
    records: tuple[LegacyRecord, ...],
    existing: tuple[BackfillReceipt, ...],
) -> tuple[BackfillReceipt, ...]:
    """New receipts only. Known fingerprints reuse their original snapshot and ordinal."""
    known = {item.fingerprint for item in existing}
    retracted = {ref.evidence_id for item in existing for ref in item.supersedes}
    active: dict[str, list[EvidenceReference]] = defaultdict(list)
    for item in existing:
        if item.reference.evidence_id not in retracted:
            active[item.record_key].append(item.reference)
    fresh = {record_fingerprint(item): item for item in records}
    fresh = {key: value for key, value in fresh.items() if key not in known}
    start = 1 + max(
        (item.ordinal for item in existing if item.snapshot_id == snapshot_id), default=0
    )
    planned: list[BackfillReceipt] = []
    for offset, fingerprint in enumerate(sorted(fresh)):
        record = fresh[fingerprint]
        key = record_key(record)
        planned.append(
            BackfillReceipt(
                run=run,
                snapshot_id=snapshot_id,
                ordinal=start + offset,
                record_key=key,
                fingerprint=fingerprint,
                record=record,
                supersedes=tuple(sorted(active.get(key, ()), key=lambda ref: ref.evidence_id)),
            )
        )
    return tuple(planned)


def _gap(
    reason: str, reference: EvidenceReference, *nodes: InventoryNodeRef
) -> AcquisitionGapEvidence:
    return AcquisitionGapEvidence(
        gap=InventoryGap(
            reason=reason,
            node_keys=tuple(sorted(node.key for node in nodes)),
            evidence_ids=(reference.evidence_id,),
        ),
        evidence=reference,
    )


def _qualification_gaps(
    natives: tuple[QualifiedNative, ...], reference: EvidenceReference, owner: InventoryNodeRef
) -> list[AcquisitionGapEvidence]:
    gaps: list[AcquisitionGapEvidence] = []
    if any(not item.harnesses for item in natives):
        gaps.append(_gap("legacy_native_identity_unqualified", reference, owner))
    if any(len(item.harnesses) > 1 for item in natives):
        gaps.append(_gap("legacy_native_identity_ambiguous", reference, owner))
    return gaps


def _transcript(run: RunIdentity, harness: str, native: str) -> InventoryNodeRef:
    return InventoryNodeRef(
        kind="transcript",
        source_instance_id=run.source_instance_id,
        harness=harness,
        local_id=native,
    )


def _platform(run: RunIdentity, session_id: str) -> InventoryNodeRef:
    return InventoryNodeRef(
        kind="platform", source_instance_id=run.source_instance_id, local_id=session_id
    )


def _observation(
    run: RunIdentity, record: LegacyObservationRecord, reference: EvidenceReference
) -> SessionEvidence:
    platform = _platform(run, record.platform_session_id)

    def member(node: InventoryNodeRef) -> MembershipEvidence:
        # A capture sweep is scoped to the run but is not per-invocation proof.
        return MembershipEvidence(
            node=node,
            run=run,
            phase_id=record.phase_id,
            confidence=EvidenceClass.CANDIDATE,
            evidence=reference,
        )

    if record.natives is None:
        return SessionEvidence(
            run=run,
            nodes=(NodeEvidence(node=platform, evidence=reference),),
            memberships=(member(platform),),
            acquisition_gaps=(_gap("legacy_capture_unsupported", reference, platform),),
        )
    transcripts = [
        _transcript(run, item.harnesses[0], item.native_id)
        for item in record.natives
        if len(item.harnesses) == 1
    ]
    return SessionEvidence(
        run=run,
        nodes=(NodeEvidence(node=platform, evidence=reference),),
        memberships=tuple(member(node) for node in (platform, *transcripts)),
        acquisition_gaps=tuple(_qualification_gaps(record.natives, reference, platform)),
    )


def _delegate(
    run: RunIdentity, record: LegacyDelegateRecord, reference: EvidenceReference
) -> SessionEvidence:
    # The fixed import namespace. Reconstruction never re-derives or re-creates it.
    platform = _platform(run, platform_session_id_for(record.native.native_id))
    bindings: tuple[IdentityBindingEvidence, ...] = ()
    if len(record.native.harnesses) == 1:
        bindings = (
            IdentityBindingEvidence(
                owner=platform,
                transcript=_transcript(run, record.native.harnesses[0], record.native.native_id),
                confidence=EvidenceClass.CORROBORATED,
                evidence=reference,
            ),
        )
    return SessionEvidence(
        run=run,
        nodes=(NodeEvidence(node=platform, evidence=reference),),
        memberships=(
            MembershipEvidence(
                node=platform,
                run=run,
                confidence=EvidenceClass.CORROBORATED,
                evidence=reference,
            ),
        ),
        bindings=bindings,
        acquisition_gaps=tuple(_qualification_gaps((record.native,), reference, platform)),
    )


def _archive(
    run: RunIdentity, record: LegacyArchiveRecord, reference: EvidenceReference
) -> SessionEvidence:
    facts = record.facts
    if facts is None:
        # Discoverability survives expired bytes; parentage is not invented for them.
        if record.catalogued_native_id is None:
            return SessionEvidence(
                run=run, acquisition_gaps=(_gap("legacy_archive_body_missing", reference),)
            )
        lost = _transcript(run, record.harness, record.catalogued_native_id)
        return SessionEvidence(
            run=run,
            nodes=(NodeEvidence(node=lost, evidence=reference),),
            acquisition_gaps=(_gap("legacy_archive_body_missing", reference, lost),),
        )
    gaps = tuple(_gap(issue, reference) for issue in facts.issues)
    if facts.native_id is None:
        return SessionEvidence(run=run, acquisition_gaps=gaps)
    node = _transcript(run, record.harness, facts.native_id)
    return SessionEvidence(
        run=run,
        nodes=(NodeEvidence(node=node, evidence=reference),),
        native_transcripts=(
            NativeTranscriptObservation(
                node=node, facts=facts.model_copy(update={"issues": ()}), evidence=reference
            ),
        ),
        acquisition_gaps=gaps,
    )


def receipt_evidence(receipt: BackfillReceipt) -> EvidenceBatch:
    """Pure in the receipt, so a restarted append regenerates identical bytes."""
    reference = receipt.reference
    record = receipt.record
    if isinstance(record, LegacyObservationRecord):
        evidence = _observation(receipt.run, record, reference)
    elif isinstance(record, LegacyDelegateRecord):
        evidence = _delegate(receipt.run, record, reference)
    else:
        evidence = _archive(receipt.run, record, reference)
    retractions = tuple(
        EvidenceRetraction(target=target, evidence=reference) for target in receipt.supersedes
    )
    return EvidenceBatch(
        batch_id=reference.evidence_id,
        producer_id=BACKFILL_PRODUCER,
        evidence=evidence.model_copy(update={"retractions": retractions}),
    )
