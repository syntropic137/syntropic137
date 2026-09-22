"""Append-only normalized evidence and its durable reconciliation outbox."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field, model_validator

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    SessionEvidence,  # noqa: TC001 - runtime Pydantic field on InventoryModel subclass
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    InventoryModel,
    RoutingIdentifier,
    RunIdentity,
)


class EvidenceBatch(InventoryModel):
    batch_id: RoutingIdentifier
    producer_id: RoutingIdentifier
    evidence: SessionEvidence

    @model_validator(mode="after")
    def _bounded(self) -> EvidenceBatch:
        source = self.evidence
        count = sum(
            len(records)
            for records in (
                source.nodes,
                source.invocation_contexts,
                source.memberships,
                source.edges,
                source.bindings,
                source.captures,
                source.retractions,
                source.acquisition_gaps,
                source.acquisition_statuses,
            )
        )
        count += sum(1 + len(item.facts.relationships) for item in source.native_transcripts)
        if source.coverage_contract is not None:
            count += len(source.coverage_contract.expected_nodes)
        if count > 500:
            raise ValueError("evidence batch exceeds 500 normalized records")
        return self


class StoredEvidenceBatch(InventoryModel):
    sequence: int = Field(ge=1)
    batch: EvidenceBatch


class EvidencePage(InventoryModel):
    watermark: int = Field(ge=0)
    items: tuple[StoredEvidenceBatch, ...]
    next_after: int | None = Field(default=None, ge=1)


class PendingEvidence(InventoryModel):
    run: RunIdentity
    watermark: int = Field(ge=1)


class SessionEvidenceReadPort(Protocol):
    async def watermark(self, run: RunIdentity) -> int: ...

    async def read(
        self, run: RunIdentity, watermark: int, *, after: int = 0, limit: int = 100
    ) -> EvidencePage: ...


class SessionEvidenceWritePort(Protocol):
    async def append(self, batch: EvidenceBatch) -> int:
        """Persist evidence and outbox watermark atomically before acknowledging."""
        ...

    async def pending(self, *, limit: int = 100) -> tuple[PendingEvidence, ...]: ...

    async def acknowledge_dispatch(self, item: PendingEvidence) -> None:
        """Call only AFTER an idempotent management command is durably recorded."""
        ...

    async def requeue(self, item: PendingEvidence) -> None:
        """Recover a publication superseded by a different input revision."""
        ...
