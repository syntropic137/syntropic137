"""Postgres Run Queue: capacity and claim in one transaction (ADR-072 D3).

Copies the lease shape of ``PostgresCaptureDeliveryJobs``: ``FOR UPDATE SKIP
LOCKED LIMIT 1``, a ``lease_token`` bumped on every claim and fence, and
compare-and-set on that token for every later write.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

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
    from syn_adapters.session_inventory.database import Connection, Pool
    from syn_domain.contexts.orchestration.ports import ExecutionStreamProbe

_START_NOT_RECORDED = "start not recorded"


class PostgresExecutionRunQueue:
    def __init__(
        self,
        pool: Pool,
        *,
        lease_ttl: timedelta = timedelta(seconds=90),
        heartbeat_stale: timedelta = timedelta(seconds=90),
    ) -> None:
        if lease_ttl <= timedelta(0) or heartbeat_stale <= timedelta(0):
            raise ValueError("lease TTL and heartbeat staleness must be positive")
        self._pool = pool
        self._lease_seconds = lease_ttl.total_seconds()
        self._stale_seconds = heartbeat_stale.total_seconds()

    async def ensure_ready(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(Path(__file__).with_name("schema.sql").read_text())

    async def register(self, host: ExecutorHost, capacity: int) -> None:
        if capacity < 0:
            raise ValueError("executor capacity must be nonnegative")
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """INSERT INTO executor_hosts (host_id,container_id,generation,epoch)
                VALUES ($1,$2,$3,$4) ON CONFLICT (host_id) DO NOTHING""",
                host.host_id,
                host.container_id,
                host.generation,
                host.epoch,
            )
            await conn.execute(
                """INSERT INTO execution_budget (executor_id,capacity)
                VALUES ($1,$2) ON CONFLICT (executor_id) DO NOTHING""",
                host.host_id,
                capacity,
            )

    async def deregister(self, host_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM executor_hosts WHERE host_id=$1", host_id)

    async def heartbeat(self, host_id: str) -> bool:
        async with self._pool.acquire() as conn:
            draining = await conn.fetchval(
                """WITH beat AS (
                    UPDATE execution_budget SET heartbeat_at=now() WHERE executor_id=$1
                    RETURNING executor_id
                ) SELECT h.draining::text FROM executor_hosts h JOIN beat b
                ON b.executor_id=h.host_id""",
                host_id,
            )
        if draining is None:
            raise LookupError(f"executor {host_id!r} is not registered")
        return draining == "true"

    async def is_draining(self, host_id: str) -> bool:
        async with self._pool.acquire() as conn:
            draining = await conn.fetchval(
                "SELECT draining::text FROM executor_hosts WHERE host_id=$1", host_id
            )
        return draining == "true"

    async def reserve(self, execution_id: str, writer_epoch: int, *, is_resume: bool) -> bool:
        async with self._pool.acquire() as conn:
            inserted = await conn.fetchval(
                """INSERT INTO execution_runs (execution_id,state,is_resume,writer_epoch)
                VALUES ($1,'opening',$2,$3) ON CONFLICT (execution_id) DO NOTHING
                RETURNING execution_id""",
                execution_id,
                is_resume,
                writer_epoch,
            )
        return inserted is not None

    async def mark_admitted(self, execution_id: str) -> None:
        async with self._pool.acquire() as conn:
            await self._promote(conn, execution_id)

    async def claim(self, host_id: str) -> ClaimedRun | None:
        async with self._pool.acquire() as conn, conn.transaction():
            # 1. Lock this executor's own budget row, only while it has room.
            epoch = await conn.fetchval(
                """SELECT h.epoch::text FROM execution_budget b
                JOIN executor_hosts h ON h.host_id=b.executor_id
                WHERE b.executor_id=$1 AND b.in_use<b.capacity AND NOT h.draining
                AND b.heartbeat_at>now()-$2::double precision*interval '1 second'
                FOR UPDATE OF b""",
                host_id,
                self._stale_seconds,
            )
            if epoch is None:
                return None
            # 2-3. The oldest claimable run this host can read, charged to it.
            raw = await conn.fetchval(
                """WITH candidate AS (
                    SELECT execution_id FROM execution_runs
                    WHERE state='admitted' AND retry_at<=now() AND writer_epoch<=$2
                    ORDER BY admitted_at,execution_id FOR UPDATE SKIP LOCKED LIMIT 1
                ) UPDATE execution_runs r SET state='claimed',executor_id=$1,
                    lease_token=r.lease_token+1, reader_epoch=$2, reason=NULL,
                    leased_until=now()+$3::double precision*interval '1 second'
                FROM candidate c WHERE r.execution_id=c.execution_id
                RETURNING jsonb_build_object('execution_id',r.execution_id,
                    'executor_id',r.executor_id,'token',r.lease_token,
                    'is_resume',r.is_resume)::text""",
                host_id,
                int(epoch),
                self._lease_seconds,
            )
            if raw is None:
                return None
            # 4. Same transaction as step 1's lock, so in_use never passes capacity.
            await conn.execute(
                "UPDATE execution_budget SET in_use=in_use+1 WHERE executor_id=$1", host_id
            )
        return ClaimedRun.model_validate_json(raw)

    async def renew(self, run: ClaimedRun) -> None:
        async with self._pool.acquire() as conn:
            renewed = await conn.fetchval(
                """UPDATE execution_runs
                SET leased_until=now()+$3::double precision*interval '1 second'
                WHERE execution_id=$1 AND lease_token=$2 AND state='claimed'
                AND leased_until>now() RETURNING execution_id""",
                run.execution_id,
                run.token,
                self._lease_seconds,
            )
        if renewed is None:
            raise RunLeaseLost(f"lease on {run.execution_id} expired or superseded")

    async def defer(self, run: ClaimedRun, retry_after: timedelta, reason: str) -> None:
        if retry_after < timedelta(0):
            raise ValueError("retry delay must be nonnegative")
        await self._release(
            run.execution_id,
            run.token,
            "claimed",
            "admitted",
            retry_seconds=retry_after.total_seconds(),
            reason=reason,
        )

    async def close(self, run: ClaimedRun) -> None:
        await self._release(run.execution_id, run.token, "claimed", "done")

    async def fence_expired(self, reconciler: str) -> list[FencedRun]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """UPDATE execution_runs r SET state='fencing',lease_token=r.lease_token+1,
                    reconciler=h.host_id, reader_epoch=LEAST(r.reader_epoch,h.epoch)
                FROM executor_hosts h
                WHERE h.host_id=$1 AND r.state='claimed' AND r.leased_until<now()
                AND r.writer_epoch<=h.epoch
                RETURNING jsonb_build_object('execution_id',r.execution_id,
                    'executor_id',r.executor_id,'reconciler',r.reconciler,
                    'token',r.lease_token)::text AS run""",
                reconciler,
            )
        return [FencedRun.model_validate_json(row["run"]) for row in rows]

    async def mark_reaped(self, run: FencedRun) -> None:
        async with self._pool.acquire() as conn:
            reaped = await conn.fetchval(
                """UPDATE execution_runs SET state='reaped'
                WHERE execution_id=$1 AND lease_token=$2 AND reconciler=$3
                AND state='fencing' RETURNING execution_id""",
                run.execution_id,
                run.token,
                run.reconciler,
            )
        if reaped is None:
            raise RunLeaseLost(f"reconciliation of {run.execution_id} was taken over")

    async def close_interrupted(self, run: FencedRun) -> None:
        await self._release(run.execution_id, run.token, "reaped", "interrupted")

    async def sweep_opening(
        self, older_than: timedelta, streams: ExecutionStreamProbe
    ) -> OpeningSweep:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT execution_id,state FROM execution_runs
                WHERE (state='opening'
                    AND opened_at<now()-$1::double precision*interval '1 second')
                OR state='abandoned' ORDER BY opened_at,execution_id""",
                older_than.total_seconds(),
            )
        admitted: list[str] = []
        abandoned: list[str] = []
        for row in rows:
            execution_id = row["execution_id"]
            presence = await streams.presence(execution_id)
            async with self._pool.acquire() as conn:
                if presence is StreamPresence.PRESENT and await self._promote(conn, execution_id):
                    admitted.append(execution_id)
                elif presence is StreamPresence.ABSENT and row["state"] == "opening":
                    moved = await conn.fetchval(
                        """UPDATE execution_runs SET state='abandoned',reason=$2
                        WHERE execution_id=$1 AND state='opening' RETURNING execution_id""",
                        execution_id,
                        _START_NOT_RECORDED,
                    )
                    if moved is not None:
                        abandoned.append(execution_id)
        return OpeningSweep(admitted=tuple(admitted), abandoned=tuple(abandoned))

    async def in_use(self) -> RunCounts:
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                """SELECT COALESCE(jsonb_object_agg(state,n),'{}'::jsonb)::text
                FROM (SELECT state,count(*) AS n FROM execution_runs GROUP BY state) s"""
            )
        return RunCounts.model_validate_json(raw or "{}")

    @staticmethod
    async def _promote(conn: Connection, execution_id: str) -> bool:
        """``opening``/``abandoned`` -> ``admitted``; whichever writes second does nothing (D2)."""
        promoted = await conn.fetchval(
            """UPDATE execution_runs SET state='admitted',admitted_at=now(),reason=NULL
            WHERE execution_id=$1 AND state IN ('opening','abandoned')
            RETURNING execution_id""",
            execution_id,
        )
        return promoted is not None

    async def _release(
        self,
        execution_id: str,
        token: int,
        held: str,
        to: str,
        *,
        retry_seconds: float = 0,
        reason: str | None = None,
    ) -> None:
        """Guarded state change, ``in_use - 1`` on the charged executor, owner cleared (D3)."""
        async with self._pool.acquire() as conn, conn.transaction():
            charged = await conn.fetchval(
                """WITH held AS (
                    SELECT execution_id,executor_id FROM execution_runs
                    WHERE execution_id=$1 AND lease_token=$2 AND state=$3 FOR UPDATE
                ) UPDATE execution_runs r SET state=$4,executor_id=NULL,
                    leased_until='-infinity',reason=$6,
                    retry_at=now()+$5::double precision*interval '1 second'
                FROM held h WHERE r.execution_id=h.execution_id
                RETURNING h.executor_id""",
                execution_id,
                token,
                held,
                to,
                retry_seconds,
                reason,
            )
            if charged is None:
                raise RunLeaseLost(f"{execution_id} is no longer {held} under token {token}")
            await conn.execute(
                "UPDATE execution_budget SET in_use=in_use-1 WHERE executor_id=$1", charged
            )
