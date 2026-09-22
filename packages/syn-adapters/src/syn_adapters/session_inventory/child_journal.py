"""Persist normalized workspace child observations before acknowledging a page.

Workspace hooks are evidence, not host registrations. This adapter contributes
lineage and binding facts; it does not infer phase or run membership from them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import (
    EvidenceBatch,
    EvidenceClass,
    EvidenceReference,
    IdentityBindingEvidence,
    InventoryNodeRef,
    LineageEvidence,
    NodeEvidence,
    RunIdentity,
    SessionEvidence,
)

if TYPE_CHECKING:
    from agentic_isolation.child_journal import ChildChange, WorkspaceChildJournalReader

    from syn_domain.contexts.agent_sessions import SessionEvidenceWritePort


def child_evidence(change: ChildChange, run: RunIdentity, spool_id: str) -> EvidenceBatch:
    if not spool_id.strip():
        raise ValueError("Host-assigned spool identity is required")
    producer = "child-journal:" + hashlib.sha256(spool_id.encode()).hexdigest()
    reference = EvidenceReference(
        producer_id=producer,
        evidence_id=f"{producer}:{change.sequence}",
        source_revision=hashlib.sha256(change.model_dump_json().encode()).hexdigest(),
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
    bindings: tuple[IdentityBindingEvidence, ...] = ()
    if intent.child_native_id is not None:
        bindings = (
            IdentityBindingEvidence(
                owner=child,
                transcript=InventoryNodeRef(
                    kind="transcript",
                    source_instance_id=run.source_instance_id,
                    harness=intent.call.harness,
                    local_id=intent.child_native_id,
                ),
                confidence=EvidenceClass.CORROBORATED,
                evidence=reference,
            ),
        )
    return EvidenceBatch(
        batch_id=str(change.sequence),
        producer_id=producer,
        evidence=SessionEvidence(
            run=run,
            nodes=(NodeEvidence(node=child, evidence=reference),),
            edges=(
                LineageEvidence(
                    parent=parent,
                    child=child,
                    relation="spawn",
                    confidence=EvidenceClass.CORROBORATED,
                    evidence=reference,
                ),
            ),
            bindings=bindings,
        ),
    )


@dataclass(frozen=True)
class ChildDrainProgress:
    watermark: int
    next_after: int | None
    persisted: int


class ChildJournalDrain:
    def __init__(self, evidence: SessionEvidenceWritePort) -> None:
        self._evidence = evidence

    async def page(
        self,
        reader: WorkspaceChildJournalReader,
        *,
        run: RunIdentity,
        spool_id: str,
        after: int = 0,
        watermark: int | None = None,
    ) -> ChildDrainProgress:
        if not spool_id.strip():
            raise ValueError("Host-assigned spool identity is required")
        page = await reader.page(after, watermark)
        for change in page.changes:
            await self._evidence.append(child_evidence(change, run, spool_id))
        return ChildDrainProgress(page.watermark, page.next_after, len(page.changes))
