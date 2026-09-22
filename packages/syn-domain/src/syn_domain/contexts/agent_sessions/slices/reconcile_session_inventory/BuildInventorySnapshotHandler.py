"""One restartable infrastructure step: materialize a complete input watermark.

The management aggregate decides whether to build or publish. This handler
never exposes staged rows or dispatches workflow execution commands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.services.evidence_assembly import assemble_evidence
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    RESOLVER_VERSION,
    resolve_relationships,
)
from syn_domain.contexts.agent_sessions.ports.SessionInventoryReadPort import (
    InventoryCounts,
    InventoryItem,
    InventorySnapshot,
    ItemKind,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
        ReconciliationRequest,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
        SessionEvidenceReadPort,
        StoredEvidenceBatch,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionInventoryWritePort import (
        SessionInventoryWritePort,
    )


def _record_count(stored: StoredEvidenceBatch) -> int:
    evidence = stored.batch.evidence
    count = sum(
        len(items)
        for items in (
            evidence.nodes,
            evidence.invocation_contexts,
            evidence.memberships,
            evidence.edges,
            evidence.bindings,
            evidence.captures,
            evidence.retractions,
            evidence.acquisition_gaps,
        )
    )
    count += sum(1 + len(item.facts.relationships) for item in evidence.native_transcripts)
    if evidence.coverage_contract is not None:
        count += len(evidence.coverage_contract.expected_nodes)
    return count


class EvidenceQuotaExceeded(Exception):
    """Do not publish partial results; report a failed management job."""


class BuildInventorySnapshotHandler:
    def __init__(
        self,
        evidence: SessionEvidenceReadPort,
        inventory: SessionInventoryWritePort,
        *,
        max_evidence_records: int,
        max_evidence_batches: int,
    ) -> None:
        if max_evidence_records < 1 or max_evidence_batches < 1:
            raise ValueError("reconciliation quotas must be positive")
        self._evidence = evidence
        self._inventory = inventory
        self._max_records = max_evidence_records
        self._max_batches = max_evidence_batches

    async def _acquire(
        self, request: ReconciliationRequest, on_progress: Callable[[], Awaitable[None]] | None
    ) -> list[StoredEvidenceBatch]:
        batches: list[StoredEvidenceBatch] = []
        after = 0
        count = 0
        while True:
            page = await self._evidence.read(request.run, request.evidence_watermark, after=after)
            if page.watermark != request.evidence_watermark:
                raise ValueError("evidence reader changed the acquired watermark")
            count += sum(_record_count(stored) for stored in page.items)
            if count > self._max_records or len(batches) + len(page.items) > self._max_batches:
                raise EvidenceQuotaExceeded("evidence quota exceeded; prior inventory preserved")
            batches.extend(page.items)
            if on_progress is not None:
                await on_progress()
            if page.next_after is None:
                break
            if page.next_after <= after:
                raise ValueError("evidence reader did not advance its cursor")
            after = page.next_after
        if (batches[-1].sequence if batches else 0) != request.evidence_watermark:
            raise ValueError("evidence reader truncated the requested watermark")
        return batches

    async def handle(
        self,
        request: ReconciliationRequest,
        *,
        on_progress: Callable[[], Awaitable[None]] | None = None,
    ) -> InventorySnapshot:
        if request.resolver_version != RESOLVER_VERSION:
            raise ValueError("job requires another resolver version")
        batches = await self._acquire(request, on_progress)
        resolved = resolve_relationships(assemble_evidence(request.run, batches))
        snapshot = InventorySnapshot(
            snapshot_id=request.snapshot_id,
            run=request.run,
            revision=resolved.revision,
            resolver_version=resolved.resolver_version,
            evidence_watermark=request.evidence_watermark,
            coverage=resolved.coverage,
            counts=InventoryCounts(
                node=len(resolved.nodes),
                binding=len(resolved.bindings),
                membership=len(resolved.memberships),
                edge=len(resolved.edges),
                capture=len(resolved.captures),
                gap=len(resolved.gaps),
                retraction=len(resolved.retractions),
            ),
        )
        await self._inventory.stage(snapshot)
        groups: tuple[tuple[ItemKind, tuple[InventoryItem, ...]], ...] = (
            ("node", resolved.nodes),
            ("binding", resolved.bindings),
            ("membership", resolved.memberships),
            ("edge", resolved.edges),
            ("capture", resolved.captures),
            ("gap", resolved.gaps),
            ("retraction", resolved.retractions),
        )
        for kind, items in groups:
            for start in range(0, len(items), 500):
                if on_progress is not None:
                    await on_progress()
                await self._inventory.append(
                    request.run, request.snapshot_id, kind, start, items[start : start + 500]
                )
        return snapshot
