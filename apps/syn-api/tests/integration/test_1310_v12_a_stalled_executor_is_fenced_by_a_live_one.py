"""V12 on real processes, Postgres, event store and Docker (#1310 1.5, ADR-072 D5).

Executor A is a separate process (``_1310_executor_process.py``) running a real
``ExecutionHost``: it claims the admitted run, starts its labelled workspace
and legacy sidecar containers and stalls. It is SIGSTOPped past its Lease. Executor B, in this
process, fences A's run, reaps it with the production ``DockerDeadHostReaper``
and interrupts it through the aggregate. A is then SIGCONTed. Asserted:

* removal of A's containers precedes the interruption append;
* A's renewal is refused, A self-fences, and its terminal commit from the
  aggregate it loaded before the stall is refused by the event store with
  ``ConcurrencyConflictError``: any other failure of that commit fails the test;
* the stream has one ``WorkflowExecutionStarted`` and one terminal event,
  ``WorkflowInterrupted``; A made one workspace, never a second;
* A's stale token can neither renew nor close the row.

Run: ``uv run pytest -m integration apps/syn-api/tests/integration/test_1310_v12_a_stalled_executor_is_fenced_by_a_live_one.py``
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from syn_adapters.execution_host import AggregateRunInterrupter
from syn_adapters.execution_host.reconciler import Reconciler
from syn_api.services.dead_host_reaper import DockerDeadHostReaper
from syn_domain.contexts.orchestration import ORCHESTRATION_EVENT_EPOCH
from syn_domain.contexts.orchestration.ports import (
    ClaimedRun,
    ExecutorHost,
    FencedRun,
    RunLeaseLost,
)
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler

from .test_1310_a_claimed_three_phase_run_succeeds_on_real_stores import (  # noqa: F401  # fixtures
    _Infra,
    _start,
    infra,
    pool,
)

if TYPE_CHECKING:
    import asyncpg
    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="requires Docker"),
]

_CHILD = Path(__file__).with_name("_1310_executor_process.py")
_LEASE_S = 2.0
_WAIT_S = 60


class _Report(BaseModel):
    """One JSON line the executor process wrote."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event: str
    run: ClaimedRun | None = None
    container: str | None = None
    error: str | None = None


def _lines(out: Path) -> list[_Report]:
    if not out.exists():
        return []
    return [_Report.model_validate_json(line) for line in out.read_text().splitlines()]


async def _until(out: Path, event: str) -> _Report:
    async with asyncio.timeout(_WAIT_S):
        while not (found := [line for line in _lines(out) if line.event == event]):
            await asyncio.sleep(0.1)
    return found[0]


async def _containers(host_id: str) -> list[str]:
    proc = await asyncio.create_subprocess_exec(
        "docker", "ps", "-aq", "--filter", f"label=syn.host_id={host_id}",
        stdout=asyncio.subprocess.PIPE,
    )  # fmt: skip
    out, _ = await proc.communicate()
    return out.decode().split()


class _Ordered:
    """The production reaper and interrupter, recording what each saw, in order."""

    def __init__(self, interrupter: AggregateRunInterrupter, a_host: str) -> None:
        self._reaper, self._interrupter, self._a = DockerDeadHostReaper(), interrupter, a_host
        self.log: list[str] = []

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        done = await self._reaper.reap(executor_id, execution_id)
        self.log.append(f"reaped:{done}:left={len(await _containers(self._a))}")
        return done

    async def interrupt(self, run: FencedRun) -> None:
        self.log.append(f"interrupt:left={len(await _containers(self._a))}")
        await self._interrupter.interrupt(run)


async def _reconcile_turn(reconciler: Reconciler) -> None:
    """One acquiring turn, then wait for its attempts: a turn no longer awaits them (#1944)."""
    await reconciler.turn(acquire=True)
    async with asyncio.timeout(60):
        while not reconciler.idle:
            await asyncio.sleep(0.01)


async def test_v12_a_stalled_executor_is_fenced_and_its_stale_commit_refused(
    infra: _Infra,  # noqa: F811
    pool: asyncpg.Pool,  # noqa: F811
    test_infrastructure: TestInfrastructure,
    tmp_path: Path,
) -> None:
    admitting, _ = await infra.processor(
        FakeAgentExecutionHandler.success(produces=A_DELIVERABLE), queued=True
    )
    execution_id = f"exec-{uuid4().hex[:12]}"
    assert await _start(admitting, execution_id) == "admitted"
    async with pool.acquire() as conn:
        schema = await conn.fetchval("SELECT current_schema()")
    a_host, out = f"v12-a-{uuid4().hex[:6]}", tmp_path / "a.jsonl"
    child = await asyncio.create_subprocess_exec(
        sys.executable, str(_CHILD), test_infrastructure.timescaledb_url, schema,
        infra.address, infra.tenant, a_host, str(_LEASE_S), str(out),
    )  # fmt: skip
    try:
        claimed = (await _until(out, "claimed")).run
        assert claimed is not None
        assert len(await _containers(a_host)) == 2  # workspace and sidecar

        os.kill(child.pid, signal.SIGSTOP)
        await asyncio.sleep(_LEASE_S * 2)
        b = ExecutorHost(
            reap_scope=DockerDeadHostReaper().scope(),  # A's daemon, so B may fence A
            host_id=f"v12-b-{uuid4().hex[:6]}",
            container_id="c-v12-b",
            generation="g1",
            epoch=ORCHESTRATION_EVENT_EPOCH,
        )
        await infra.queue.register(b, capacity=1)
        await infra.queue.heartbeat(b.host_id)
        ordered = _Ordered(AggregateRunInterrupter(await infra.executions()), a_host)
        await _reconcile_turn(Reconciler(infra.queue, b.host_id, ordered, ordered))
        assert ordered.log == ["reaped:True:left=0", "interrupt:left=0"]
        assert (await infra.queue.in_use()).interrupted == 1

        os.kill(child.pid, signal.SIGCONT)
        await _until(out, "self_fenced")
        refused = await _until(out, "stale_append_refused")
        assert refused.error == "ConcurrencyConflictError", refused
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(child.pid, signal.SIGCONT)
            child.terminate()
        await child.wait()

    with pytest.raises(RunLeaseLost):
        await infra.queue.renew(claimed)
    with pytest.raises(RunLeaseLost):
        await infra.queue.close(claimed)
    assert [line.event for line in _lines(out)].count("claimed") == 1  # one workspace
    assert await _containers(a_host) == []
    types = await infra.event_types(execution_id)
    assert types.count("WorkflowExecutionStarted") == 1, types
    assert types.count("WorkflowInterrupted") == 1, types
    assert types[-1] == "WorkflowInterrupted", types
    assert not {"WorkflowCompleted", "WorkflowFailed"} & set(types), types
