"""Postgres Run Queue: capacity and claim in one transaction (ADR-072 D3).

Copies the lease shape of ``PostgresCaptureDeliveryJobs``: ``FOR UPDATE SKIP
LOCKED LIMIT 1``, a ``lease_token`` bumped on every claim and fence, and
compare-and-set on that token for every later write.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from syn_adapters.advisory_locks import RUN_QUEUE_SCHEMA_LOCK_KEY, session_advisory_lock
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
    from syn_adapters.session_inventory.database import Connection, Pool
    from syn_domain.contexts.orchestration.ports import ExecutionStreamProbe

_START_NOT_RECORDED = "start not recorded"


def can_run(pool: str) -> str:
    """SQL: the Executor Pool aliased ``pool`` can run the run aliased ``r`` (D13).

    The one place what a pool can run is spelled; the claim uses it for the
    claimer and for every higher executor, so the two can never disagree.
    Today it is the credential clause (#1917): a NoCredentials pool runs only
    scripted work. Run Requirements (provider, region, isolation, capabilities,
    #2060) join here.
    """
    return f"({pool}.supplies_credentials OR r.workload='scripted')"


def can_take(executor: str) -> str:
    """SQL: the executor aliased ``executor`` (epoch and pool columns) could take run ``r``."""
    return f"({executor}.epoch>=r.writer_epoch AND {can_run(executor)})"


# D3 steps 2-3 with D13 placement. $1 the claimer, $2 the staleness window, $3
# the lease TTL. Higher executors' rows are read, never locked: capacity comes
# only from the claimer's own locked row, so preference is decided on a
# snapshot and capacity is still exact (D3, D13).
_CLAIM_SQL = f"""WITH me AS (
    SELECT b.executor_id, h.epoch, p.pool_id, p.priority, p.overflow_delay_s,
        p.supplies_credentials
    FROM execution_budget b JOIN executor_hosts h ON h.host_id=b.executor_id
    JOIN executor_pools p ON p.pool_id=b.pool_id WHERE b.executor_id=$1
), higher AS (
    SELECT h.epoch, p.supplies_credentials,
        (b.in_use<b.capacity
            AND b.claim_checked_at>clock_timestamp()-$2::double precision*interval '1 second')
            AS claiming_with_room,
        COALESCE(b.full_since>clock_timestamp()-me.overflow_delay_s*interval '1 second', FALSE)
            AS recently_full
    FROM execution_budget b JOIN executor_hosts h ON h.host_id=b.executor_id
    JOIN executor_pools p ON p.pool_id=b.pool_id, me
    WHERE p.priority<me.priority AND NOT h.draining
    AND b.heartbeat_at>clock_timestamp()-$2::double precision*interval '1 second'
), candidate AS (
    SELECT r.execution_id, EXISTS (SELECT 1 FROM higher x WHERE {can_take("x")}) AS overflowed
    FROM execution_runs r, me
    WHERE r.state='admitted' AND r.retry_at<=clock_timestamp() AND r.writer_epoch<=me.epoch
    AND {can_run("me")}
    AND NOT EXISTS (SELECT 1 FROM higher x WHERE {can_take("x")}
        AND (x.claiming_with_room OR x.recently_full))
    ORDER BY r.admitted_at, r.execution_id FOR UPDATE OF r SKIP LOCKED LIMIT 1
) UPDATE execution_runs r SET state='claimed', executor_id=me.executor_id,
    lease_token=r.lease_token+1, reader_epoch=me.epoch, reason=NULL,
    leased_until=clock_timestamp()+$3::double precision*interval '1 second',
    placed_pool=me.pool_id, overflowed=c.overflowed, claimed_at=clock_timestamp()
FROM candidate c, me WHERE r.execution_id=c.execution_id
RETURNING jsonb_build_object('execution_id',r.execution_id,'executor_id',r.executor_id,
    'token',r.lease_token,'is_resume',r.is_resume,'pool_id',r.placed_pool,
    'overflowed',r.overflowed)::text"""


@dataclass(frozen=True)
class SchemaStep:
    name: str
    sql: str


def schema_steps(text: str) -> tuple[SchemaStep, ...]:
    """Split schema.sql at its ``-- step: <name>`` lines, in file order."""
    preamble, *parts = re.split(r"^-- step: (\S+)$", text, flags=re.MULTILINE)
    if any(line.strip() and not line.startswith("--") for line in preamble.splitlines()):
        raise ValueError("Run Queue schema.sql has SQL before its first '-- step:' line")
    steps = tuple(SchemaStep(name, sql) for name, sql in zip(parts[::2], parts[1::2], strict=True))
    if len({step.name for step in steps}) != len(steps):
        raise ValueError("Run Queue schema.sql names a step twice")
    return steps


SCHEMA_STEPS = schema_steps(Path(__file__).with_name("schema.sql").read_text())

# Which steps this database has applied, and when each first was (#1965).
_SCHEMA_LEDGER_SQL = """CREATE TABLE IF NOT EXISTS execution_run_queue_schema_steps (
    step TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""
_RECORD_STEP_SQL = """INSERT INTO execution_run_queue_schema_steps (step)
    VALUES ($1) ON CONFLICT DO NOTHING"""


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
        """Apply every schema step, one process at a time (#1965).

        The api and each executor call this as they start. Every step is
        idempotent, but concurrently it is not: two CREATE TABLE IF NOT EXISTS
        race on the catalog, and the pool constraint is check-then-add. So the
        whole apply holds one session lock, and no transaction is open while
        waiting for it (see session_advisory_lock).
        """
        async with (
            self._pool.acquire() as conn,
            session_advisory_lock(conn, RUN_QUEUE_SCHEMA_LOCK_KEY),
        ):
            await conn.execute(_SCHEMA_LEDGER_SQL)
            for step in SCHEMA_STEPS:
                async with conn.transaction():
                    await conn.execute(step.sql)
                    await conn.execute(_RECORD_STEP_SQL, step.name)

    async def register(self, host: ExecutorHost, capacity: int) -> None:
        if capacity < 0:
            raise ValueError("executor capacity must be nonnegative")
        async with self._pool.acquire() as conn, conn.transaction():
            # D5 Restart: a process starting in a container that already has a
            # host row is the proof that row's process stopped; it has left.
            await conn.execute(
                "DELETE FROM executor_hosts WHERE container_id=$1 AND host_id<>$2",
                host.container_id,
                host.host_id,
            )
            await self._join_pool(conn, host)
            await self._register_budget(conn, host, capacity)
            # Last, after every lock wait above: registered_at is this member's
            # liveness until its first heartbeat, and now() is the transaction's
            # start, so a long wait would commit a member already stale.
            await conn.execute(
                """INSERT INTO executor_hosts
                (host_id,container_id,generation,epoch,registered_at)
                VALUES ($1,$2,$3,$4,clock_timestamp()) ON CONFLICT (host_id) DO NOTHING""",
                host.host_id,
                host.container_id,
                host.generation,
                host.epoch,
            )

    async def deregister(self, host_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM executor_hosts WHERE host_id=$1", host_id)

    async def heartbeat(self, host_id: str) -> bool:
        async with self._pool.acquire() as conn:
            draining = await conn.fetchval(
                """UPDATE execution_budget b SET heartbeat_at=now() FROM executor_hosts h
                WHERE b.executor_id=$1 AND h.host_id=b.executor_id
                RETURNING h.draining::text""",
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

    async def others_live(self, host_id: str) -> bool:
        async with self._pool.acquire() as conn:
            live = await conn.fetchval(
                """SELECT EXISTS (SELECT 1 FROM executor_hosts h
                JOIN execution_budget b ON b.executor_id=h.host_id WHERE h.host_id<>$1
                AND b.heartbeat_at>clock_timestamp()-$2::double precision*interval '1 second')""",
                host_id,
                self._stale_seconds,
            )
        return bool(live)

    async def reserve(
        self,
        execution_id: str,
        writer_epoch: int,
        *,
        is_resume: bool,
        workload: RunWorkload = RunWorkload.AGENT,
    ) -> bool:
        async with self._pool.acquire() as conn:
            inserted = await conn.fetchval(
                """INSERT INTO execution_runs (execution_id,state,is_resume,writer_epoch,workload)
                VALUES ($1,'opening',$2,$3,$4) ON CONFLICT (execution_id) DO NOTHING
                RETURNING execution_id""",
                execution_id,
                is_resume,
                writer_epoch,
                str(workload),
            )
        return inserted is not None

    async def mark_admitted(self, execution_id: str) -> None:
        async with self._pool.acquire() as conn:
            await self._promote(conn, execution_id)

    async def claim(self, host_id: str) -> ClaimedRun | None:
        async with self._pool.acquire() as conn, conn.transaction():
            # 1. Lock this executor's own budget row. The lock can wait, and now()
            # is the transaction's start, so room and liveness are read after it
            # against clock_timestamp(), in a statement that sees the wait's writes.
            await conn.execute(
                "SELECT 1 FROM execution_budget WHERE executor_id=$1 FOR UPDATE", host_id
            )
            # The Claim Check (D13): stamped whenever this executor is live and
            # not draining, with or without room, so it commits even when no run
            # is then found. Placement trusts it, not the heartbeat, to say room.
            has_room = await conn.fetchval(
                """UPDATE execution_budget b SET claim_checked_at=clock_timestamp()
                FROM executor_hosts h WHERE b.executor_id=$1 AND h.host_id=b.executor_id
                AND NOT h.draining
                AND b.heartbeat_at>clock_timestamp()-$2::double precision*interval '1 second'
                RETURNING (b.in_use<b.capacity)::text""",
                host_id,
                self._stale_seconds,
            )
            if has_room != "true":
                return None
            # 2-3. The oldest run this executor may take now (D13), charged to it.
            raw = await conn.fetchval(_CLAIM_SQL, host_id, self._stale_seconds, self._lease_seconds)
            if raw is None:
                return None
            # 4. Same transaction as step 1's lock, so in_use never passes capacity.
            await conn.execute(
                "UPDATE execution_budget SET in_use=in_use+1 WHERE executor_id=$1", host_id
            )
        return ClaimedRun.model_validate_json(raw)

    async def renew(self, run: ClaimedRun) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            # Expiry is judged after the row lock, for the same reason as claim's step 1.
            await conn.execute(
                "SELECT 1 FROM execution_runs WHERE execution_id=$1 FOR UPDATE", run.execution_id
            )
            renewed = await conn.fetchval(
                """UPDATE execution_runs
                SET leased_until=clock_timestamp()+$3::double precision*interval '1 second'
                WHERE execution_id=$1 AND lease_token=$2 AND state='claimed'
                AND leased_until>clock_timestamp() RETURNING execution_id""",
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

    async def fence_expired(self, reconciler: str, *, limit: int) -> list[FencedRun]:
        if limit < 1:
            return []
        async with self._pool.acquire() as conn:
            # Only a claimer in this reconciler's reap scope: anything else is a
            # machine whose containers this reaper cannot see (D5, D13). The
            # scope never changes for a row, so the pick's check holds after the
            # lock. SKIP LOCKED keeps two fencers from blocking on, or sharing, a row;
            # the outer predicate is re-checked once the row is locked. The
            # pick is a MATERIALIZED CTE because an IN (... LIMIT) subquery may
            # be rescanned once per outer row, each rescan locking LIMIT more.
            rows = await conn.fetch(
                """WITH picked AS MATERIALIZED (
                    SELECT c.execution_id FROM execution_runs c
                    WHERE c.state='claimed' AND c.leased_until<now()
                    AND c.writer_epoch<=(SELECT epoch FROM executor_hosts WHERE host_id=$1)
                    AND (SELECT reap_scope FROM execution_budget WHERE executor_id=c.executor_id)
                        =(SELECT reap_scope FROM execution_budget WHERE executor_id=$1)
                    ORDER BY c.leased_until, c.execution_id
                    FOR UPDATE OF c SKIP LOCKED LIMIT $2
                ) UPDATE execution_runs r SET state='fencing',lease_token=r.lease_token+1,
                    reconciler=h.host_id, reader_epoch=LEAST(r.reader_epoch,h.epoch)
                FROM executor_hosts h, picked p
                WHERE h.host_id=$1 AND r.execution_id=p.execution_id
                AND r.state='claimed' AND r.leased_until<now() AND r.writer_epoch<=h.epoch
                RETURNING jsonb_build_object('execution_id',r.execution_id,
                    'executor_id',r.executor_id,'reconciler',r.reconciler,
                    'token',r.lease_token)::text AS run""",
                reconciler,
                limit,
            )
        return [FencedRun.model_validate_json(row["run"]) for row in rows]

    async def take_over(self, reconciler: str, *, limit: int) -> list[FencedRun]:
        if limit < 1:
            return []
        async with self._pool.acquire() as conn:
            # Take over rows whose reconciler has left, in this reap scope only
            # (D5, D13), the same rule as fence_expired's. SKIP LOCKED keeps two
            # adopters apart; the outer predicate is re-checked after the lock,
            # so a second adopter finds a live owner and takes nothing. The pick
            # is a MATERIALIZED CTE for the same reason as fence_expired's.
            rows = await conn.fetch(
                """WITH picked AS MATERIALIZED (
                    SELECT o.execution_id FROM execution_runs o
                    WHERE o.state IN ('fencing','reaped') AND o.reconciler IS DISTINCT FROM $1
                    AND o.writer_epoch<=(SELECT epoch FROM executor_hosts WHERE host_id=$1)
                    AND NOT EXISTS (SELECT 1 FROM executor_hosts h WHERE h.host_id=o.reconciler)
                    AND (SELECT reap_scope FROM execution_budget WHERE executor_id=o.executor_id)
                        =(SELECT reap_scope FROM execution_budget WHERE executor_id=$1)
                    ORDER BY o.leased_until, o.execution_id
                    FOR UPDATE OF o SKIP LOCKED LIMIT $2
                ) UPDATE execution_runs r SET reconciler=me.host_id,lease_token=r.lease_token+1
                FROM executor_hosts me, picked p
                WHERE me.host_id=$1 AND r.execution_id=p.execution_id
                AND r.state IN ('fencing','reaped')
                AND r.reconciler IS DISTINCT FROM me.host_id AND r.writer_epoch<=me.epoch
                AND NOT EXISTS (SELECT 1 FROM executor_hosts h WHERE h.host_id=r.reconciler)
                RETURNING jsonb_build_object('execution_id',r.execution_id,
                    'executor_id',r.executor_id,'reconciler',r.reconciler,
                    'token',r.lease_token,'reaped',r.state='reaped')::text AS run""",
                reconciler,
                limit,
            )
        return [FencedRun.model_validate_json(row["run"]) for row in rows]

    async def reconciling(self, reconciler: str) -> list[FencedRun]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT jsonb_build_object('execution_id',execution_id,
                    'executor_id',executor_id,'reconciler',reconciler,
                    'token',lease_token,'reaped',state='reaped')::text AS run
                FROM execution_runs WHERE reconciler=$1 AND state IN ('fencing','reaped')
                ORDER BY execution_id""",
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

    async def _join_pool(self, conn: Connection, host: ExecutorHost) -> None:
        """D13: define ``host.pool`` if new; redefine it only when no other member is live.

        The row lock serialises two members registering into one pool. A member
        is live while its host row is not draining and it heartbeat, or
        registered, within the staleness window: a crashed member never blocks
        a redefinition, and one that has not yet beaten still does.
        """
        declared = host.pool
        values = (
            declared.pool_id,
            declared.priority,
            declared.provider,
            declared.region,
            int(declared.isolation),
            sorted(declared.capabilities),
            int(declared.overflow_delay.total_seconds()),
            declared.supplies_credentials,
        )
        await conn.execute(
            """INSERT INTO executor_pools (pool_id,priority,provider,region,isolation,
            capabilities,overflow_delay_s,supplies_credentials)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (pool_id) DO NOTHING""",
            *values,
        )
        raw = await conn.fetchval(
            """SELECT jsonb_build_object('pool_id',pool_id,'priority',priority,
                'provider',provider,'region',region,'isolation',isolation,
                'capabilities',capabilities,'overflow_delay',overflow_delay_s,
                'supplies_credentials',supplies_credentials)::text
            FROM executor_pools WHERE pool_id=$1 FOR UPDATE""",
            declared.pool_id,
        )
        held = ExecutorPool.model_validate_json(raw or "")
        if held == declared:
            return
        others = await conn.fetchval(
            """SELECT EXISTS (SELECT 1 FROM executor_hosts h
            JOIN execution_budget b ON b.executor_id=h.host_id
            WHERE b.pool_id=$1 AND h.host_id<>$2 AND NOT h.draining
            AND GREATEST(b.heartbeat_at,h.registered_at)
                >clock_timestamp()-$3::double precision*interval '1 second')::text""",
            declared.pool_id,
            host.host_id,
            self._stale_seconds,
        )
        if others == "true":
            raise PoolDefinitionConflict(
                f"executor {host.host_id!r} declares Executor Pool {declared!r}, "
                f"but live members hold {held!r}; drain them or declare the same definition"
            )
        await conn.execute(
            """UPDATE executor_pools SET priority=$2,provider=$3,region=$4,isolation=$5,
            capabilities=$6,overflow_delay_s=$7,supplies_credentials=$8,defined_at=now()
            WHERE pool_id=$1""",
            *values,
        )

    @staticmethod
    async def _register_budget(conn: Connection, host: ExecutorHost, capacity: int) -> None:
        """D3 Restart: the machine's budget is not doubled by a new process in it.

        A predecessor in the same container keeps exactly the slots its runs
        still hold; the rest move to the successor now, and each later release
        moves one more. The machine's summed capacity never changes. Capacity
        belongs to the machine; the pool belongs to the new row (D13).
        """
        held = await conn.fetch(
            """SELECT executor_id FROM execution_budget
            WHERE container_id=$1 AND executor_id<>$2 FOR UPDATE""",
            host.container_id,
            host.host_id,
        )
        free = await conn.fetchval(
            """SELECT COALESCE(SUM(capacity-in_use),0)::text FROM execution_budget
            WHERE container_id=$1 AND executor_id<>$2""",
            host.container_id,
            host.host_id,
        )
        inserted = await conn.fetchval(
            """INSERT INTO execution_budget (executor_id,container_id,capacity,pool_id,reap_scope)
            VALUES ($1,$2,$3,$4,$5) ON CONFLICT (executor_id) DO NOTHING RETURNING executor_id""",
            host.host_id,
            host.container_id,
            int(free or 0) if held else capacity,
            host.pool.pool_id,
            host.reap_scope,
        )
        # Rows from before the scope column (D13): one container runs on one
        # daemon, so a successor in the same container proves the same scope.
        # Never inferred any other way; rows with no such successor stay NULL,
        # unfenceable and charged, for the D5 alert.
        await conn.execute(
            """UPDATE execution_budget SET reap_scope=$2
            WHERE container_id=$1 AND reap_scope IS NULL""",
            host.container_id,
            host.reap_scope,
        )
        if inserted is not None and held:
            await conn.execute(
                """UPDATE execution_budget SET capacity=in_use,successor_id=$2
                WHERE container_id=$1 AND executor_id<>$2""",
                host.container_id,
                host.host_id,
            )

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
            # A retired predecessor's slot goes back to the machine, which is now
            # its successor's: capacity moves with the release, never sooner (D3).
            await conn.execute(
                """WITH b AS (UPDATE execution_budget SET in_use=in_use-1,
                    capacity=capacity-(successor_id IS NOT NULL)::int
                    WHERE executor_id=$1 RETURNING successor_id)
                UPDATE execution_budget s SET capacity=s.capacity+1
                FROM b WHERE s.executor_id=b.successor_id""",
                charged,
            )
            if retry_seconds > 0:
                # now() is the transaction's start, so the lock waits above would
                # spend the backoff. Stamp it once both locks are held.
                await conn.execute(
                    """UPDATE execution_runs
                    SET retry_at=clock_timestamp()+$2::double precision*interval '1 second'
                    WHERE execution_id=$1""",
                    execution_id,
                    retry_seconds,
                )
