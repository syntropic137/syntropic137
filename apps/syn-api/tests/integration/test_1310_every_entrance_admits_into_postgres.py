"""B2: every start entrance admits into the REAL run queue and event store (#1310 1.3).

`test_1310_admission_into_postgres_run_queue.py` calls the processor directly;
this drives the three ways a start actually arrives, with the flag ON, over a
real Postgres run queue and the real gRPC event store, and reads every answer
back through a client that never wrote it:

* dispatch - `BackgroundWorkflowDispatcher.run_workflow` (a trigger),
* resume - `BackgroundWorkflowDispatcher.start_resume`,
* direct route - `POST /workflows/{id}/execute`.

Each must return with the run's `execution_runs` row `admitted`, its start
event durable, nothing provisioned and no task left carrying it (V11). V5 is
then proved on the same infrastructure: an ON start, claimed from Postgres and
drained by a FRESH processor over a FRESH client, writes the event sequence
today's single-call run writes.

Only the workspace is a double, and it fails setup, which gives a scripted,
deterministic run. The to-do store is shared in memory, as in the unit V5:
the run-scoped fold that replaces it is #1310 1.4.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import asyncpg
import pytest
from event_sourcing import EventStoreRepository
from fastapi import BackgroundTasks

from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.legacy_tolerant_client import LegacyShapeTolerantGrpcClient
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_api import _wiring
from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_api.routes.executions import commands
from syn_api.routes.executions.commands import ExecuteWorkflowRequest
from syn_domain.contexts._shared import AdmissionGate
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration import ORCHESTRATION_EVENT_EPOCH
from syn_domain.contexts.orchestration._shared.eval_choice import EvalSelection, LaunchEval
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ResumeExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.ports import ExecutorHost
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.start_resume import StartResumeHandler
from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = pytest.mark.integration

_WORKFLOW = (
    Path(__file__).resolve().parents[4] / "workflows" / "sdlc" / "quickfix" / "workflow.yaml"
)
_REPO = RepositoryRef.from_slug("acme/widgets")
_HOST = ExecutorHost(
    host_id="host-b2", container_id="c-b2", generation="g1", epoch=ORCHESTRATION_EVENT_EPOCH
)


def _failing_workspace() -> MagicMock:
    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value.__aenter__.return_value.run_setup_phase = (
        AsyncMock(
            return_value=ExecutionResult(
                exit_code=1, success=False, duration_ms=0.0, stderr="setup failed"
            )
        )
    )
    return workspace_service


class _Infra:
    """Real Postgres + real event store; every processor gets its OWN client."""

    def __init__(self, address: str, pool: asyncpg.Pool) -> None:
        self.address = address
        self.tenant = f"b2-{uuid4().hex}"
        self.pool = pool
        self.queue = PostgresExecutionRunQueue(pool)
        self.todos = InMemoryProjectionStore()
        self.workspace = _failing_workspace()
        self.definition = WorkflowDefinition.from_file(_WORKFLOW)
        self._clients: list[LegacyShapeTolerantGrpcClient] = []

    async def client(self) -> LegacyShapeTolerantGrpcClient:
        client = LegacyShapeTolerantGrpcClient(address=self.address, tenant_id=self.tenant)
        await client.connect()
        self._clients.append(client)
        return client

    async def close(self) -> None:
        for client in self._clients:
            await client.disconnect()

    async def executions(self) -> RepositoryAdapter:
        return RepositoryAdapter(
            EventStoreRepository(
                await self.client(),
                WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "WorkflowExecution",
            )
        )

    async def templates(self) -> RepositoryAdapter:
        return RepositoryAdapter(
            EventStoreRepository(
                await self.client(),
                WorkflowTemplateAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "WorkflowTemplate",
            )
        )

    async def install(self) -> None:
        template = WorkflowTemplateAggregate()
        template.create_workflow(build_command_from_definition(self.definition))
        await (await self.templates()).save_new(template)

    async def processor(self, *, queued: bool) -> WorkflowExecutionProcessor:
        """A fresh processor over a fresh client: nothing in it survives from any other."""
        return WorkflowExecutionProcessor(
            execution_repository=await self.executions(),
            session_repository=AsyncMock(),
            workspace_service=self.workspace,
            artifact_repository=AsyncMock(),
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=None,
            observability_writer=None,
            controller=None,
            prompt_builder=AsyncMock(return_value="test prompt"),
            command_builder=MagicMock(return_value=["claude"]),
            todo_projection=ExecutionTodoProjection(store=self.todos),
            run_queue=self.queue if queued else None,
        )

    async def handler(self, *, queued: bool) -> ExecuteWorkflowHandler:
        return ExecuteWorkflowHandler(
            processor=await self.processor(queued=queued),
            workflow_repository=await self.templates(),
        )

    async def event_types(self, execution_id: str) -> list[str]:
        """Read back by a client that wrote none of it."""
        reader = await self.client()
        envelopes = await reader.read_events(f"WorkflowExecution-{execution_id}")
        return [e.metadata.event_type or e.event.event_type for e in envelopes]

    async def row_state(self, execution_id: str) -> str | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT state FROM execution_runs WHERE execution_id=$1", execution_id
            )

    async def assert_admitted(self, execution_id: str) -> None:
        assert await self.row_state(execution_id) == "admitted"
        assert await self.event_types(execution_id) == ["WorkflowExecutionStarted"]


@pytest.fixture
async def pool(test_infrastructure: TestInfrastructure) -> AsyncIterator[asyncpg.Pool]:
    schema = f"run_queue_b2_{uuid4().hex}"
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


@pytest.fixture
async def infra(
    pool: asyncpg.Pool, test_infrastructure: TestInfrastructure
) -> AsyncIterator[_Infra]:
    world = _Infra(
        f"{test_infrastructure.eventstore_host}:{test_infrastructure.eventstore_port}", pool
    )
    await world.install()
    try:
        yield world
    finally:
        await world.close()


@pytest.fixture
def run_queue_flag(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SYN_EXECUTION_RUN_QUEUE_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    monkeypatch.delenv("SYN_EXECUTION_RUN_QUEUE_ENABLED")
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _no_failure(failures: list[Exception]):
    async def record(exc: Exception) -> None:
        failures.append(exc)

    return record


async def test_dispatch_admits_with_the_row_admitted_and_the_start_durable(
    infra: _Infra,
) -> None:
    dispatcher = BackgroundWorkflowDispatcher(
        await infra.handler(queued=True),
        maintenance=AdmissionGate(InMemoryMaintenanceAdapter()),
        admits_to_run_queue=True,
    )
    failures: list[Exception] = []
    execution_id = f"exec-{uuid4().hex[:12]}"
    tasks_before = asyncio.all_tasks()

    await dispatcher.run_workflow(
        infra.definition.id,
        {"task": "fix it"},
        execution_id=execution_id,
        repos=[_REPO],
        on_held=_no_failure(failures),
    )

    assert failures == []
    assert asyncio.all_tasks() == tasks_before
    await infra.assert_admitted(execution_id)
    infra.workspace.create_workspace.assert_not_called()


async def test_resume_admits_with_the_row_admitted_and_the_start_durable(
    infra: _Infra,
) -> None:
    parent_id = f"exec-{uuid4().hex[:12]}"
    child_id = f"exec-{uuid4().hex[:12]}"
    # Today's path, to a failed parent the operator then resumes.
    parent_result = await (await infra.handler(queued=False)).handle(
        ExecuteWorkflowCommand(
            aggregate_id=infra.definition.id,
            execution_id=parent_id,
            repos=[_REPO],
            inputs={"task": "fix it"},
        )
    )
    assert parent_result.status == "failed"
    executions = await infra.executions()
    parent = await executions.get_by_id(parent_id)
    assert parent is not None
    parent.resume_execution(
        ResumeExecutionCommand(
            execution_id=parent_id, resume_execution_id=child_id, acknowledge_external_effects=True
        )
    )
    await executions.save(parent)
    infra.workspace.create_workspace.reset_mock()

    resume_handler = StartResumeHandler(
        await infra.processor(queued=True), await infra.executions()
    )
    dispatcher = BackgroundWorkflowDispatcher(
        await infra.handler(queued=True),
        maintenance=AdmissionGate(InMemoryMaintenanceAdapter()),
        resume_handler=resume_handler,
        admits_to_run_queue=True,
    )
    failures: list[Exception] = []
    tasks_before = asyncio.all_tasks()

    await dispatcher.start_resume(parent_id, on_failure=_no_failure(failures))

    assert failures == []
    assert asyncio.all_tasks() == tasks_before
    await infra.assert_admitted(child_id)
    async with infra.pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT is_resume FROM execution_runs WHERE execution_id=$1", child_id
        )
    infra.workspace.create_workspace.assert_not_called()


@pytest.mark.usefixtures("run_queue_flag")
async def test_direct_route_admits_before_its_200(
    infra: _Infra, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`POST /execute`, past validation: the real route, gate, handler and stores."""
    import syn_api._wiring_admission as wiring_admission

    handler = await infra.handler(queued=True)
    template = await (await infra.templates()).get_by_id(infra.definition.id)

    async def validated(
        _workflow_id: str, request: ExecuteWorkflowRequest
    ) -> tuple[object, dict[str, str], list[RepositoryRef]]:
        return template, dict(request.inputs), [_REPO]

    async def nothing(*_args: object, **_kwargs: object) -> None:
        return None

    async def ordinary(*_args: object, **_kwargs: object) -> LaunchEval:
        return LaunchEval(None, EvalSelection.NONE)

    async def the_handler() -> ExecuteWorkflowHandler:
        return handler

    projections = MagicMock()
    projections.workflow_detail.get_by_id = AsyncMock(return_value=None)
    monkeypatch.setattr(
        wiring_admission,
        "_admission_gate_singleton",
        AdmissionGate(InMemoryMaintenanceAdapter()),
        raising=False,
    )
    monkeypatch.setattr(commands, "_validate_execution_request", validated)
    monkeypatch.setattr(commands, "_launch_eval", ordinary)
    monkeypatch.setattr(commands, "record_execution_request", nothing)
    monkeypatch.setattr(commands, "ensure_connected", nothing)
    monkeypatch.setattr(commands, "get_projection_mgr", lambda: projections)
    monkeypatch.setattr(_wiring, "get_execute_workflow_handler", the_handler)
    tasks = BackgroundTasks()

    response = await commands.execute_workflow_endpoint(
        infra.definition.id,
        ExecuteWorkflowRequest(inputs={"task": "fix it"}),
        tasks,
    )

    assert response.status == "started"
    assert tasks.tasks == [], "ON must not queue a background task (V11)"
    await infra.assert_admitted(response.execution_id)
    infra.workspace.create_workspace.assert_not_called()


async def test_v5_claimed_from_postgres_and_drained_fresh_matches_todays_run(
    infra: _Infra,
) -> None:
    golden_id = f"exec-{uuid4().hex[:12]}"
    claimed_id = f"exec-{uuid4().hex[:12]}"

    def command(execution_id: str) -> ExecuteWorkflowCommand:
        return ExecuteWorkflowCommand(
            aggregate_id=infra.definition.id,
            execution_id=execution_id,
            repos=[_REPO],
            inputs={"task": "fix it"},
        )

    await (await infra.handler(queued=False)).handle(command(golden_id))
    golden = await infra.event_types(golden_id)

    admitted = await (await infra.handler(queued=True)).handle(command(claimed_id))
    assert admitted.status == "admitted"
    await infra.queue.register(_HOST, capacity=1)
    await infra.queue.heartbeat(_HOST.host_id)
    claimed = await infra.queue.claim(_HOST.host_id)
    assert claimed is not None
    assert claimed.execution_id == claimed_id
    result = await (await infra.processor(queued=True)).run_claimed(claimed)

    assert len(golden) > 2, golden
    assert await infra.event_types(claimed_id) == golden
    assert result.status == "failed"
