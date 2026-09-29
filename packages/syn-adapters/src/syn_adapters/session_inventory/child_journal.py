"""Persist normalized workspace child observations before acknowledging a page.

Workspace hooks are evidence, not host registrations. This adapter contributes
lineage and binding facts; it does not infer phase or run membership from them.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.agent_sessions import (
    AcquisitionStatusEvidence,
    EvidenceBatch,
    EvidenceClass,
    EvidenceReference,
    IdentityBindingEvidence,
    InventoryNodeRef,
    InvocationContextEvidence,
    InvocationLifecycleEvidence,
    LaunchFailureReason,
    LineageEvidence,
    NodeEvidence,
    RunIdentity,
    SessionEvidence,
)

if TYPE_CHECKING:
    from agentic_isolation.child_journal import ChildChange, WorkspaceChildJournalReader

logger = logging.getLogger(__name__)


class ChildEvidenceWriter(Protocol):
    async def append(self, batch: EvidenceBatch) -> int: ...

    async def observe_acquisition(self, batch: EvidenceBatch) -> int: ...


def child_evidence(change: ChildChange, run: RunIdentity, spool_id: str) -> EvidenceBatch:
    if not spool_id.strip():
        raise ValueError("Host-assigned spool identity is required")
    producer = "child-journal:" + hashlib.sha256(spool_id.encode()).hexdigest()
    reference = EvidenceReference(
        producer_id=producer,
        evidence_id=f"{producer}:{change.sequence}",
        source_revision=hashlib.sha256(
            change.model_dump_json(exclude_defaults=True).encode()
        ).hexdigest(),
        locator=f"child_changes/{change.sequence}",
        extractor_version="agentic-child-journal/1",
    )
    intent = change.intent
    parent = InventoryNodeRef(
        kind="transcript",
        source_instance_id=run.source_instance_id,
        harness=intent.call.harness,
        local_id=intent.call.parent_native_id,
    )
    child = InventoryNodeRef(
        kind="invocation",
        source_instance_id=run.source_instance_id,
        local_id=intent.child_invocation_id,
    )
    child_harness = intent.call.target_harness or intent.call.harness

    def transcript(native_id: str) -> InventoryNodeRef:
        return InventoryNodeRef(
            kind="transcript",
            source_instance_id=run.source_instance_id,
            harness=child_harness,
            local_id=native_id,
        )

    bindings: list[IdentityBindingEvidence] = []
    if intent.child_native_id is not None:
        bindings.append(
            IdentityBindingEvidence(
                owner=child,
                transcript=transcript(intent.child_native_id),
                confidence=EvidenceClass.CORROBORATED,
                evidence=reference,
            )
        )
    if change.conflict_native_id is not None:
        # Schema v3: a different identity was observed for an already-bound
        # intent. The journal kept its binding; the rejected identity is
        # conflicting evidence, never a corroborated binding.
        bindings.append(
            IdentityBindingEvidence(
                owner=child,
                transcript=transcript(change.conflict_native_id),
                confidence=EvidenceClass.CONFLICTING,
                evidence=reference,
            )
        )
    return EvidenceBatch(
        batch_id=str(change.sequence),
        producer_id=producer,
        evidence=SessionEvidence(
            run=run,
            nodes=(NodeEvidence(node=child, evidence=reference),),
            invocation_contexts=(
                InvocationContextEvidence(
                    controller=InventoryNodeRef(
                        kind="invocation",
                        source_instance_id=run.source_instance_id,
                        local_id=intent.call.invocation_id,
                    ),
                    child=child,
                    attempt_id=intent.call.attempt_id,
                    evidence=reference,
                ),
            ),
            edges=(
                LineageEvidence(
                    parent=parent,
                    child=child,
                    relation="spawn",
                    confidence=EvidenceClass.CORROBORATED,
                    evidence=reference,
                ),
            ),
            bindings=tuple(bindings),
        ),
    )


def launch_failure_reason(value: str | None) -> LaunchFailureReason | None:
    """Translate the journal's wire reason; an unknown one stays a generic failure."""
    if value is None:
        return None
    try:
        return LaunchFailureReason(value)
    except ValueError:
        logger.warning("Unknown child launch failure reason %r; recording it as generic", value)
        return None


def child_lifecycle_evidence(
    change: ChildChange, run: RunIdentity, spool_id: str
) -> EvidenceBatch | None:
    """Separate producer preserves immutable pre-lifecycle journal batches on replay.

    Schema v3 adds ``pending`` (a native intent whose launch was never
    acknowledged) and a named ``reason`` on ``launch_failed``; both are carried
    so the resolver can report them as explicit gaps.
    """
    if change.intent.status is None:
        return None
    original = child_evidence(change, run, spool_id)
    producer = original.producer_id.replace("child-journal:", "child-lifecycle:", 1)
    reference = original.evidence.nodes[0].evidence.model_copy(
        update={
            "producer_id": producer,
            "evidence_id": f"{producer}:{change.sequence}",
            "extractor_version": "agentic-child-lifecycle/1",
        }
    )
    return EvidenceBatch(
        batch_id=str(change.sequence),
        producer_id=producer,
        evidence=SessionEvidence(
            run=run,
            invocation_lifecycle=(
                InvocationLifecycleEvidence(
                    node=original.evidence.nodes[0].node,
                    sequence=change.sequence,
                    status=change.intent.status,
                    exit_code=change.intent.exit_code,
                    reason=launch_failure_reason(change.intent.reason),
                    evidence=reference,
                ),
            ),
        ),
    )


def child_read_status(
    run: RunIdentity, spool_id: str, sequence: int, *, failed: bool
) -> EvidenceBatch:
    producer = "child-journal:" + hashlib.sha256(spool_id.encode()).hexdigest()
    batch_id = f"read:{sequence}"
    reference = EvidenceReference(
        producer_id=producer,
        evidence_id=f"{producer}:{batch_id}",
        source_revision=str(sequence),
        locator="children.sqlite",
        extractor_version="host-child-recovery/1",
    )
    return EvidenceBatch(
        batch_id=batch_id,
        producer_id=producer,
        evidence=SessionEvidence(
            run=run,
            acquisition_statuses=(
                AcquisitionStatusEvidence(
                    stream_id="child-journal-read",
                    sequence=sequence,
                    failed=failed,
                    reason="child_journal_unreadable",
                    evidence=reference,
                ),
            ),
        ),
    )


@dataclass(frozen=True)
class ChildDrainProgress:
    watermark: int
    next_after: int | None
    persisted: int


class ChildJournalDrain:
    def __init__(self, evidence: ChildEvidenceWriter) -> None:
        self._evidence = evidence

    async def page(
        self,
        reader: WorkspaceChildJournalReader,
        *,
        run: RunIdentity,
        spool_id: str,
        observation_sequence: int,
        after: int = 0,
        watermark: int | None = None,
    ) -> ChildDrainProgress:
        if not spool_id.strip():
            raise ValueError("Host-assigned spool identity is required")
        success = child_read_status(run, spool_id, observation_sequence, failed=False)
        try:
            page = await reader.page(after, watermark)
        except Exception:
            await self._evidence.observe_acquisition(
                child_read_status(run, spool_id, observation_sequence, failed=True)
            )
            raise
        for change in page.changes:
            await self._evidence.append(child_evidence(change, run, spool_id))
            lifecycle = child_lifecycle_evidence(change, run, spool_id)
            if lifecycle is not None:
                await self._evidence.append(lifecycle)
        await self._evidence.observe_acquisition(success)
        return ChildDrainProgress(page.watermark, page.next_after, len(page.changes))
