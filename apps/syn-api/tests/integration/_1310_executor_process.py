"""A real executor process for the V7/V12 tests, so it can be SIGKILLed or SIGSTOPped.

Not a test module. Usage (only the 1.5 process tests run it)::

    python _1310_executor_process.py PG_URL SCHEMA ES_ADDRESS TENANT HOST_ID LEASE_S OUT

A real ``ExecutionHost`` over the real Run Queue claims the one admitted run.
Its drainer starts the two containers production starts for a run, a workspace
and a legacy sidecar, labelled by production's own label producers as this host
would stamp them; loads the execution aggregate, reports ``claimed`` and
stalls. When the host self-fences (renew raised ``RunLeaseLost``) the drain is
cancelled; the stalled owner then tries its terminal commit from the aggregate
it loaded and reports the event store's ``ConcurrencyConflictError``. Any other
failure of that commit is not a fencing refusal and is not reported as one: it
propagates, so the test waiting for the refusal fails. Its reconciler is production's: the
``DockerDeadHostReaper`` and ``AggregateRunInterrupter``, so a live one of these
fences, reaps and interrupts a dead peer's run. Every report is one JSON line in OUT.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import asyncpg
from event_sourcing import ConcurrencyConflictError, EventStoreRepository

from syn_adapters.execution_host import AggregateRunInterrupter, ExecutionHost, HostTiming
from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_adapters.storage.legacy_tolerant_client import LegacyShapeTolerantGrpcClient
from syn_adapters.storage.repositories import EventStoreExecutionEventStream, RepositoryAdapter
from syn_adapters.workspace_backends.agentic.adapter import _container_labels
from syn_adapters.workspace_backends.docker.docker_sidecar_helpers import (
    build_sidecar_docker_cmd,
)
from syn_adapters.workspace_backends.host_labels import LABEL_HOST_ID, host_labels
from syn_api.services.dead_host_reaper import DockerDeadHostReaper
from syn_domain.contexts.orchestration import (
    ORCHESTRATION_EVENT_EPOCH,
    InterruptExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
    SidecarConfig,
)
from syn_domain.contexts.orchestration.ports import ClaimedRun, ExecutorHost
from syn_shared.settings import reset_settings


def _report(out: Path, **line: object) -> None:
    with out.open("a") as f:
        f.write(json.dumps(line) + "\n")


class _StallingDrainer:
    def __init__(self, executions: RepositoryAdapter, out: Path) -> None:
        self._executions, self._out = executions, out

    async def run_claimed(self, run: ClaimedRun) -> object:
        name = f"agentic-ws-1310-{run.execution_id}"
        await _start_container(name, _workspace_labels(run.execution_id))
        await _start_container(
            f"syn-sidecar-1310-{run.execution_id}", _sidecar_labels(run.execution_id)
        )
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
            except ConcurrencyConflictError as refused:
                _report(self._out, event="stale_append_refused", error=type(refused).__name__)
            else:
                _report(self._out, event="stale_append_accepted")
            raise
        return None


def _workspace_labels(execution_id: str) -> dict[str, str]:
    return _container_labels(
        IsolationConfig(execution_id=execution_id, workspace_id=f"ws-{execution_id}")
    )


def _sidecar_labels(execution_id: str) -> dict[str, str]:
    cmd = build_sidecar_docker_cmd(
        SidecarConfig(workspace_id=f"ws-{execution_id}", execution_id=execution_id),
        container_name="unused",
        network_name="unused",
        token_service_url="http://unused",
        default_image="unused",
    )
    return dict(
        arg.removeprefix("--label=").split("=", 1) for arg in cmd if arg.startswith("--label=")
    )


async def _start_container(name: str, labels: dict[str, str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        "docker", "run", "-d", "--name", name,
        *(f"--label={key}={value}" for key, value in labels.items()),
        "alpine:3", "sleep", "600",
        stdout=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    if await proc.wait() != 0:
        raise RuntimeError(f"`docker run` for {name} exited {proc.returncode}")


def _stamp_as(host_id: str) -> None:
    """Make production's ``host_labels()`` stamp exactly ``host_id`` in this process."""
    os.environ["SYN_HOST_ID"] = host_id
    os.environ["SYN_EXECUTION_RUN_QUEUE_ENABLED"] = "false"  # no per-process suffix
    reset_settings()
    assert host_labels()[LABEL_HOST_ID] == host_id


async def main(
    pg_url: str, schema: str, es: str, tenant: str, host_id: str, lease: str, out: str
) -> None:
    _stamp_as(host_id)
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
    reaper = await DockerDeadHostReaper.for_local_engine()
    host = ExecutorHost(
        host_id=host_id,
        container_id=f"c-{host_id}",
        generation="g1",
        epoch=ORCHESTRATION_EVENT_EPOCH,
        reap_scope=reaper.scope(),
    )
    await ExecutionHost(
        PostgresExecutionRunQueue(pool, lease_ttl=ttl),  # type: ignore[arg-type]  # asyncpg.Pool vs Pool
        host,
        capacity=1,
        drainer=_StallingDrainer(executions, Path(out)),
        reaper=reaper,
        interrupter=AggregateRunInterrupter(executions),
        streams=EventStoreExecutionEventStream(clients[1]),
        timing=HostTiming(
            loop_interval=timedelta(milliseconds=200),
            lease_ttl=ttl,
            turn_budget=ttl / 3 - timedelta(milliseconds=200),
        ),
    ).run_until_drained()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:8]))
