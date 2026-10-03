"""Test-only twin of ``PostgresSessionInventoryJobs``: the same claim, lease and re-arm rules.

Inventory heads are not modelled, so ``publish`` checks the lease exactly as the
SQL does and records the publication instead of swapping a head.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003 - dataclass field

from syn_adapters.in_memory import InMemoryAdapter
from syn_domain.contexts.agent_sessions import (
    InventoryJob,
    InventoryJobLease,
    InventoryLeaseLost,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationStage,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_OPEN = (ReconciliationStage.PENDING, ReconciliationStage.PUBLISHING)


@dataclass
class _Row:
    job: InventoryJob
    lease_token: int = 0
    leased_until: float = -math.inf
    retry_at: float = -math.inf


@dataclass(frozen=True)
class Publication:
    run: RunIdentity
    snapshot_id: UUID


class InMemorySessionInventoryJobs(InMemoryAdapter):
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self._clock = clock
        self._rows: dict[str, _Row] = {}
        self.published: list[Publication] = []

    async def project(self, job: InventoryJob) -> None:
        row = self._rows.get(job.job_id)
        if row is None:
            self._rows[job.job_id] = _Row(job=job)
        elif row.job.global_position < job.global_position:
            self._rows[job.job_id] = _Row(job=job, lease_token=row.lease_token + 1)

    async def get(self, job_id: str) -> InventoryJob | None:
        row = self._rows.get(job_id)
        return None if row is None else row.job

    async def find_ids(self, source_instance_id: str, prefix: str) -> tuple[str, ...]:
        if not prefix or len(prefix) > 36:
            return ()
        ids = sorted(
            job_id
            for job_id, row in self._rows.items()
            if row.job.state.request.run.source_instance_id == source_instance_id
            and job_id.startswith(prefix)
        )
        return (prefix,) if prefix in ids else tuple(ids[:2])

    async def latest(self, run: RunIdentity) -> InventoryJob | None:
        rows = [row for row in self._rows.values() if row.job.state.request.run == run]
        return max(rows, key=lambda row: row.job.global_position).job if rows else None

    async def claim(self, *, lease_seconds: int) -> InventoryJobLease | None:
        if lease_seconds < 1:
            raise ValueError("lease duration must be positive")
        now = self._clock()
        due = [
            row
            for row in self._rows.values()
            if row.job.state.stage in _OPEN and row.retry_at <= now and row.leased_until <= now
        ]
        if not due:
            return None
        row = min(due, key=lambda r: (r.retry_at, r.job.global_position))
        row.lease_token += 1
        row.leased_until = now + lease_seconds
        return InventoryJobLease(job=row.job, token=row.lease_token)

    async def renew(self, lease: InventoryJobLease, *, lease_seconds: int) -> None:
        if lease_seconds < 1:
            raise ValueError("lease duration must be positive")
        row = self._held(lease)
        if row is None or row.leased_until <= self._clock():
            raise InventoryLeaseLost("inventory lease expired or was superseded")
        row.leased_until = self._clock() + lease_seconds

    async def release(self, lease: InventoryJobLease, *, retry_seconds: int) -> None:
        if retry_seconds < 0:
            raise ValueError("retry delay cannot be negative")
        row = self._held(lease)
        if row is not None:
            row.leased_until, row.retry_at = -math.inf, self._clock() + retry_seconds

    async def park(self, lease: InventoryJobLease) -> None:
        row = self._held(lease)
        if row is not None:
            row.leased_until, row.retry_at = -math.inf, math.inf

    async def publish(self, lease: InventoryJobLease) -> None:
        row = self._held(lease)
        if (
            row is None
            or row.leased_until <= self._clock()
            or row.job.state.stage is not ReconciliationStage.PUBLISHING
            or row.job != lease.job
        ):
            raise InventoryLeaseLost("publication requires the current publishing lease")
        request = lease.job.state.request
        self.published.append(Publication(run=request.run, snapshot_id=request.snapshot_id))

    def _held(self, lease: InventoryJobLease) -> _Row | None:
        row = self._rows.get(lease.job.job_id)
        return row if row is not None and row.lease_token == lease.token else None
