"""V7 and V7b on real processes, Postgres, event store and Docker (#1310 1.5, ADR-072 D5, D6).

Executors A and B are separate processes (``_1310_executor_process.py``), each
a real ``ExecutionHost`` with production's reaper and interrupter, each holding
one admitted run in a real workspace container and a legacy sidecar, both
labelled by production's label producers.

* V7: A is SIGKILLed. B, still live, fences A's run on Lease expiry, reaps it
  and interrupts it. Only A's workspace and sidecar are removed, B's survive and B's run
  stays claimed; A's stream ends ``WorkflowInterrupted`` and A's slot is
  released.
* V7b: an unlabelled workspace container is left, with a WARN, while B's real
  heartbeat is live, and is reaped once B is SIGKILLed and its heartbeat stale.

Run: ``uv run pytest -m integration apps/syn-api/tests/integration/test_1310_v7_a_killed_executor_is_reaped_by_a_live_one.py``
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
import sys
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_api.services.unlabelled_containers import reap_unlabelled_if_alone
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler

from .test_1310_a_claimed_three_phase_run_succeeds_on_real_stores import (  # noqa: F401  # fixtures
    _Infra,
    _start,
    infra,
    pool,
)
from .test_1310_v12_a_stalled_executor_is_fenced_by_a_live_one import (
    _CHILD,
    _containers,
    _until,
)

if TYPE_CHECKING:
    from pathlib import Path

    import asyncpg
    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="requires Docker"),
]

_LEASE_S = 2.0
_WAIT_S = 60


async def _spawn(
    world: _Infra, url: str, schema: str, host_id: str, out: Path
) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable, str(_CHILD), url, schema, world.address, world.tenant,
        host_id, str(_LEASE_S), str(out),
    )  # fmt: skip


async def _docker(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await proc.communicate()
    return out.decode().strip()


async def test_v7_and_v7b_a_killed_executor_is_reaped_by_a_live_one(
    infra: _Infra,  # noqa: F811
    pool: asyncpg.Pool,  # noqa: F811
    test_infrastructure: TestInfrastructure,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with pool.acquire() as conn:
        schema = await conn.fetchval("SELECT current_schema()")
    url = test_infrastructure.timescaledb_url
    a_host, b_host = f"v7-a-{uuid4().hex[:6]}", f"v7-b-{uuid4().hex[:6]}"
    unlabelled = f"agentic-ws-v7b-{uuid4().hex[:6]}"
    children: list[asyncio.subprocess.Process] = []
    try:
        claimed: list[str] = []
        for host_id in (a_host, b_host):
            admitting, _ = await infra.processor(
                FakeAgentExecutionHandler.success(produces=A_DELIVERABLE), queued=True
            )
            execution_id = f"exec-{uuid4().hex[:12]}"
            assert await _start(admitting, execution_id) == "admitted"
            out = tmp_path / f"{host_id}.jsonl"
            children.append(await _spawn(infra, url, schema, host_id, out))
            run = (await _until(out, "claimed")).run
            assert run is not None
            assert run.execution_id == execution_id
            claimed.append(execution_id)
        a, b = children
        # Each host holds a workspace and a legacy sidecar for its run.
        assert len(await _containers(a_host)) == len(await _containers(b_host)) == 2

        # V7: A dies; B's own loop fences, reaps and interrupts A's run.
        a.kill()
        await a.wait()
        async with asyncio.timeout(_WAIT_S):
            while (await infra.queue.in_use()).interrupted != 1:
                await asyncio.sleep(0.2)
        assert await _containers(a_host) == []
        assert len(await _containers(b_host)) == 2
        a_types = await infra.event_types(claimed[0])
        assert a_types.count("WorkflowInterrupted") == 1, a_types
        assert a_types[-1] == "WorkflowInterrupted", a_types
        b_types = await infra.event_types(claimed[1])
        assert "WorkflowInterrupted" not in b_types, b_types
        counts = await infra.queue.in_use()
        assert (counts.claimed, counts.fencing, counts.reaped) == (1, 0, 0)
        async with pool.acquire() as conn:
            a_in_use = await conn.fetchval(
                "SELECT in_use FROM execution_budget WHERE executor_id=$1", a_host
            )
        assert a_in_use == 0

        # V7b: an unlabelled container is B's as far as anyone can tell while B is live.
        await _docker("run", "-d", "--name", unlabelled, "alpine:3", "sleep", "600")
        live = PostgresExecutionRunQueue(pool, heartbeat_stale=timedelta(seconds=1))
        with caplog.at_level(logging.WARNING):
            await reap_unlabelled_if_alone(live, "v7b-observer")
        assert await _docker("ps", "-aq", "--filter", f"name={unlabelled}")
        assert any(
            "unlabelled" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records
        )
        b.kill()
        await b.wait()
        await asyncio.sleep(2)
        await reap_unlabelled_if_alone(live, "v7b-observer")
        assert not await _docker("ps", "-aq", "--filter", f"name={unlabelled}")
    finally:
        for child in children:
            with contextlib.suppress(ProcessLookupError):
                os.kill(child.pid, signal.SIGKILL)
            await child.wait()
        for host_id in (a_host, b_host):
            for container in await _containers(host_id):
                await _docker("rm", "-f", container)
        await _docker("rm", "-f", unlabelled)
