"""B3: the fourth entrance, an ExecutionRequest re-offered, admits into the REAL stores (#1310 1.3).

`POST /execute` writes an `ExecutionRequested` record before its 200 (#1557).
When the process that queued the fast path dies, the request ProcessManager
re-offers that record to `BackgroundWorkflowDispatcher.start_requested`. With
the run queue ON, that start must end exactly like the other three entrances
in `test_1310_every_entrance_admits_into_postgres.py`: one durable start, one
`execution_runs` row `admitted`, nothing provisioned and no task carrying it.

The record is written by the production writer, and read back by a dispatcher
over a client that never wrote it - the shape a restart has. Re-offering it
again changes nothing, and a withdrawn record starts nothing at all.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from event_sourcing import EventStoreRepository

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_adapters.storage import repositories
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_api.routes.executions.direct_start import (
    record_execution_request,
    withdraw_execution_request,
)
from syn_domain.contexts._shared import AdmissionGate
from syn_domain.contexts.orchestration import ExecutionRequestAggregate, RequestExecutionCommand
from syn_domain.contexts.orchestration._shared.eval_choice import EvalSelection, LaunchEval

from . import test_1310_every_entrance_admits_into_postgres as entrance
from .test_1310_every_entrance_admits_into_postgres import _REPO, _Infra, _no_failure

pytestmark = pytest.mark.integration

# The same real Postgres run queue and gRPC event store as the other entrances.
pool = entrance.pool
infra = entrance.infra


async def _requests(infra: _Infra) -> RepositoryAdapter[ExecutionRequestAggregate]:
    """The ExecutionRequest repository, over a client of its own."""
    return RepositoryAdapter(
        EventStoreRepository(
            await infra.client(),
            ExecutionRequestAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "ExecutionRequest",
        )
    )


async def _record(infra: _Infra, monkeypatch: pytest.MonkeyPatch, execution_id: str) -> None:
    """Write the request through the route's own writer, then lose the fast path."""
    writer = await _requests(infra)
    monkeypatch.setattr(repositories, "get_execution_request_repository", lambda: writer)
    async with AdmissionGate(InMemoryMaintenanceAdapter()).admitting() as ticket:
        await record_execution_request(
            RequestExecutionCommand(
                execution_id=execution_id,
                workflow_id=infra.definition.id,
                inputs={"task": "fix it"},
                repos=[_REPO],
                launch_eval=LaunchEval(None, EvalSelection.NONE),
            ),
            ticket,
        )
        # The process that would have started it dies here.
        ticket.abort()


async def _dispatcher(infra: _Infra) -> BackgroundWorkflowDispatcher:
    """A fresh dispatcher, as after a restart: nothing shared but the stores."""
    return BackgroundWorkflowDispatcher(
        await infra.handler(queued=True),
        maintenance=AdmissionGate(InMemoryMaintenanceAdapter()),
        requests=await _requests(infra),
        admits_to_run_queue=True,
    )


async def _rows(infra: _Infra, execution_id: str) -> int:
    async with infra.pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM execution_runs WHERE execution_id=$1", execution_id
        )


async def test_a_reoffered_request_admits_once_however_often_it_is_offered(
    infra: _Infra, monkeypatch: pytest.MonkeyPatch
) -> None:
    execution_id = f"exec-{uuid4().hex[:12]}"
    await _record(infra, monkeypatch, execution_id)
    failures: list[Exception] = []
    tasks_before = asyncio.all_tasks()

    await (await _dispatcher(infra)).start_requested(execution_id, on_failure=_no_failure(failures))

    assert failures == []
    assert asyncio.all_tasks() == tasks_before
    await infra.assert_admitted(execution_id)
    assert await _rows(infra, execution_id) == 1
    infra.workspace.create_workspace.assert_not_called()

    # Re-offered after another restart: still one start and one admitted row.
    await (await _dispatcher(infra)).start_requested(execution_id, on_failure=_no_failure(failures))

    assert asyncio.all_tasks() == tasks_before
    await infra.assert_admitted(execution_id)
    assert await _rows(infra, execution_id) == 1
    infra.workspace.create_workspace.assert_not_called()


async def test_a_withdrawn_request_reoffered_starts_nothing(
    infra: _Infra, monkeypatch: pytest.MonkeyPatch
) -> None:
    execution_id = f"exec-{uuid4().hex[:12]}"
    await _record(infra, monkeypatch, execution_id)
    assert await withdraw_execution_request(execution_id, "changed my mind")
    failures: list[Exception] = []

    ticket = await (await _dispatcher(infra)).start_requested(
        execution_id, on_failure=_no_failure(failures)
    )

    assert ticket is None
    assert failures == []
    assert await _rows(infra, execution_id) == 0
    assert await (await infra.executions()).get_by_id(execution_id) is None
    infra.workspace.create_workspace.assert_not_called()
