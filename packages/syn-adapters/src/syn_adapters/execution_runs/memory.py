"""Test double for the Run Queue. Same guards as Postgres; refuses production (ADR-060)."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from syn_adapters.in_memory import InMemoryAdapter
from syn_domain.contexts.orchestration.ports import (
    ClaimedRun,
    ExecutorHost,
    ExecutorPool,
    FencedRun,
    OpeningSweep,
    PoolDefinitionConflict,
    RunCounts,
    RunLeaseLost,
    RunWorkload,
    StreamPresence,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from syn_domain.contexts.orchestration.ports import ExecutionStreamProbe

_NEVER = datetime.min.replace(tzinfo=UTC)


class _Host(BaseModel):
    """One executor's ``executor_hosts`` and ``execution_budget`` rows, replaced on change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: ExecutorHost
    capacity: int
    registered_at: datetime
    in_use: int = 0
    heartbeat_at: datetime = _NEVER
    draining: bool = False
    registered: bool = True
    successor_id: str | None = None
    claim_checked_at: datetime = _NEVER
    full_since: datetime | None = None
    create_failures: int = 0
    claims_disabled_until: datetime | None = None
    breaker_cooldown: timedelta = timedelta(0)


class _Run(BaseModel):
    """One ``execution_runs`` row, replaced on every transition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    is_resume: bool
    writer_epoch: int
    opened_at: datetime
    state: str = "opening"
    executor_id: str | None = None
    reconciler: str | None = None
    token: int = 0
    leased_until: datetime = _NEVER
    retry_at: datetime = _NEVER
    admitted_at: datetime | None = None
    reader_epoch: int | None = None
    reason: str | None = None
    workload: RunWorkload = RunWorkload.AGENT
    placed_pool: str | None = None
    overflowed: bool | None = None
    claimed_at: datetime | None = None


class InMemoryExecutionRunQueue(InMemoryAdapter):
    def __init__(
        self,
        *,
        lease_ttl: timedelta = timedelta(seconds=90),
        heartbeat_stale: timedelta = timedelta(seconds=90),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__()
        self._ttl, self._stale, self._now = lease_ttl, heartbeat_stale, clock
        self._hosts: dict[str, _Host] = {}
        self._pools: dict[str, ExecutorPool] = {}
        self._runs: dict[str, _Run] = {}
        self._lock = asyncio.Lock()

    async def register(self, host: ExecutorHost, capacity: int) -> None:
        if capacity < 0:
            raise ValueError("executor capacity must be nonnegative")
        held = {
            other_id: other
            for other_id, other in self._hosts.items()
            if other.host.container_id == host.container_id and other_id != host.host_id
        }
        self._join_pool(host, retired=held.keys())
        if host.host_id not in self._hosts and held:
            capacity = sum(other.capacity - other.in_use for other in held.values())
            for other_id, other in held.items():
                self._budget(other_id, other, capacity=other.in_use, successor_id=host.host_id)
        for other_id in held:
            self._hosts[other_id] = self._hosts[other_id].model_copy(update={"registered": False})
        if host.host_id not in self._hosts:
            self._budget(
                host.host_id, _Host(host=host, capacity=capacity, registered_at=self._now())
            )

    def _join_pool(self, host: ExecutorHost, retired: Iterable[str]) -> None:
        """Postgres's rule (D13); ``retired`` are this container's predecessors, already gone."""
        declared = host.pool
        held = self._pools.setdefault(declared.pool_id, declared)
        if held == declared:
            return
        now, gone = self._now(), set(retired)
        if any(
            other.registered
            and not other.draining
            and other_id != host.host_id
            and other_id not in gone
            and other.host.pool.pool_id == declared.pool_id
            and max(other.heartbeat_at, other.registered_at) > now - self._stale
            for other_id, other in self._hosts.items()
        ):
            raise PoolDefinitionConflict(
                f"executor {host.host_id!r} declares Executor Pool {declared!r}, "
                f"but live members hold {held!r}; drain them or declare the same definition"
            )
        self._pools[declared.pool_id] = declared

    async def deregister(self, host_id: str) -> None:
        if host_id in self._hosts:
            self._hosts[host_id] = self._hosts[host_id].model_copy(update={"registered": False})

    async def heartbeat(self, host_id: str) -> bool:
        entry = self._hosts.get(host_id)
        if entry is None or not entry.registered:
            raise LookupError(f"executor {host_id!r} is not registered")
        self._hosts[host_id] = entry.model_copy(update={"heartbeat_at": self._now()})
        return entry.draining

    async def is_draining(self, host_id: str) -> bool:
        entry = self._hosts.get(host_id)
        return entry is not None and entry.registered and entry.draining

    async def others_live(self, host_id: str) -> bool:
        cutoff = self._now() - self._stale
        return any(
            other_id != host_id and entry.registered and entry.heartbeat_at > cutoff
            for other_id, entry in self._hosts.items()
        )

    async def reserve(
        self,
        execution_id: str,
        writer_epoch: int,
        *,
        is_resume: bool,
        workload: RunWorkload = RunWorkload.AGENT,
    ) -> bool:
        if execution_id in self._runs:
            return False
        self._runs[execution_id] = _Run(
            execution_id=execution_id,
            is_resume=is_resume,
            writer_epoch=writer_epoch,
            opened_at=self._now(),
            workload=workload,
        )
        return True

    async def mark_admitted(self, execution_id: str) -> None:
        self._promote(execution_id)

    async def claim(self, host_id: str) -> ClaimedRun | None:
        async with self._lock:
            now = self._now()
            entry = self._hosts.get(host_id)
            if entry is None or not self._live(entry, now) or not self._claims_enabled(entry, now):
                return None
            entry = self._budget(host_id, entry, claim_checked_at=now)
            if entry.in_use >= entry.capacity:
                return None
            pool = self._pools[entry.host.pool.pool_id]
            higher = self._higher(pool, now)
            epoch = entry.host.epoch
            ready = [r for r in self._runs.values() if self._eligible(r, entry, higher, now)]
            if not ready:
                return None
            oldest = min(ready, key=lambda r: (r.admitted_at or _NEVER, r.execution_id))
            overflowed = any(self._can_take(x, oldest) for x in higher)
            run = self._put(
                oldest,
                state="claimed",
                executor_id=host_id,
                reader_epoch=epoch,
                token=oldest.token + 1,
                leased_until=now + self._ttl,
                placed_pool=pool.pool_id,
                overflowed=overflowed,
                claimed_at=now,
            )
            # The one probe past a tripped breaker's cooldown: Postgres's step 4.
            probe = entry.claims_disabled_until is not None
            self._budget(
                host_id,
                entry,
                in_use=entry.in_use + 1,
                claims_disabled_until=now + entry.breaker_cooldown if probe else None,
            )
            return ClaimedRun(
                execution_id=run.execution_id,
                executor_id=host_id,
                token=run.token,
                is_resume=run.is_resume,
                pool_id=pool.pool_id,
                overflowed=overflowed,
            )

    async def record_create_failure(
        self, host_id: str, *, threshold: int, cooldown: timedelta
    ) -> bool:
        if threshold < 1 or cooldown <= timedelta(0):
            raise ValueError("breaker threshold and cooldown must be positive")
        entry = self._hosts.get(host_id)
        if entry is None:
            return False
        now, failures = self._now(), entry.create_failures + 1
        until = now + cooldown if failures >= threshold else entry.claims_disabled_until
        self._budget(
            host_id,
            entry,
            create_failures=failures,
            claims_disabled_until=until,
            breaker_cooldown=cooldown,
        )
        return until is not None and until > now

    async def record_create_success(self, host_id: str) -> None:
        entry = self._hosts.get(host_id)
        if entry is not None:
            self._budget(host_id, entry, create_failures=0, claims_disabled_until=None)

    async def renew(self, run: ClaimedRun) -> None:
        row = self._held(run.execution_id, run.token, "claimed")
        if row is None or row.leased_until <= self._now():
            raise RunLeaseLost(f"lease on {run.execution_id} expired or superseded")
        self._put(row, leased_until=self._now() + self._ttl)

    async def defer(self, run: ClaimedRun, retry_after: timedelta, reason: str) -> None:
        if retry_after < timedelta(0):
            raise ValueError("retry delay must be nonnegative")
        row = self._release(run.execution_id, run.token, "claimed", "admitted")
        self._put(row, retry_at=self._now() + retry_after, reason=reason)

    async def close(self, run: ClaimedRun) -> None:
        self._release(run.execution_id, run.token, "claimed", "done")

    async def fence_expired(self, reconciler: str, *, limit: int) -> list[FencedRun]:
        entry = self._hosts.get(reconciler)
        if entry is None or not entry.registered or limit < 1:
            return []
        now, epoch = self._now(), entry.host.epoch
        expired = sorted(
            (
                held
                for held in self._runs.values()
                if held.state == "claimed"
                and held.leased_until < now
                and held.writer_epoch <= epoch
                and self._in_scope(held, entry)
            ),
            key=lambda held: (held.leased_until, held.execution_id),
        )
        fenced: list[FencedRun] = []
        for held in expired[:limit]:
            row = self._put(
                held,
                state="fencing",
                reconciler=reconciler,
                token=held.token + 1,
                reader_epoch=min(
                    held.reader_epoch if held.reader_epoch is not None else epoch, epoch
                ),
            )
            fenced.append(self._fenced(row, reconciler))
        return fenced

    async def take_over(self, reconciler: str, *, limit: int) -> list[FencedRun]:
        entry = self._hosts.get(reconciler)
        if entry is None or not entry.registered or limit < 1:
            return []
        orphaned = sorted(
            (
                held
                for held in self._runs.values()
                if held.state in ("fencing", "reaped")
                and held.reconciler != reconciler
                and self._adoptable(held, entry.host.epoch)
                and self._in_scope(held, entry)
            ),
            key=lambda held: (held.leased_until, held.execution_id),
        )
        return [
            self._fenced(self._put(held, reconciler=reconciler, token=held.token + 1), reconciler)
            for held in orphaned[:limit]
        ]

    async def reconciling(self, reconciler: str) -> list[FencedRun]:
        entry = self._hosts.get(reconciler)
        if entry is None or not entry.registered:
            return []
        owned = [
            self._fenced(held, reconciler)
            for held in self._runs.values()
            if held.state in ("fencing", "reaped") and held.reconciler == reconciler
        ]
        return sorted(owned, key=lambda run: run.execution_id)

    async def mark_reaped(self, run: FencedRun) -> None:
        row = self._held(run.execution_id, run.token, "fencing")
        if row is None or row.reconciler != run.reconciler:
            raise RunLeaseLost(f"reconciliation of {run.execution_id} was taken over")
        self._put(row, state="reaped")

    async def close_interrupted(self, run: FencedRun) -> None:
        self._release(run.execution_id, run.token, "reaped", "interrupted")

    async def sweep_opening(
        self, older_than: timedelta, streams: ExecutionStreamProbe
    ) -> OpeningSweep:
        cutoff = self._now() - older_than
        due = [
            r
            for r in self._runs.values()
            if (r.state == "opening" and r.opened_at < cutoff) or r.state == "abandoned"
        ]
        admitted: list[str] = []
        abandoned: list[str] = []
        for due_row in due:
            execution_id = due_row.execution_id
            presence = await streams.presence(execution_id)
            # Re-read: the row may have been replaced while the probe was awaited.
            row = self._runs[execution_id]
            if presence is StreamPresence.PRESENT and self._promote(execution_id):
                admitted.append(execution_id)
            elif presence is StreamPresence.ABSENT and row.state == "opening":
                self._put(row, state="abandoned", reason="start not recorded")
                abandoned.append(execution_id)
        return OpeningSweep(admitted=tuple(admitted), abandoned=tuple(abandoned))

    async def in_use(self) -> RunCounts:
        return RunCounts.model_validate(Counter(r.state for r in self._runs.values()))

    def _live(self, entry: _Host, now: datetime) -> bool:
        """Registered, not draining and a fresh heartbeat: the Postgres claim's step 1."""
        return entry.registered and not entry.draining and entry.heartbeat_at > now - self._stale

    @staticmethod
    def _claims_enabled(entry: _Host, now: datetime) -> bool:
        """The Postgres ``claims_enabled``: the Outage Breaker has not disabled it (#1917)."""
        return entry.claims_disabled_until is None or entry.claims_disabled_until <= now

    def _eligible(self, row: _Run, entry: _Host, higher: list[_Host], now: datetime) -> bool:
        """The Postgres claim's candidate predicate, for the claimer ``entry`` (D13)."""
        pool = self._pools[entry.host.pool.pool_id]
        return (
            row.state == "admitted"
            and row.retry_at <= now
            and row.writer_epoch <= entry.host.epoch
            and self._can_run(pool, row)
            and not any(self._can_take(x, row) and self._holds_back(x, pool, now) for x in higher)
            # No Overflow Budget: only what no REGISTERED higher executor could take.
            and (
                pool.overflow_budget_usd_per_day is not None
                or not any(self._can_take(x, row) for x in self._registered_higher(pool))
            )
        )

    def _higher(self, pool: ExecutorPool, now: datetime) -> list[_Host]:
        """Live executors in higher-priority pools: the Postgres claim's ``higher`` (D13)."""
        return [
            other
            for other in self._hosts.values()
            if self._pools[other.host.pool.pool_id].priority < pool.priority
            and self._live(other, now)
            and self._claims_enabled(other, now)
        ]

    def _registered_higher(self, pool: ExecutorPool) -> list[_Host]:
        """Registered executors in higher-priority pools, live or not: Postgres's ``registered_higher``."""
        return [
            other
            for other in self._hosts.values()
            if other.registered and self._pools[other.host.pool.pool_id].priority < pool.priority
        ]

    def _holds_back(self, other: _Host, pool: ExecutorPool, now: datetime) -> bool:
        """Claiming with room, or full for less than ``pool``'s Overflow Delay (D13)."""
        claiming_with_room = (
            other.in_use < other.capacity and other.claim_checked_at > now - self._stale
        )
        recently_full = (
            other.full_since is not None and other.full_since > now - pool.overflow_delay
        )
        return claiming_with_room or recently_full

    @staticmethod
    def _can_run(pool: ExecutorPool, row: _Run) -> bool:
        """The Postgres ``can_run``: a NoCredentials pool runs only scripted work (#1917)."""
        return pool.supplies_credentials or row.workload is RunWorkload.SCRIPTED

    def _can_take(self, other: _Host, row: _Run) -> bool:
        """The Postgres ``can_take``: the executor reads the run's epoch and its pool can run it."""
        return other.host.epoch >= row.writer_epoch and self._can_run(
            self._pools[other.host.pool.pool_id], row
        )

    def _budget(self, host_id: str, entry: _Host, **changes: object) -> _Host:
        """Replace a budget row, keeping ``full_since`` as the Postgres trigger does."""
        updated = entry.model_copy(update=changes)
        full_since = (
            None if updated.in_use < updated.capacity else (updated.full_since or self._now())
        )
        updated = updated.model_copy(update={"full_since": full_since})
        self._hosts[host_id] = updated
        return updated

    def _adoptable(self, row: _Run, epoch: int) -> bool:
        """The Postgres takeover predicate: its reconciler has left, and the epoch is readable."""
        left = self._hosts.get(row.reconciler or "")
        return (left is None or not left.registered) and row.writer_epoch <= epoch

    def _in_scope(self, row: _Run, reconciler: _Host) -> bool:
        """The Postgres ``in_reach``: its own scope or one it holds a Recovery Kit for (C8)."""
        claimer = self._hosts.get(row.executor_id or "")
        reach = {reconciler.host.reap_scope, *reconciler.host.recovery_scopes}
        return claimer is not None and claimer.host.reap_scope in reach

    def _fenced(self, row: _Run, reconciler: str) -> FencedRun:
        claimer = self._hosts.get(row.executor_id or "")
        return FencedRun(
            execution_id=row.execution_id,
            executor_id=row.executor_id or "",
            reconciler=reconciler,
            token=row.token,
            reaped=row.state == "reaped",
            claimer_scope=None if claimer is None else claimer.host.reap_scope,
        )

    def _promote(self, execution_id: str) -> bool:
        row = self._runs.get(execution_id)
        if row is None or row.state not in ("opening", "abandoned"):
            return False
        self._put(row, state="admitted", admitted_at=self._now(), reason=None)
        return True

    def _put(self, row: _Run, **changes: object) -> _Run:
        """Replace ``row`` with a copy carrying ``changes``; the stored row is never mutated."""
        updated = row.model_copy(update=changes)
        self._runs[row.execution_id] = updated
        return updated

    def _held(self, execution_id: str, token: int, state: str) -> _Run | None:
        row = self._runs.get(execution_id)
        if row is None or row.token != token or row.state != state:
            return None
        return row

    def _release(self, execution_id: str, token: int, held: str, to: str) -> _Run:
        row = self._held(execution_id, token, held)
        if row is None or row.executor_id is None:
            raise RunLeaseLost(f"{execution_id} is no longer {held} under token {token}")
        charged = self._hosts[row.executor_id]
        moved = int(charged.successor_id is not None)
        self._budget(
            row.executor_id,
            charged,
            in_use=charged.in_use - 1,
            capacity=charged.capacity - moved,
        )
        if charged.successor_id is not None:
            heir = self._hosts[charged.successor_id]
            self._budget(charged.successor_id, heir, capacity=heir.capacity + 1)
        return self._put(row, state=to, executor_id=None, leased_until=_NEVER)
