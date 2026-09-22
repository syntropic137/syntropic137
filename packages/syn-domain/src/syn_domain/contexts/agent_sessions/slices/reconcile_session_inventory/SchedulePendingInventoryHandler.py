"""Bridge the evidence outbox to idempotent event-sourced management commands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
)
from syn_domain.contexts.agent_sessions.domain.commands.RequestInventoryReconciliationCommand import (
    RequestInventoryReconciliationCommand,
)
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    RESOLVER_VERSION,
)

from .RequestInventoryReconciliationHandler import RequestInventoryReconciliationHandler

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.aggregate_inventory_reconciliation.InventoryReconciliationAggregate import (
        InventoryReconciliationAggregate,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
        PendingEvidence,
        SessionEvidenceWritePort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionInventoryReadPort import (
        SessionInventoryReadPort,
    )
    from syn_domain.repository import Repository


class SchedulePendingInventoryHandler:
    def __init__(
        self,
        outbox: SessionEvidenceWritePort,
        inventory: SessionInventoryReadPort,
        repository: Repository[InventoryReconciliationAggregate],
    ) -> None:
        self._outbox, self._inventory, self._repository = outbox, inventory, repository
        self._request = RequestInventoryReconciliationHandler(repository)

    async def handle(self) -> None:
        for item in await self._outbox.pending():
            await self._schedule(item)
            # If scheduling raises (including a concurrent first writer), leave
            # the wakeup durable. A later tick retries the same command identity.
            await self._outbox.acknowledge_dispatch(item)

    async def _schedule(self, item: PendingEvidence) -> None:
        head = await self._inventory.head(item.run)
        expected_head = None if head is None else head.snapshot_id
        identity = json.dumps(
            (
                "syn-session-reconciliation/1",
                item.run.source_instance_id,
                item.run.execution_id,
                item.watermark,
                RESOLVER_VERSION,
                str(expected_head) if expected_head is not None else None,
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        job_id = uuid5(NAMESPACE_URL, identity)
        await self._request.handle(
            RequestInventoryReconciliationCommand(
                aggregate_id=str(job_id),
                request=ReconciliationRequest(
                    run=item.run,
                    evidence_watermark=item.watermark,
                    expected_head=expected_head,
                    snapshot_id=job_id,
                    resolver_version=RESOLVER_VERSION,
                ),
            )
        )
