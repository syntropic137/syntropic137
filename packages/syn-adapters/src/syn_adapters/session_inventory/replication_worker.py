"""Bounded live-only export work. Remote draining is separate from local enqueue."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from .replication_batch import replication_batch
from .replication_jobs import ReplicationLeaseLost

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import SessionInventoryReadPort

    from .exporter_transport import ExporterInventoryTransport, ReplicationDrain
    from .replication_jobs import PostgresReplicationJobs

logger = logging.getLogger(__name__)


class InventoryReplicationWorker:
    def __init__(
        self,
        jobs: PostgresReplicationJobs,
        inventory: SessionInventoryReadPort,
        transport: ExporterInventoryTransport,
        *,
        lease_seconds: int = 120,
        retry_seconds: int = 10,
    ) -> None:
        if lease_seconds < 1 or retry_seconds < 0:
            raise ValueError("invalid replication worker timing")
        self._jobs, self._inventory, self._transport = jobs, inventory, transport
        self._lease_seconds, self._retry_seconds = lease_seconds, retry_seconds

    async def enqueue_step(self) -> bool:
        """No network: checkpoint only after all operations have durable receipts."""
        await self._jobs.discover()
        lease = await self._jobs.claim(self._lease_seconds)
        if lease is None:
            return False
        try:
            batch = await replication_batch(self._inventory, lease.publication, offset=lease.offset)
            for operation in batch.operations:
                await self._jobs.renew(lease, self._lease_seconds)
                await self._transport.enqueue(operation)
            await self._jobs.advance(lease, next_offset=batch.next_offset)
        except Exception:
            # Credentials and subprocess output must never enter logs.
            logger.warning("Inventory export failed; its durable checkpoint remains retryable")
            with suppress(ReplicationLeaseLost):
                await self._jobs.advance(
                    lease, next_offset=lease.offset, retry_seconds=self._retry_seconds
                )
        return True

    async def drain_step(self) -> ReplicationDrain:
        """Run independently from reconciliation. The exporter retains failed HTTP work."""
        return await self._transport.drain(limit=50)
