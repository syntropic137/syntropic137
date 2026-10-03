"""Test-only twins of the Postgres jobs and inventory adapters.

``InMemorySessionInventoryJobs`` keeps the same claim, lease and re-arm rules as
``PostgresSessionInventoryJobs``. ``publish`` then makes the same judgements as
``postgres_jobs.publish`` and ``postgres_publication.publish_snapshot``: a
matching staged snapshot, complete items, evidence no older than the head, and
an atomic compare-and-swap of the run's head against ``expected_head``. A test
that publishes against the wrong head or an unstaged revision fails here as it
would in production. Not modelled: namespace counts derived from stored nodes,
and the replication sequence.
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
    InventoryNotFound,
    InventoryPublicationConflict,
    InventorySnapshot,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationStage,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_domain.contexts.agent_sessions import InventoryItem, ItemKind

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
    parent_snapshot_id: UUID | None
    revision_sequence: int


@dataclass
class _Staged:
    snapshot: InventorySnapshot
    items: dict[tuple[ItemKind, int], InventoryItem]
    published: bool = False


class InMemorySessionInventory(InMemoryAdapter):
    """Staged snapshots, items and per-run heads, published as ``publish_snapshot`` does."""

    def __init__(self) -> None:
        super().__init__()
        self._staged: dict[tuple[RunIdentity, UUID], _Staged] = {}
        self._heads: dict[RunIdentity, UUID] = {}
        self.publications: list[Publication] = []

    async def head(self, run: RunIdentity) -> InventorySnapshot | None:
        head = self._heads.get(run)
        return None if head is None else self._staged[(run, head)].snapshot

    async def staged(self, run: RunIdentity, snapshot_id: UUID) -> InventorySnapshot | None:
        staged = self._staged.get((run, snapshot_id))
        return None if staged is None else staged.snapshot

    async def stage(self, snapshot: InventorySnapshot) -> None:
        stored = self._staged.setdefault(
            (snapshot.run, snapshot.snapshot_id), _Staged(snapshot=snapshot, items={})
        )
        if stored.snapshot.without_derived_counts() != snapshot.without_derived_counts():
            raise InventoryPublicationConflict("snapshot identity reused with different metadata")

    async def append(
        self,
        run: RunIdentity,
        snapshot_id: UUID,
        kind: ItemKind,
        start: int,
        items: tuple[InventoryItem, ...],
    ) -> None:
        if start < 0 or not 1 <= len(items) <= 500:
            raise ValueError("batch must have 1..500 items and a nonnegative start")
        staged = self._staged.get((run, snapshot_id))
        if staged is None:
            raise InventoryNotFound("unknown staged snapshot")
        if start + len(items) > getattr(staged.snapshot.counts, kind):
            raise ValueError("batch exceeds declared snapshot size")
        for offset, item in enumerate(items, start):
            if staged.items.setdefault((kind, offset), item) != item:
                raise InventoryPublicationConflict("inventory item position reused")

    async def publish(
        self, run: RunIdentity, snapshot_id: UUID, expected_head: UUID | None
    ) -> None:
        current = self._heads.get(run)
        if current == snapshot_id:
            return  # Retry after a committed response was lost.
        if current != expected_head:
            raise InventoryPublicationConflict("inventory head changed during reconciliation")
        staged = self._staged.get((run, snapshot_id))
        if staged is None or staged.published:
            raise InventoryNotFound("no unpublished snapshot in this run")
        snapshot = staged.snapshot
        if current is not None and (
            snapshot.evidence_watermark < self._staged[(run, current)].snapshot.evidence_watermark
        ):
            raise InventoryPublicationConflict("input evidence predates the published head")
        for kind in ("node", "membership", "edge", "capture", "gap", "retraction", "binding"):
            stored = sum(1 for item_kind, _ in staged.items if item_kind == kind)
            if stored != getattr(snapshot.counts, kind):
                raise InventoryPublicationConflict("snapshot still has uncommitted batches")
        sequence = 1
        if expected_head is not None:
            parent = next(
                (p for p in self.publications if p.run == run and p.snapshot_id == expected_head),
                None,
            )
            if parent is None:
                raise InventoryPublicationConflict(
                    "published head has no durable publication order"
                )
            sequence = parent.revision_sequence + 1
        staged.published = True
        self._heads[run] = snapshot_id
        self.publications.append(
            Publication(
                run=run,
                snapshot_id=snapshot_id,
                parent_snapshot_id=expected_head,
                revision_sequence=sequence,
            )
        )


class InMemorySessionInventoryJobs(InMemoryAdapter):
    def __init__(
        self, inventory: InMemorySessionInventory, clock: Callable[[], float] = time.monotonic
    ) -> None:
        super().__init__()
        self._inventory = inventory
        self._clock = clock
        self._rows: dict[str, _Row] = {}

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
        snapshot = await self._inventory.staged(request.run, request.snapshot_id)
        if snapshot is None:
            raise InventoryPublicationConflict("publishing job has no staged snapshot")
        if (snapshot.revision, snapshot.resolver_version, snapshot.evidence_watermark) != (
            lease.job.state.revision,
            request.resolver_version,
            request.evidence_watermark,
        ):
            raise InventoryPublicationConflict("staged snapshot does not match the publishing job")
        await self._inventory.publish(request.run, request.snapshot_id, request.expected_head)

    def _held(self, lease: InventoryJobLease) -> _Row | None:
        row = self._rows.get(lease.job.job_id)
        return row if row is not None and row.lease_token == lease.token else None
