"""Test double for the Run Queue. Same guards as Postgres; refuses production (ADR-060)."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from syn_adapters.in_memory import InMemoryAdapter
from syn_domain.contexts.orchestration.ports import (
    ClaimedRun,
    ExecutorHost,
    FencedRun,
    OpeningSweep,
    RunCounts,
    RunLeaseLost,
    StreamPresence,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_domain.contexts.orchestration.ports import ExecutionStreamProbe

_NEVER = datetime.min.replace(tzinfo=UTC)


@dataclass
class _Host:
    host: ExecutorHost
    capacity: int
    in_use: int = 0
    heartbeat_at: datetime = _NEVER
    draining: bool = False
    registered: bool = True


@dataclass
class _Run:
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
    reader_epoch: int | None = field(default=None)
    reason: str | None = None


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
        self._runs: dict[str, _Run] = {}
        self._lock = asyncio.Lock()

    async def register(self, host: ExecutorHost, capacity: int) -> None:
        if capacity < 0:
            raise ValueError("executor capacity must be nonnegative")
        self._hosts.setdefault(host.host_id, _Host(host=host, capacity=capacity))

    async def deregister(self, host_id: str) -> None:
        if host_id in self._hosts:
            self._hosts[host_id].registered = False

    async def heartbeat(self, host_id: str) -> bool:
        entry = self._hosts.get(host_id)
        if entry is None or not entry.registered:
            raise LookupError(f"executor {host_id!r} is not registered")
        entry.heartbeat_at = self._now()
        return entry.draining

    async def is_draining(self, host_id: str) -> bool:
        entry = self._hosts.get(host_id)
        return entry is not None and entry.registered and entry.draining

    async def reserve(self, execution_id: str, writer_epoch: int, *, is_resume: bool) -> bool:
        if execution_id in self._runs:
            return False
        self._runs[execution_id] = _Run(execution_id, is_resume, writer_epoch, self._now())
        return True

    async def mark_admitted(self, execution_id: str) -> None:
        self._promote(execution_id)

    async def claim(self, host_id: str) -> ClaimedRun | None:
        async with self._lock:
            now = self._now()
            entry = self._hosts.get(host_id)
            if (
                entry is None
                or not entry.registered
                or entry.draining
                or entry.in_use >= entry.capacity
                or entry.heartbeat_at <= now - self._stale
            ):
                return None
            epoch = entry.host.epoch
            ready = [
                r
                for r in self._runs.values()
                if r.state == "admitted" and r.retry_at <= now and r.writer_epoch <= epoch
            ]
            if not ready:
                return None
            run = min(ready, key=lambda r: (r.admitted_at or _NEVER, r.execution_id))
            run.state, run.executor_id, run.reader_epoch = "claimed", host_id, epoch
            run.token += 1
            run.leased_until = now + self._ttl
            entry.in_use += 1
            return ClaimedRun(
                execution_id=run.execution_id,
                executor_id=host_id,
                token=run.token,
                is_resume=run.is_resume,
            )

    async def renew(self, run: ClaimedRun) -> None:
        row = self._held(run.execution_id, run.token, "claimed")
        if row is None or row.leased_until <= self._now():
            raise RunLeaseLost(f"lease on {run.execution_id} expired or superseded")
        row.leased_until = self._now() + self._ttl

    async def defer(self, run: ClaimedRun, retry_after: timedelta, reason: str) -> None:
        if retry_after < timedelta(0):
            raise ValueError("retry delay must be nonnegative")
        row = self._release(run.execution_id, run.token, "claimed", "admitted")
        row.retry_at, row.reason = self._now() + retry_after, reason

    async def close(self, run: ClaimedRun) -> None:
        self._release(run.execution_id, run.token, "claimed", "done")

    async def fence_expired(self, reconciler: str) -> list[FencedRun]:
        entry = self._hosts.get(reconciler)
        if entry is None or not entry.registered:
            return []
        now, epoch, fenced = self._now(), entry.host.epoch, []
        for row in self._runs.values():
            if row.state == "claimed" and row.leased_until < now and row.writer_epoch <= epoch:
                row.state, row.reconciler = "fencing", reconciler
                row.token += 1
                row.reader_epoch = min(
                    row.reader_epoch if row.reader_epoch is not None else epoch, epoch
                )
                fenced.append(
                    FencedRun(
                        execution_id=row.execution_id,
                        executor_id=row.executor_id or "",
                        reconciler=reconciler,
                        token=row.token,
                    )
                )
        return fenced

    async def mark_reaped(self, run: FencedRun) -> None:
        row = self._held(run.execution_id, run.token, "fencing")
        if row is None or row.reconciler != run.reconciler:
            raise RunLeaseLost(f"reconciliation of {run.execution_id} was taken over")
        row.state = "reaped"

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
        for row in due:
            presence = await streams.presence(row.execution_id)
            if presence is StreamPresence.PRESENT and self._promote(row.execution_id):
                admitted.append(row.execution_id)
            elif presence is StreamPresence.ABSENT and row.state == "opening":
                row.state, row.reason = "abandoned", "start not recorded"
                abandoned.append(row.execution_id)
        return OpeningSweep(admitted=tuple(admitted), abandoned=tuple(abandoned))

    async def in_use(self) -> RunCounts:
        return RunCounts.model_validate(Counter(r.state for r in self._runs.values()))

    def _promote(self, execution_id: str) -> bool:
        row = self._runs.get(execution_id)
        if row is None or row.state not in ("opening", "abandoned"):
            return False
        row.state, row.admitted_at, row.reason = "admitted", self._now(), None
        return True

    def _held(self, execution_id: str, token: int, state: str) -> _Run | None:
        row = self._runs.get(execution_id)
        if row is None or row.token != token or row.state != state:
            return None
        return row

    def _release(self, execution_id: str, token: int, held: str, to: str) -> _Run:
        row = self._held(execution_id, token, held)
        if row is None or row.executor_id is None:
            raise RunLeaseLost(f"{execution_id} is no longer {held} under token {token}")
        self._hosts[row.executor_id].in_use -= 1
        row.state, row.executor_id, row.leased_until = to, None, _NEVER
        return row
