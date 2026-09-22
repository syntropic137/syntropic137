"""Explicit local refresh freezes inputs once for each run-scoped caller key."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
)
from syn_domain.contexts.agent_sessions.domain.aggregate_inventory_reconciliation.InventoryReconciliationAggregate import (
    InventoryReconciliationAggregate,
)
from syn_domain.contexts.agent_sessions.domain.commands.RequestInventoryReconciliationCommand import (
    RequestInventoryReconciliationCommand,
)
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    RESOLVER_VERSION,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import RunIdentity
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
        SessionEvidenceReadPort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionInventoryReadPort import (
        SessionInventoryReadPort,
    )
    from syn_domain.repository import Repository


class RefreshSessionInventoryHandler:
    def __init__(
        self,
        repository: Repository[InventoryReconciliationAggregate],
        evidence: SessionEvidenceReadPort,
        inventory: SessionInventoryReadPort,
    ) -> None:
        self._repository, self._evidence, self._inventory = repository, evidence, inventory

    async def handle(self, run: RunIdentity, idempotency_key: str) -> str:
        if not idempotency_key.strip() or len(idempotency_key) > 200 or "\x00" in idempotency_key:
            raise ValueError(
                "idempotency key must be nonblank, NUL-free, and at most 200 characters"
            )
        identity = json.dumps(
            [
                "session-inventory-refresh/1",
                run.source_instance_id,
                run.execution_id,
                idempotency_key,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        job_id = uuid5(NAMESPACE_URL, identity)
        if await self._exists(str(job_id), run):
            return str(job_id)
        head = await self._inventory.head(run)
        watermark = await self._evidence.watermark(run)
        aggregate = InventoryReconciliationAggregate()
        aggregate.request(
            RequestInventoryReconciliationCommand(
                aggregate_id=str(job_id),
                request=ReconciliationRequest(
                    run=run,
                    evidence_watermark=watermark,
                    expected_head=head.snapshot_id if head is not None else None,
                    snapshot_id=job_id,
                    resolver_version=RESOLVER_VERSION,
                ),
            )
        )
        try:
            await self._repository.save_new(aggregate)
        except Exception:
            # Resolve concurrent first writers and ambiguous acknowledgements
            # against the durable stream. Never replace its frozen inputs.
            if not await self._exists(str(job_id), run):
                raise
        return str(job_id)

    async def _exists(self, job_id: str, run: RunIdentity) -> bool:
        existing = await self._repository.get_by_id(job_id)
        if existing is None:
            return False
        if existing.state is None or existing.state.request.run != run:
            raise ValueError("refresh identity conflicts with existing management state")
        return True
