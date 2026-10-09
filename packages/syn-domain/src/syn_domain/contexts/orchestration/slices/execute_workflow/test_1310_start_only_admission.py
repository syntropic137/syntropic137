"""Start-only admission, and the drain from a claim (#1310 1.3, ADR-072 V5).

Driven through the REAL `ExecuteWorkflowHandler` and `WorkflowExecutionProcessor`
over real event-store repositories; only the stores are in memory and only the
workspace is a double. Provisioning fails on purpose, which gives a scripted,
deterministic run: start, provision attempt, failure, terminal events.

V5 is the claim that matters: a run admitted by one processor and drained by a
FRESH one - sharing nothing but the durable stores - writes the same events as
today's single-call run. A field the drain needs that only lived in `run()`'s
arguments would make the two sequences differ here.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration import ORCHESTRATION_EVENT_EPOCH, DuplicateExecutionError
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
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
from syn_domain.testing.stored_replay import stored_envelopes

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_WORKFLOW = (
    Path(__file__).resolve().parents[8] / "workflows" / "sdlc" / "quickfix" / "workflow.yaml"
)
_HOST = ExecutorHost(
    host_id="host-1", container_id="c-1", generation="g1", epoch=ORCHESTRATION_EVENT_EPOCH
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


class _World:
    """Durable stores shared by every processor built over them."""

    def __init__(self) -> None:
        self.definition = WorkflowDefinition.from_file(_WORKFLOW)
        self.store = MemoryEventStoreClient()
        self.todos = InMemoryProjectionStore()
        self.queue = InMemoryExecutionRunQueue()
        self.workspace = _failing_workspace()
        self.templates = RepositoryAdapter(
            EventStoreRepository(
                MemoryEventStoreClient(),
                WorkflowTemplateAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "WorkflowTemplate",
            )
        )

    async def install(self) -> None:
        template = WorkflowTemplateAggregate()
        template.create_workflow(build_command_from_definition(self.definition))
        await self.templates.save_new(template)

    def processor(self, *, queued: bool) -> WorkflowExecutionProcessor:
        """A fresh processor: nothing in it survives from any other."""
        return WorkflowExecutionProcessor(
            execution_repository=RepositoryAdapter(
                EventStoreRepository(
                    self.store,
                    WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                    "WorkflowExecution",
                )
            ),
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

    async def handle(self, processor: WorkflowExecutionProcessor, execution_id: str) -> str:
        handler = ExecuteWorkflowHandler(processor=processor, workflow_repository=self.templates)
        result = await handler.handle(
            ExecuteWorkflowCommand(
                aggregate_id=self.definition.id,
                execution_id=execution_id,
                repos=[RepositoryRef.from_slug("acme/widgets")],
                inputs={"task": "fix it"},
            )
        )
        return result.status

    async def event_types(self, execution_id: str) -> list[str]:
        return [
            e.event.event_type
            for e in await stored_envelopes(self.store)
            if e.metadata.aggregate_id == execution_id
        ]


async def test_a_queued_start_returns_admitted_with_the_start_durable_and_nothing_run() -> None:
    world = _World()
    await world.install()

    status = await world.handle(world.processor(queued=True), "exec-admitted")

    assert status == "admitted"
    assert await world.event_types("exec-admitted") == ["WorkflowExecutionStarted"]
    assert (await world.queue.in_use()).admitted == 1
    world.workspace.create_workspace.assert_not_called()


async def test_a_second_start_of_an_admitted_execution_is_a_duplicate() -> None:
    world = _World()
    await world.install()
    await world.handle(world.processor(queued=True), "exec-twice")

    with pytest.raises(DuplicateExecutionError):
        await world.handle(world.processor(queued=True), "exec-twice")

    assert await world.event_types("exec-twice") == ["WorkflowExecutionStarted"]


async def test_v5_start_then_run_claimed_in_a_fresh_processor_matches_todays_run() -> None:
    world = _World()
    await world.install()
    await world.handle(world.processor(queued=False), "exec-golden")
    golden = await world.event_types("exec-golden")

    await world.handle(world.processor(queued=True), "exec-claimed")
    await world.queue.register(_HOST, capacity=1)
    await world.queue.heartbeat(_HOST.host_id)
    claimed = await world.queue.claim(_HOST.host_id)
    assert claimed is not None
    assert claimed.execution_id == "exec-claimed"
    result = await world.processor(queued=True).run_claimed(claimed)

    assert len(golden) > 2, golden
    assert await world.event_types("exec-claimed") == golden
    assert result.status == "failed"
    world.workspace.create_workspace.assert_called()
