"""A claimed three-phase run drains to success on real stores (#1310 1.4, ADR-072 V5 + V10).

`test_1310_every_entrance_admits_into_postgres.py` proves the claimed drain
reads its own fold, but on a run that fails at provisioning. That leaves every
journal hop inside a SUCCESSFUL phase unexercised: `start_phase`, the agent's
completion, `collect` and `complete_phase`. A hop that saved through the shared
journal instead of the run's own would not advance the run's fold, and nothing
there would notice.

This drives a three-phase run all the way to `WorkflowCompleted` with the flag
ON: admitted into a real Postgres run queue, claimed from it, drained by a
FRESH processor over a FRESH gRPC client against the real event store. Only the
agent (`FakeAgentExecutionHandler`) and the workspace backend (memory) are
doubles; no model is called.

V10 is folded in: the shared `execution_todo` projection is rebuilt, the way a
`VERSION` bump rebuilds it (`clear_all_data`, then a replay that has not caught
up), once mid-phase and once between phases. A drain that still read the shared
list would find it empty and "complete" with phases unrun, so the assertions
are on the event stream, not the status: every pinned phase is started and
completed in order, and the run ends `WorkflowCompleted` with
`completed_phases == total_phases`. V5: the claimed run's event sequence equals
today's single-call run of the same workflow.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

import asyncpg
import pytest
from event_sourcing import EventStoreRepository

from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.legacy_tolerant_client import LegacyShapeTolerantGrpcClient
from syn_adapters.storage.repositories import EventStoreExecutionEventStream, RepositoryAdapter
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.agent_sessions import AgentSessionAggregate
from syn_domain.contexts.artifacts import ArtifactAggregate
from syn_domain.contexts.orchestration import ORCHESTRATION_EVENT_EPOCH
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.ports import ExecutorHost
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from event_sourcing import DomainEvent
    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = pytest.mark.integration

_HOST = ExecutorHost(
    host_id="host-1-4",
    container_id="c-1-4",
    generation="g1",
    epoch=ORCHESTRATION_EVENT_EPOCH,
    reap_scope="engine-1",
)
_WORKFLOW_ID = "wf-1310-three-phase"
_PHASE_IDS = ("phase-1", "phase-2", "phase-3")
#: Far above the ~1s this drain takes; only a drain that loops forever reaches it.
_DRAIN_BUDGET_SECONDS = 60
#: What one successful phase writes to the execution stream, in order.
_PHASE_STEPS = (
    "PhaseStarted",
    "WorkspaceProvisionedForPhase",
    "AgentExecutionCompleted",
    "ArtifactsCollectedForPhase",
    "PhaseCompleted",
)


def _three_phases() -> list[ExecutablePhase]:
    """Three sequential phases that declare no output, so the agent's deliverable suffices."""
    return [
        ExecutablePhase(
            phase_id=phase_id,
            name=f"Phase {order}",
            order=order,
            description=f"phase {order} of 3",
            agent_config=AgentConfiguration(),
            prompt_template="do the thing",
            output_artifact_types=(),
            timeout_seconds=1800,
        )
        for order, phase_id in enumerate(_PHASE_IDS, start=1)
    ]


async def _prompt(*_args: object, **_kwargs: object) -> str:
    return "three-phase prompt"


def _command(*_args: object, **_kwargs: object) -> list[str]:
    return ["echo", "agent"]


def _phase_of(event: DomainEvent) -> str | None:
    phase_id = getattr(event, "phase_id", None)
    return phase_id if isinstance(phase_id, str) else None


class _SharedListRebuiltDuringTheRun:
    """The execution repository, rebuilding the SHARED to-do list at two points (V10).

    A `VERSION` bump makes the coordinator `clear_all_data` and replay; until
    the replay catches up, the shared list holds nothing for this run. That is
    simulated right after the run's own durable writes of:

    * `PhaseStarted` of phase 2 - mid-phase, before its agent runs;
    * `PhaseCompleted` of phase 1 - between phases.

    Only the watched execution triggers it, so the golden run is untouched.
    """

    def __init__(
        self, inner: RepositoryAdapter, shared: InMemoryProjectionStore, execution_id: str
    ) -> None:
        self._inner = inner
        self._shared = ExecutionTodoProjection(store=shared)  # type: ignore[arg-type]
        self._execution_id = execution_id
        self.rebuilds: list[tuple[str, str]] = []

    async def _rebuild_if_due(self, events: list[DomainEvent]) -> None:
        for event in events:
            point = (event.event_type, _phase_of(event) or "")
            if point in {("PhaseCompleted", "phase-1"), ("PhaseStarted", "phase-2")}:
                await self._shared.clear_all_data()
                self.rebuilds.append(point)

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        pending = list(aggregate.get_uncommitted_events())
        await self._inner.save(aggregate)
        if aggregate.id == self._execution_id:
            await self._rebuild_if_due([e.event for e in pending])

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        await self._inner.save_new(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        return await self._inner.get_by_id(aggregate_id)


class _Infra:
    """Real Postgres + real event store; every processor gets its OWN client."""

    def __init__(self, address: str, pool: asyncpg.Pool) -> None:
        self.address = address
        self.tenant = f"b2-1-4-{uuid4().hex}"
        self.queue = PostgresExecutionRunQueue(pool)
        self.shared_todos = InMemoryProjectionStore()
        self.workspace = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
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

    async def processor(
        self,
        agent: FakeAgentExecutionHandler,
        *,
        queued: bool,
        rebuild_for: str | None = None,
    ) -> tuple[WorkflowExecutionProcessor, _SharedListRebuiltDuringTheRun | None]:
        """A fresh processor over fresh clients: nothing in it survives from any other."""
        executions = await self.executions()
        watched = (
            None
            if rebuild_for is None
            else _SharedListRebuiltDuringTheRun(executions, self.shared_todos, rebuild_for)
        )
        processor = WorkflowExecutionProcessor(
            execution_repository=watched or executions,
            session_repository=RepositoryAdapter(
                EventStoreRepository(
                    await self.client(),
                    AgentSessionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                    "AgentSession",
                )
            ),
            workspace_service=self.workspace,
            artifact_repository=RepositoryAdapter(
                EventStoreRepository(
                    await self.client(),
                    ArtifactAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                    "Artifact",
                )
            ),
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=None,
            observability_writer=None,
            controller=None,
            prompt_builder=_prompt,
            command_builder=MagicMock(side_effect=_command),
            todo_projection=ExecutionTodoProjection(store=self.shared_todos),  # type: ignore[arg-type]
            agent_handler=agent,
            run_queue=self.queue if queued else None,
            execution_events=EventStoreExecutionEventStream(await self.client()),
            todo_projection_type=ExecutionTodoProjection,
        )
        return processor, watched

    async def events(self, execution_id: str) -> list[DomainEvent]:
        """Read back by a client that wrote none of it."""
        reader = await self.client()
        return [e.event for e in await reader.read_events(f"WorkflowExecution-{execution_id}")]

    async def event_types(self, execution_id: str) -> list[str]:
        return [e.event_type for e in await self.events(execution_id)]


@pytest.fixture
async def pool(test_infrastructure: TestInfrastructure) -> AsyncIterator[asyncpg.Pool]:
    schema = f"run_queue_1_4_{uuid4().hex}"
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
    try:
        yield world
    finally:
        await world.close()


async def _start(processor: WorkflowExecutionProcessor, execution_id: str) -> str:
    result = await processor.run(
        workflow_id=_WORKFLOW_ID,
        workflow_name="Three phases",
        phases=_three_phases(),
        inputs={"task": "fix it"},
        execution_id=execution_id,
    )
    return result.status


async def test_1_4_a_claimed_three_phase_run_succeeds_through_two_shared_list_rebuilds(
    infra: _Infra,
) -> None:
    golden_id = f"exec-{uuid4().hex[:12]}"
    claimed_id = f"exec-{uuid4().hex[:12]}"

    # Today's single-call run: the reference sequence.
    golden_agent = FakeAgentExecutionHandler.success(produces=A_DELIVERABLE)
    golden_processor, _ = await infra.processor(golden_agent, queued=False)
    assert await _start(golden_processor, golden_id) == "completed"
    golden = await infra.event_types(golden_id)

    # Flag ON: admit, claim from Postgres, drain in a FRESH processor.
    admitting, _ = await infra.processor(
        FakeAgentExecutionHandler.success(produces=A_DELIVERABLE), queued=True
    )
    assert await _start(admitting, claimed_id) == "admitted"
    assert await infra.event_types(claimed_id) == ["WorkflowExecutionStarted"]
    await infra.queue.register(_HOST, capacity=1)
    await infra.queue.heartbeat(_HOST.host_id)
    claimed = await infra.queue.claim(_HOST.host_id)
    assert claimed is not None
    assert claimed.execution_id == claimed_id

    agent = FakeAgentExecutionHandler.success(produces=A_DELIVERABLE)
    claiming, watched = await infra.processor(agent, queued=True, rebuild_for=claimed_id)
    # Bounded: a fold that never advances re-serves the same to-do forever,
    # and that must fail here rather than hang the suite.
    result = await asyncio.wait_for(claiming.run_claimed(claimed), timeout=_DRAIN_BUDGET_SECONDS)

    # V10, read off the stream: each pinned phase ran once, in order, to completion.
    events = await infra.events(claimed_id)
    lifecycle = [(e.event_type, _phase_of(e)) for e in events if e.event_type in _PHASE_STEPS]
    assert lifecycle == [(step, phase_id) for phase_id in _PHASE_IDS for step in _PHASE_STEPS], (
        lifecycle
    )
    assert [t.phase_id for t in agent.calls] == list(_PHASE_IDS)
    # ...and it ran through both rebuilds, mid-phase and between phases.
    assert watched is not None
    assert watched.rebuilds == [("PhaseCompleted", "phase-1"), ("PhaseStarted", "phase-2")]
    terminal = events[-1]
    assert terminal.event_type == "WorkflowCompleted", [e.event_type for e in events]
    assert getattr(terminal, "completed_phases", None) == len(_PHASE_IDS)
    assert getattr(terminal, "total_phases", None) == len(_PHASE_IDS)
    artifact_ids = getattr(terminal, "artifact_ids", None)
    assert isinstance(artifact_ids, list)
    assert len(set(artifact_ids)) == len(_PHASE_IDS), artifact_ids
    assert result.status == "completed"

    # V5: the claimed run wrote exactly what today's run writes.
    assert golden[-1] == "WorkflowCompleted", golden
    assert [e.event_type for e in events] == golden
