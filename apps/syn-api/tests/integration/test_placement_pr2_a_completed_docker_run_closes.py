"""Reap-before-close on real Docker and real Postgres (placement plan PR 2, ADR-072 D3, R7).

The owner closes a drained run only once ``DockerDeadHostReaper`` shows its
containers gone. These pin that the gate never reroutes a healthy Docker run
through fencing: whether the drain tore its workspace down (the normal path)
or left it behind, the run closes under its own claim, the lease token never
moves, and nothing labelled for the run is left on the engine.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import asyncpg
import pytest

from syn_adapters.execution_host import ExecutionHost, HostTiming
from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_adapters.workspace_backends.host_labels import LABEL_HOST_ID
from syn_api.services.dead_host_reaper import LABEL_EXECUTION_ID, DockerDeadHostReaper
from syn_domain.contexts.orchestration.ports import ClaimedRun, ExecutorHost, StreamPresence

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="requires Docker"),
]

IMAGE = os.environ.get("SYN_SPOOL_RELEASE_TEST_IMAGE", "alpine:3")
_TTL = timedelta(seconds=3)
_TIMING = HostTiming(
    loop_interval=timedelta(milliseconds=100),
    lease_ttl=_TTL,
    turn_budget=timedelta(milliseconds=500),
)


async def _docker(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode().strip()


@pytest.fixture
async def pool(test_infrastructure: TestInfrastructure) -> AsyncIterator[asyncpg.Pool]:
    code, _ = await _docker("image", "inspect", IMAGE)
    if code != 0:
        pytest.skip(f"{IMAGE} is not available locally")
    schema = f"run_queue_pr2_{uuid4().hex}"
    admin = await asyncpg.connect(test_infrastructure.timescaledb_url)
    await admin.execute(f"CREATE SCHEMA {schema}")
    created = await asyncpg.create_pool(
        test_infrastructure.timescaledb_url, server_settings={"search_path": schema}
    )
    assert created is not None
    try:
        await PostgresExecutionRunQueue(created).ensure_ready()
        yield created
    finally:
        await created.close()
        await admin.execute(f"DROP SCHEMA {schema} CASCADE")
        await admin.close()


class _DockerDrain:
    """Runs one labelled workspace stand-in, then tears it down unless ``leave`` is set."""

    def __init__(self, name: str, *, leave: bool) -> None:
        self.name, self.leave = name, leave
        self.done = asyncio.Event()

    async def run_claimed(self, claimed: ClaimedRun) -> object:
        code, _ = await _docker(
            "run",
            "-d",
            "--name",
            self.name,
            f"--label={LABEL_HOST_ID}={claimed.executor_id}",
            f"--label={LABEL_EXECUTION_ID}={claimed.execution_id}",
            IMAGE,
            "sleep",
            "300",
        )
        assert code == 0, f"could not start {self.name}"
        if not self.leave:
            await _docker("rm", "-f", self.name)
        self.done.set()
        return "completed"


class _Streams:
    async def presence(self, execution_id: str) -> StreamPresence:
        return StreamPresence.PRESENT


class _NoInterrupt:
    async def interrupt(self, run: object) -> None:
        raise AssertionError(f"a healthy run was interrupted: {run}")


@pytest.mark.parametrize("leave", [False, True], ids=["torn-down", "left-behind"])
async def test_a_completed_docker_run_is_shown_released_and_closes(
    pool: asyncpg.Pool, leave: bool
) -> None:
    tag = uuid4().hex[:8]
    reaper = DockerDeadHostReaper()
    queue = PostgresExecutionRunQueue(pool, lease_ttl=_TTL)
    host_id = f"pr2-{tag}"
    drain = _DockerDrain(f"agentic-ws-pr2-{tag}", leave=leave)
    host = ExecutionHost(
        queue,
        ExecutorHost(
            host_id=host_id,
            container_id=f"c-{host_id}",
            generation="g1",
            epoch=1,
            reap_scope=await asyncio.to_thread(reaper.scope),
        ),
        capacity=1,
        drainer=drain,
        reaper=reaper,
        interrupter=_NoInterrupt(),  # type: ignore[arg-type]
        streams=_Streams(),
        timing=_TIMING,
    )
    await host.join()
    execution_id = f"exec-pr2-{tag}"
    assert await queue.reserve(execution_id, 1, is_resume=False)
    await queue.mark_admitted(execution_id)
    task = asyncio.create_task(host.run_until_drained())
    try:
        await asyncio.wait_for(drain.done.wait(), 60)
        deadline = time.monotonic() + 60
        while True:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT state, lease_token FROM execution_runs WHERE execution_id=$1",
                    execution_id,
                )
            assert row is not None
            if row["state"] != "claimed" or time.monotonic() > deadline:
                break
            await asyncio.sleep(0.1)
        assert (row["state"], row["lease_token"]) == ("done", 1)  # closed, never fenced
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT in_use FROM execution_budget WHERE executor_id=$1", host_id
                )
                == 0
            )
        _, left = await _docker(
            "ps",
            "-aq",
            "--filter",
            f"label={LABEL_HOST_ID}={host_id}",
            "--filter",
            f"label={LABEL_EXECUTION_ID}={execution_id}",
        )
        assert left == ""
    finally:
        host.drain()
        try:
            await asyncio.wait_for(task, 30)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await _docker("rm", "-f", drain.name)
