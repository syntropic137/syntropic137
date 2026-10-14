"""A real executor process for the V7/V12 tests, so it can be SIGKILLed or SIGSTOPped.

Not a test module. Usage (only the 1.5 process tests run it)::

    python _1310_executor_process.py PG_URL SCHEMA ES_ADDRESS TENANT HOST_ID LEASE_S OUT

A real ``ExecutionHost`` over the real Run Queue claims the one admitted run.
Its drainer starts one real workspace container labelled for this host and run,
loads the execution aggregate, reports ``claimed`` and stalls. When the host
self-fences (renew raised ``RunLeaseLost``) the drain is cancelled; the stalled
owner then tries its terminal commit from the aggregate it loaded and reports
whether the event store refused it. Its reconciler is production's: the
``DockerDeadHostReaper`` and ``AggregateRunInterrupter``, so a live one of these
fences, reaps and interrupts a dead peer's run. Every report is one JSON line in OUT.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path

import asyncpg
from event_sourcing import EventStoreRepository

from syn_adapters.execution_host import AggregateRunInterrupter, ExecutionHost, HostTiming
from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_adapters.storage.legacy_tolerant_client import LegacyShapeTolerantGrpcClient
from syn_adapters.storage.repositories import EventStoreExecutionEventStream, RepositoryAdapter
from syn_api.services.dead_host_reaper import DockerDeadHostReaper
from syn_domain.contexts.orchestration import (
    ORCHESTRATION_EVENT_EPOCH,
    InterruptExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.ports import ClaimedRun, ExecutorHost


def _report(out: Path, **line: object) -> None:
    with out.open("a") as f:
        f.write(json.dumps(line) + "\n")


class _StallingDrainer:
    def __init__(self, executions: RepositoryAdapter, host_id: str, out: Path) -> None:
        self._executions, self._host_id, self._out = executions, host_id, out

    async def run_claimed(self, run: ClaimedRun) -> object:
        name = f"agentic-ws-1310-{run.execution_id}"
        proc = await asyncio.create_subprocess_exec(
            "docker", "run", "-d", "--name", name,
            "--label", f"syn.host_id={self._host_id}",
            "--label", f"syn.execution_id={run.execution_id}",
            "alpine:3", "sleep", "600",
            stdout=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        await proc.wait()
        stale = await self._executions.get_by_id(run.execution_id)
        assert stale is not None
        _report(self._out, event="claimed", run=run.model_dump(), container=name)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            _report(self._out, event="self_fenced")
            stale.interrupt_execution(
                InterruptExecutionCommand(
                    execution_id=run.execution_id,
                    phase_id=stale.running_phase_id or "",
                    reason="stale owner's terminal commit",
                )
            )
            try:
                await self._executions.save(stale)
            except Exception as refused:
                _report(self._out, event="stale_append_refused", error=type(refused).__name__)
            else:
                _report(self._out, event="stale_append_accepted")
            raise
        return None


async def main(
    pg_url: str, schema: str, es: str, tenant: str, host_id: str, lease: str, out: str
) -> None:
    ttl = timedelta(seconds=float(lease))
    pool = await asyncpg.create_pool(pg_url, server_settings={"search_path": schema})
    assert pool is not None
    clients = [LegacyShapeTolerantGrpcClient(address=es, tenant_id=tenant) for _ in range(2)]
    for client in clients:
        await client.connect()
    executions = RepositoryAdapter(
        EventStoreRepository(
            clients[0],
            WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "WorkflowExecution",
        )
    )
    host = ExecutorHost(
        host_id=host_id,
        container_id=f"c-{host_id}",
        generation="g1",
        epoch=ORCHESTRATION_EVENT_EPOCH,
    )
    await ExecutionHost(
        PostgresExecutionRunQueue(pool, lease_ttl=ttl),  # type: ignore[arg-type]  # asyncpg.Pool vs Pool
        host,
        capacity=1,
        drainer=_StallingDrainer(executions, host_id, Path(out)),
        reaper=DockerDeadHostReaper(),
        interrupter=AggregateRunInterrupter(executions),
        streams=EventStoreExecutionEventStream(clients[1]),
        timing=HostTiming(loop_interval=timedelta(milliseconds=200), lease_ttl=ttl),
    ).run_until_drained()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:8]))
