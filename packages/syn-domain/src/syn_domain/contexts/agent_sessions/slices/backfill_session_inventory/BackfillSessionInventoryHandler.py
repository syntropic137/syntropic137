"""Acquire historical evidence once, journal it, then reuse live reconciliation.

Restart-safe by construction: receipts are durable and reused, journal appends
are idempotent per receipt, and the reconciliation job is keyed by the caller's
idempotency key. There is no separate backfill resolver and no billing access.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    InventoryModel,
)
from syn_domain.contexts.agent_sessions.ports.BackfillReceiptPort import BackfillReceiptConflict

from .legacy_normalization import plan_receipts, qualify, receipt_evidence

if TYPE_CHECKING:
    from uuid import UUID

    from syn_domain.contexts.agent_sessions.domain.read_models.legacy_evidence import (
        BackfillReceipt,
        LegacyRecord,
    )
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
        RunIdentity,
    )
    from syn_domain.contexts.agent_sessions.ports.BackfillReceiptPort import BackfillReceiptPort
    from syn_domain.contexts.agent_sessions.ports.HistoricalEvidenceSourcePort import (
        HistoricalEvidenceSourcePort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
        SessionEvidenceWritePort,
    )
    from syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.RefreshSessionInventoryHandler import (
        RefreshSessionInventoryHandler,
    )


class BackfillResult(InventoryModel):
    job_id: str
    receipts: int = Field(ge=0)
    materialized: int = Field(ge=0)
    evidence_watermark: int = Field(ge=0)


def _validated_key(key: str) -> str:
    if not key.strip() or len(key) > 200 or "\x00" in key:
        raise ValueError("idempotency key must be nonblank, NUL-free, and at most 200 characters")
    return key


def backfill_snapshot_id(run: RunIdentity, idempotency_key: str) -> UUID:
    identity = json.dumps(
        [
            "session-history-backfill/1",
            run.source_instance_id,
            run.execution_id,
            _validated_key(idempotency_key),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return uuid5(NAMESPACE_URL, identity)


def backfill_refresh_key(idempotency_key: str) -> str:
    """A separate namespace: a plain refresh key never aliases a backfill job."""
    digest = hashlib.sha256(_validated_key(idempotency_key).encode()).hexdigest()
    return f"session-history-backfill/{digest}"


class BackfillSessionInventoryHandler:
    def __init__(
        self,
        source: HistoricalEvidenceSourcePort,
        receipts: BackfillReceiptPort,
        journal: SessionEvidenceWritePort,
        refresh: RefreshSessionInventoryHandler,
        *,
        max_plan_attempts: int = 5,
    ) -> None:
        if max_plan_attempts < 1:
            raise ValueError("backfill needs at least one materialization attempt")
        self._source, self._receipts, self._journal = source, receipts, journal
        self._refresh = refresh
        self._attempts = max_plan_attempts

    async def _materialize(
        self, run: RunIdentity, snapshot_id: UUID, records: tuple[LegacyRecord, ...]
    ) -> tuple[BackfillReceipt, ...]:
        for _ in range(self._attempts):
            existing = await self._receipts.existing(run)
            planned = plan_receipts(run, snapshot_id, records, existing)
            if not planned:
                return existing
            try:
                await self._receipts.insert(run, planned)
            except BackfillReceiptConflict:
                continue  # A concurrent materializer won; plan against its receipts.
            return (*existing, *planned)
        raise BackfillReceiptConflict("backfill receipts kept changing; retry later")

    async def handle(self, run: RunIdentity, idempotency_key: str) -> BackfillResult:
        snapshot_id = backfill_snapshot_id(run, idempotency_key)
        refresh_key = backfill_refresh_key(idempotency_key)
        acquisition = await self._source.acquire(run)
        if acquisition.run != run:
            raise ValueError("historical source answered for another run")
        before = await self._receipts.existing(run)
        receipts = await self._materialize(run, snapshot_id, qualify(acquisition, before))
        watermark = 0
        # Every receipt, not only new ones: a crash after materialization but
        # before its append is repaired here. Re-appends return the prior sequence.
        for receipt in receipts:
            watermark = max(watermark, await self._journal.append(receipt_evidence(receipt)))
        job_id = await self._refresh.handle(run, refresh_key)
        return BackfillResult(
            job_id=job_id,
            receipts=len(receipts),
            materialized=len(receipts) - len(before),
            evidence_watermark=watermark,
        )
