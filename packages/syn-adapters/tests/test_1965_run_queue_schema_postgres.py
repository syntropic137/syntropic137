"""Real-Postgres acceptance for applying the Run Queue schema (#1965).

Needs Docker (marked integration); CI runs it. The statement-order half is
``test_1965_run_queue_schema_lock.py``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import asyncpg
import pytest

from syn_adapters.advisory_locks import RUN_QUEUE_SCHEMA_LOCK_KEY
from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_adapters.execution_runs.postgres import SCHEMA_STEPS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = pytest.mark.integration

_PRE_POOL_SCHEMA = Path(__file__).parent / "fixtures" / "execution_runs" / "schema_pre_pool.sql"
_TABLES = ("executor_hosts", "executor_pools", "execution_budget", "execution_runs")


async def _fresh_schema(url: str) -> tuple[asyncpg.Connection, str]:
    schema = f"run_queue_1965_{uuid4().hex}"
    admin = await asyncpg.connect(url)
    await admin.execute(f"CREATE SCHEMA {schema}")
    return admin, schema


@pytest.fixture
async def pre_pool(test_infrastructure: TestInfrastructure) -> AsyncIterator[asyncpg.Pool]:
    """A schema holding v1.0.0-era Run Queue tables and rows, before any ledger."""
    admin, schema = await _fresh_schema(test_infrastructure.timescaledb_url)
    pool = await asyncpg.create_pool(
        test_infrastructure.timescaledb_url, server_settings={"search_path": schema}
    )
    assert pool is not None
    try:
        async with pool.acquire() as conn:
            await conn.execute(_PRE_POOL_SCHEMA.read_text())
            await conn.execute(
                """INSERT INTO executor_hosts (host_id,container_id,generation,epoch)
                VALUES ('old','c-old','g0',1)"""
            )
            await conn.execute(
                """INSERT INTO execution_budget (executor_id,container_id,capacity,in_use)
                VALUES ('old','c-old',2,1)"""
            )
            await conn.execute(
                """INSERT INTO execution_runs (execution_id,state,is_resume,writer_epoch,
                    executor_id,lease_token,admitted_at)
                VALUES ('exec-held','claimed',FALSE,1,'old',1,now())"""
            )
        yield pool
    finally:
        await pool.close()
        await admin.execute(f"DROP SCHEMA {schema} CASCADE")
        await admin.close()


async def _snapshot(pool: asyncpg.Pool) -> tuple[object, ...]:
    """Everything an apply could change: catalogue, rows and the ledger."""
    async with pool.acquire() as conn:
        columns = await conn.fetch(
            """SELECT table_name,column_name,data_type,is_nullable,column_default
            FROM information_schema.columns WHERE table_schema=current_schema()
            ORDER BY table_name,column_name"""
        )
        constraints = await conn.fetch(
            """SELECT c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c
            JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname=current_schema()
            ORDER BY c.conname"""
        )
        indexes = await conn.fetch(
            """SELECT indexname,indexdef FROM pg_indexes
            WHERE schemaname=current_schema() ORDER BY indexname"""
        )
        rows = [await conn.fetch(f"SELECT * FROM {table} ORDER BY 1") for table in _TABLES]
        ledger = await conn.fetch(
            "SELECT step,applied_at FROM execution_run_queue_schema_steps ORDER BY step"
        )
    return (
        [tuple(r) for r in columns],
        [tuple(r) for r in constraints],
        [tuple(r) for r in indexes],
        [[tuple(r) for r in table] for table in rows],
        [tuple(r) for r in ledger],
    )


async def test_applying_twice_on_pre_pool_data_changes_nothing_the_second_time(
    pre_pool: asyncpg.Pool,
) -> None:
    queue = PostgresExecutionRunQueue(pre_pool)
    await queue.ensure_ready()
    first = await _snapshot(pre_pool)

    await queue.ensure_ready()

    assert await _snapshot(pre_pool) == first
    ledger = first[4]
    assert isinstance(ledger, list)
    assert sorted(step for step, _ in ledger) == sorted(s.name for s in SCHEMA_STEPS)
    # The upgrade kept the v1.0.0 rows.
    async with pre_pool.acquire() as conn:
        assert await conn.fetchval("SELECT state FROM execution_runs") == "claimed"
        assert await conn.fetchval("SELECT pool_id FROM execution_budget") == "default"


async def test_an_image_from_before_pools_still_runs_after_the_upgrade(
    pre_pool: asyncpg.Pool,
) -> None:
    """A downgrade to a pre-#1931 image: its schema and its writes still apply.

    Pre-#1931 code never named ``backend``, so dropping it is not what makes
    the Run Queue forward-only (#1965 item 2).
    """
    await PostgresExecutionRunQueue(pre_pool).ensure_ready()
    async with pre_pool.acquire() as conn:
        # The older image's ensure_ready, then its register and claim shapes.
        await conn.execute(_PRE_POOL_SCHEMA.read_text())
        await conn.execute(
            """INSERT INTO execution_budget (executor_id,container_id,capacity)
            VALUES ('older','c-older',1)"""
        )
        await conn.execute(
            """UPDATE execution_budget SET in_use=in_use+1, heartbeat_at=now()
            WHERE executor_id='older'"""
        )
        assert (
            await conn.fetchval("SELECT pool_id FROM execution_budget WHERE executor_id='older'")
            == "default"
        )


_APPLY_IN_ANOTHER_PROCESS = """
import asyncio, sys
import asyncpg
from syn_adapters.execution_runs import PostgresExecutionRunQueue

async def main(url, schema, name):
    pool = await asyncpg.create_pool(
        url, min_size=1, max_size=1,
        server_settings={"search_path": schema, "application_name": name},
    )
    try:
        await PostgresExecutionRunQueue(pool).ensure_ready()
    finally:
        await pool.close()

asyncio.run(main(*sys.argv[1:4]))
"""


async def _connected(admin: asyncpg.Connection, name: str, count: int) -> None:
    for _ in range(600):
        if (
            await admin.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE application_name=$1", name
            )
            >= count
        ):
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"{count} processes named {name!r} never connected")


async def test_two_processes_applying_together_both_succeed_one_at_a_time(
    test_infrastructure: TestInfrastructure,
) -> None:
    url = test_infrastructure.timescaledb_url
    admin, schema = await _fresh_schema(url)
    name = f"run_queue_1965_{uuid4().hex[:12]}"
    try:
        # Hold the key so both processes are provably waiting at once, then let
        # them race for it.
        await admin.execute("SELECT pg_advisory_lock($1)", RUN_QUEUE_SCHEMA_LOCK_KEY)
        processes = [
            await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                _APPLY_IN_ANOTHER_PROCESS,
                url,
                schema,
                name,
                stderr=asyncio.subprocess.PIPE,
            )
            for _ in range(2)
        ]
        await _connected(admin, name, 2)
        await asyncio.sleep(0.5)
        assert not await admin.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname=$1)", schema
        ), "a process applied the schema while another held the lock"
        await admin.execute("SELECT pg_advisory_unlock($1)", RUN_QUEUE_SCHEMA_LOCK_KEY)

        results = await asyncio.wait_for(
            asyncio.gather(*(p.communicate() for p in processes)), timeout=60
        )
        for process, (_, stderr) in zip(processes, results, strict=True):
            assert process.returncode == 0, stderr.decode()
        steps = await admin.fetch(f"SELECT step FROM {schema}.execution_run_queue_schema_steps")
        assert sorted(r["step"] for r in steps) == sorted(s.name for s in SCHEMA_STEPS)
    finally:
        await admin.execute("SELECT pg_advisory_unlock_all()")
        await admin.execute(f"DROP SCHEMA {schema} CASCADE")
        await admin.close()
