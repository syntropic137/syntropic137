"""Reap-before-close does not reroute a healthy Docker run (ADR-072 D3, D13; #1734 PR 2).

The host now closes a run only once its reaper shows the run's containers gone.
On Docker the processor tears its workspace down before the drain returns, so
the production ``DockerDeadHostReaper`` finds nothing left and the run closes
through the normal path: ``done``, slot freed, never fenced. The scope the
budget records is this daemon's real engine ID.

A run whose container is still there when the drain returns is removed by that
same reap, and still closes: the gate reaps, it does not only look.

Run: ``uv run pytest -m integration apps/syn-api/tests/integration/test_1734_reap_before_close_on_real_docker.py``
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.execution_host import ExecutionHost, HostTiming
from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_api.services.dead_host_reaper import DockerDeadHostReaper
from syn_domain.contexts.orchestration import ORCHESTRATION_EVENT_EPOCH
from syn_domain.contexts.orchestration.ports import ExecutorHost, StreamPresence

from .test_1310_a_claimed_three_phase_run_succeeds_on_real_stores import (  # noqa: F401  # fixtures
    pool,
)
from .test_1310_v7_dead_host_reap_on_real_docker import (  # noqa: F401  # fixtures
    _Containers,
    _docker,
    _exists,
    _labels_as,
    containers,
)

if TYPE_CHECKING:
    import asyncpg

    from syn_domain.contexts.orchestration.ports import ClaimedRun, FencedRun

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="requires Docker"),
]


class _Interrupter:
    async def interrupt(self, run: FencedRun) -> None:
        raise AssertionError(f"a healthy run was reconciled: {run.execution_id}")


class _NoStreams:
    async def presence(self, execution_id: str) -> StreamPresence:
        return StreamPresence.UNKNOWN


class _DockerDrain:
    """Runs one labelled stand-in workspace per run; ``tear_down`` removes it, as ``_drain``'s finally does."""

    def __init__(self, started: _Containers, labels: dict[str, str], *, tear_down: bool) -> None:
        self._containers, self._labels, self._tear_down = started, labels, tear_down
        self.names: list[str] = []

    async def run_claimed(self, claimed: ClaimedRun) -> object:
        name = f"agentic-ws-{claimed.execution_id}"
        labels = {**self._labels, "syn.execution_id": claimed.execution_id}
        await self._containers.run(name, labels)
        self.names.append(name)
        if self._tear_down:
            code, _ = await _docker("rm", "-f", name)
            assert code == 0
        return "completed"


async def _one_run(
    store: asyncpg.Pool, drainer: _DockerDrain, host_id: str, execution_id: str
) -> PostgresExecutionRunQueue:
    queue = PostgresExecutionRunQueue(store)
    reaper = DockerDeadHostReaper()
    host = ExecutionHost(
        queue,
        ExecutorHost(
            host_id=host_id,
            container_id=f"c-{host_id}",
            generation="g1",
            epoch=ORCHESTRATION_EVENT_EPOCH,
            reap_scope=reaper.scope(),
        ),
        capacity=1,
        drainer=drainer,
        reaper=reaper,
        interrupter=_Interrupter(),
        streams=_NoStreams(),
        timing=HostTiming(loop_interval=timedelta(milliseconds=50)),
    )
    loop = asyncio.create_task(host.run_until_drained())
    assert await queue.reserve(execution_id, ORCHESTRATION_EVENT_EPOCH, is_resume=False)
    await queue.mark_admitted(execution_id)
    async with asyncio.timeout(60):
        while (await queue.in_use()).done < 1:
            await asyncio.sleep(0.05)
        host.drain()
        await loop
    return queue


@pytest.mark.may_skip(
    reason="needs a Docker daemon and the alpine stand-in image; integration-evidence has both",
    issue="#1734",
)
@pytest.mark.parametrize("tear_down", [True, False], ids=["torn-down", "left-running"])
async def test_a_completed_docker_run_is_shown_released_and_closes(
    pool: asyncpg.Pool,  # noqa: F811  # the fixture imported above
    containers: _Containers,  # noqa: F811  # the fixture imported above
    monkeypatch: pytest.MonkeyPatch,
    tear_down: bool,
) -> None:
    tag = uuid4().hex[:8]
    execution_id = f"exec-1734-{tag}"
    workspace, _ = _labels_as(f"host-1734-{tag}", execution_id, monkeypatch)
    host_id = workspace["syn.host_id"]
    drainer = _DockerDrain(containers, workspace, tear_down=tear_down)

    queue = await _one_run(pool, drainer, host_id, execution_id)

    counts = await queue.in_use()
    assert (counts.done, counts.claimed, counts.fencing, counts.interrupted) == (1, 0, 0, 0)
    async with pool.acquire() as conn:
        budget = await conn.fetchrow(
            "SELECT in_use, reap_scope FROM execution_budget WHERE executor_id=$1", host_id
        )
    assert budget is not None
    assert budget["in_use"] == 0
    assert budget["reap_scope"] == DockerDeadHostReaper().scope()
    (name,) = drainer.names
    assert not await _exists(name)
