"""Real-Postgres acceptance for start-only admission (#1310 1.3).

A start through the real handler and processor returns with its
`execution_runs` row `admitted` and its start event in the stream. Runs where
the 1.2 run-queue tests run (CI's test stack); this image has no Postgres.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import asyncpg
import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = pytest.mark.integration


@pytest.fixture
async def pool(test_infrastructure: TestInfrastructure) -> AsyncIterator[asyncpg.Pool]:
    schema = f"run_queue_{uuid4().hex}"
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


async def test_a_start_returns_with_its_row_admitted_and_its_start_event_durable(
    pool: asyncpg.Pool,
) -> None:
    executions = RepositoryAdapter(
        EventStoreRepository(
            MemoryEventStoreClient(),
            WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "WorkflowExecution",
        )
    )
    workspace = MagicMock()
    processor = WorkflowExecutionProcessor(
        execution_repository=executions,
        session_repository=AsyncMock(),
        workspace_service=workspace,
        artifact_repository=AsyncMock(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=AsyncMock(return_value="p"),
        command_builder=MagicMock(return_value=["claude"]),
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        run_queue=PostgresExecutionRunQueue(pool),
    )

    result = await processor.run(
        workflow_id="wf-1",
        workflow_name="wf",
        phases=[ExecutablePhase(phase_id="p1", name="P1", order=1, prompt_template="do")],
        inputs={"task": "x"},
        execution_id="exec-pg-admitted",
    )

    assert result.status == "admitted"
    async with pool.acquire() as conn:
        state = await conn.fetchval(
            "SELECT state FROM execution_runs WHERE execution_id=$1", "exec-pg-admitted"
        )
    assert state == "admitted"
    assert await executions.get_by_id("exec-pg-admitted") is not None
    workspace.create_workspace.assert_not_called()


async def test_a_durable_start_reloads_through_a_fresh_event_store_client(
    pool: asyncpg.Pool, test_infrastructure: TestInfrastructure
) -> None:
    """B2 slice: the start survives the process, read back by a client that never wrote it.

    The test above holds the stream in memory, so it cannot show the start is
    durable. This one writes through the production gRPC client and reloads
    through a second one; the start pins - inputs and repositories, including
    one whose SHA is unknown - are what `run_claimed` rebuilds the run from.
    It does NOT drive the dispatch, resume or direct-route entrances.
    """
    from syn_adapters.storage.legacy_tolerant_client import LegacyShapeTolerantGrpcClient
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
        SourceCommit,
    )

    address = f"{test_infrastructure.eventstore_host}:{test_infrastructure.eventstore_port}"
    tenant = f"run-queue-{uuid4().hex}"

    def _executions(client: LegacyShapeTolerantGrpcClient) -> RepositoryAdapter:
        return RepositoryAdapter(
            EventStoreRepository(
                client,
                WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "WorkflowExecution",
            )
        )

    writer = LegacyShapeTolerantGrpcClient(address=address, tenant_id=tenant)
    reader = LegacyShapeTolerantGrpcClient(address=address, tenant_id=tenant)
    await writer.connect()
    await reader.connect()
    execution_id = f"exec-durable-{uuid4().hex[:8]}"
    try:
        processor = WorkflowExecutionProcessor(
            execution_repository=_executions(writer),
            session_repository=AsyncMock(),
            workspace_service=MagicMock(),
            artifact_repository=AsyncMock(),
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=None,
            observability_writer=None,
            controller=None,
            prompt_builder=AsyncMock(return_value="p"),
            command_builder=MagicMock(return_value=["claude"]),
            todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
            run_queue=PostgresExecutionRunQueue(pool),
        )
        result = await processor.run(
            workflow_id="wf-1",
            workflow_name="wf",
            phases=[ExecutablePhase(phase_id="p1", name="P1", order=1, prompt_template="do")],
            inputs={"task": "x"},
            execution_id=execution_id,
            repos=[
                RepositoryRef.from_slug("acme/one"),
                RepositoryRef.from_slug("acme/two"),
            ],
            # What `ExecuteWorkflowHandler` hands the processor: one entry per
            # repository, an unknown SHA kept as None (`source_commits_for`).
            source_commits=[
                SourceCommit(repository="acme/one", sha="a" * 40),
                SourceCommit(repository="acme/two", sha=None),
            ],
        )
        assert result.status == "admitted"

        reloaded = await _executions(reader).get_by_id(execution_id)
        assert reloaded is not None
        pins = reloaded.start_pins
        assert pins.inputs["task"] == "x"
        assert [c.repository for c in pins.source_commits] == ["acme/one", "acme/two"]
        assert [p.phase_id for p in pins.pinned_phases] == ["p1"]
        async with pool.acquire() as conn:
            state = await conn.fetchval(
                "SELECT state FROM execution_runs WHERE execution_id=$1", execution_id
            )
        assert state == "admitted"
    finally:
        await writer.disconnect()
        await reader.disconnect()
