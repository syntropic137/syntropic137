"""Bridge the evidence outbox to idempotent event-sourced management commands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
    ReconciliationStage,
    ReconciliationState,
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
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import RunIdentity
    from syn_domain.contexts.agent_sessions.ports.InventorySchedulingGuardPort import (
        InventorySchedulingGuardPort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
        PendingEvidence,
        SessionEvidenceWritePort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionInventoryJobPort import (
        SessionInventoryJobPort,
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
        jobs: SessionInventoryJobPort,
        guard: InventorySchedulingGuardPort,
    ) -> None:
        self._outbox, self._inventory, self._repository = outbox, inventory, repository
        self._jobs, self._guard = jobs, guard
        self._request = RequestInventoryReconciliationHandler(repository)

    async def handle(self) -> None:
        for item in await self._outbox.pending():
            await self._dispatch(item)

    async def _dispatch(self, item: PendingEvidence) -> None:
        # The open-job check and the schedule are one step per run (#1534).
        # Without the guard, two managers holding different watermarks for the
        # run both see no open job and open two jobs (distinct identities, so
        # nothing collides); the later one only loses at publication.
        async with self._guard.hold(item.run) as schedule:
            if schedule is None:
                # Another manager is scheduling this run right now. Skip it this
                # tick without acknowledging: the wakeup stays durable, exactly
                # as in the coalesce branch below.
                return
            last = await schedule.last_scheduled()
            recorded = None if last is None else await self._repository.get_by_id(last.aggregate_id)
            if last is not None and recorded is None:
                # The recorded job's stream is absent, but its save may still be
                # committing: a failed Append is not proof it never lands
                # (#2254). Retry exactly that job, never a successor at a newer
                # watermark; the same identity cannot open a second stream. The
                # job is now open, so the wakeup stays, as in the coalesce below.
                await self._request.handle(last)
                return
            if await self._in_flight(item.run, recorded):
                # Coalesce (#1528). The open job fixed its expected head before
                # this evidence arrived, so a second job for the run now could
                # only lose the head race to it (publication_superseded). The
                # wakeup stays undispatched; the outbox keeps one row per run at
                # the latest watermark, so once the open job ends the next tick
                # schedules everything that arrived meanwhile, against the head
                # that job published.
                return
            command = await self._command(item)
            # Recorded before the save, whole: a save that fails or whose
            # outcome is unknown leaves this request on record, and the next
            # holder retries it above instead of scheduling past it.
            await schedule.record_scheduled(command)
            await self._request.handle(command)
            # If scheduling raises (including a concurrent first writer), leave
            # the wakeup durable. A later tick retries the same command identity.
            await self._outbox.acknowledge_dispatch(item)

    async def _in_flight(
        self, run: RunIdentity, recorded: InventoryReconciliationAggregate | None
    ) -> bool:
        # The projection lags the schedule, so a job scheduled moments ago may
        # not be in it yet (#2254). The run's last scheduled job is read from
        # its own stream instead, which reflects every save; the projection
        # still covers jobs scheduled before that record existed.
        if recorded is not None and _open(recorded.state):
            return True
        latest = await self._jobs.latest(run)
        return latest is not None and _open(latest.state)

    async def _command(self, item: PendingEvidence) -> RequestInventoryReconciliationCommand:
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
        return RequestInventoryReconciliationCommand(
            aggregate_id=str(job_id),
            request=ReconciliationRequest(
                run=item.run,
                evidence_watermark=item.watermark,
                expected_head=expected_head,
                snapshot_id=job_id,
                resolver_version=RESOLVER_VERSION,
            ),
        )


def _open(state: ReconciliationState | None) -> bool:
    return state is not None and state.stage in (
        ReconciliationStage.PENDING,
        ReconciliationStage.PUBLISHING,
    )
