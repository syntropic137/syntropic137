"""Execute one leased to-do item, then report the result to its aggregate."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import ReconciliationStage
from syn_domain.contexts.agent_sessions.domain.commands.AdvanceInventoryReconciliationCommand import (
    AdvanceInventoryReconciliationCommand,
)
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import PendingEvidence
from syn_domain.contexts.agent_sessions.ports.SessionInventoryWritePort import (
    InventoryPublicationConflict,
)

from .BuildInventorySnapshotHandler import EvidenceQuotaExceeded

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.aggregate_inventory_reconciliation.InventoryReconciliationAggregate import (
        InventoryReconciliationAggregate,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
        SessionEvidenceWritePort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionInventoryJobPort import (
        InventoryJobLease,
        SessionInventoryJobPort,
    )
    from syn_domain.repository import Repository

    from .BuildInventorySnapshotHandler import BuildInventorySnapshotHandler


class InventoryStepHandler:
    def __init__(
        self,
        repository: Repository[InventoryReconciliationAggregate],
        jobs: SessionInventoryJobPort,
        builder: BuildInventorySnapshotHandler,
        outbox: SessionEvidenceWritePort,
        *,
        lease_seconds: int,
    ) -> None:
        self._repository, self._jobs, self._builder = repository, jobs, builder
        self._lease_seconds = lease_seconds
        self._outbox = outbox

    async def handle(self, lease: InventoryJobLease) -> None:
        aggregate = await self._repository.get_by_id(lease.job.job_id)
        if aggregate is None:
            raise ValueError("projected inventory job has no management stream")
        if aggregate.state != lease.job.state:
            return  # Its newer management event has not reached this projection yet.
        try:
            command = await self._perform(lease)
        except EvidenceQuotaExceeded:
            command = self._failure(lease, "evidence_quota_exceeded")
        except InventoryPublicationConflict:
            request = lease.job.state.request
            if request.evidence_watermark > 0:
                # Queue the retry before recording failure. A crash between
                # stores leaves either retryable old work or a durable wakeup.
                await self._outbox.requeue(
                    PendingEvidence(run=request.run, watermark=request.evidence_watermark)
                )
            command = self._failure(lease, "publication_superseded")
        except ValueError:
            command = self._failure(lease, "invalid_evidence")
        await self._jobs.renew(lease, lease_seconds=self._lease_seconds)
        aggregate.advance(command)
        await self._repository.save(aggregate)

    async def _perform(self, lease: InventoryJobLease) -> AdvanceInventoryReconciliationCommand:
        if lease.job.state.stage is ReconciliationStage.PENDING:

            async def renew() -> None:
                await self._jobs.renew(lease, lease_seconds=self._lease_seconds)

            snapshot = await self._builder.handle(lease.job.state.request, on_progress=renew)
            return AdvanceInventoryReconciliationCommand(
                aggregate_id=lease.job.job_id,
                stage=ReconciliationStage.PUBLISHING,
                revision=snapshot.revision,
            )
        if lease.job.state.stage is ReconciliationStage.PUBLISHING:
            await self._jobs.publish(lease)
            return AdvanceInventoryReconciliationCommand(
                aggregate_id=lease.job.job_id,
                stage=ReconciliationStage.COMPLETED,
                revision=lease.job.state.revision,
            )
        raise ValueError("terminal inventory job cannot execute")

    @staticmethod
    def _failure(lease: InventoryJobLease, code: str) -> AdvanceInventoryReconciliationCommand:
        return AdvanceInventoryReconciliationCommand(
            aggregate_id=lease.job.job_id,
            stage=ReconciliationStage.FAILED,
            failure_code=code,
        )
