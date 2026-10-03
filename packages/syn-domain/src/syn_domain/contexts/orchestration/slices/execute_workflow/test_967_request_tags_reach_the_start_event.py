"""A run's tags are written on its WorkflowExecutionStarted event (#967, #955).

Driven through the REAL `ExecuteWorkflowHandler` and the REAL
`WorkflowExecutionProcessor`, each over a real event-store repository; only the
store itself is in memory, and only the workspace (IO) is a double. #955 is
the defect this shape guards against: a field that reaches the handler and is
dropped before the event is written passes every test that stops at a double
of the processor. So the assertion is made on what the store holds.

Provisioning is made to fail on purpose. The start event is written before
any workspace is asked for, so a failing workspace proves the launch snapshot
without running an agent.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient
from pydantic import ValidationError

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.tags import TagSet
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
from syn_domain.contexts.orchestration.domain.commands.AddWorkflowTagsCommand import (
    AddWorkflowTagsCommand,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
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
    """Real repositories over in-memory stores, a real handler and processor."""

    def __init__(self, workflow_tags: list[str]) -> None:
        self.definition = WorkflowDefinition.from_file(_WORKFLOW)
        self.executions_store = MemoryEventStoreClient()
        self.templates = RepositoryAdapter(
            EventStoreRepository(
                MemoryEventStoreClient(),
                WorkflowTemplateAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "WorkflowTemplate",
            )
        )
        executions = RepositoryAdapter(
            EventStoreRepository(
                self.executions_store,
                WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "WorkflowExecution",
            )
        )
        processor = WorkflowExecutionProcessor(
            execution_repository=executions,
            session_repository=AsyncMock(),
            workspace_service=_failing_workspace(),
            artifact_repository=AsyncMock(),
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=None,
            observability_writer=None,
            controller=None,
            prompt_builder=AsyncMock(return_value="test prompt"),
            command_builder=MagicMock(return_value=["claude"]),
            todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        )
        self.handler = ExecuteWorkflowHandler(
            processor=processor,
            workflow_repository=self.templates,
        )
        self._workflow_tags = workflow_tags

    async def install(self) -> None:
        template = WorkflowTemplateAggregate()
        command = build_command_from_definition(self.definition)
        template.create_workflow(command.model_copy(update={"tags": TagSet(self._workflow_tags)}))
        await self.templates.save_new(template)

    async def tag_workflow(self, tags: list[str]) -> None:
        template = await self.templates.get_by_id(self.definition.id)
        assert template is not None
        template.add_tags(
            AddWorkflowTagsCommand(aggregate_id=self.definition.id, tags=TagSet(tags))
        )
        await self.templates.save(template)

    async def run(self, execution_id: str, tags: list[str]) -> None:
        command = ExecuteWorkflowCommand(
            aggregate_id=self.definition.id,
            execution_id=execution_id,
            repos=[RepositoryRef.from_slug("acme/widgets")],
            inputs={"task": "fix it"},
            tags=tags,  # type: ignore[arg-type]  # validated into a TagSet, as the API sends it
        )
        await self.handler.handle(command)

    async def started_tags(self, execution_id: str) -> list[str]:
        for envelope in await stored_envelopes(self.executions_store):
            event = envelope.event
            if event.event_type == "WorkflowExecutionStarted" and (
                event.model_dump()["execution_id"] == execution_id
            ):
                return list(event.model_dump().get("tags", []))
        msg = f"no WorkflowExecutionStarted stored for {execution_id}"
        raise AssertionError(msg)


async def test_request_tags_are_on_the_persisted_start_event_with_the_workflows() -> None:
    world = _World(workflow_tags=["nightly"])
    await world.install()

    await world.run("exec-1", [" Baseline", "smoke", "smoke"])

    assert await world.started_tags("exec-1") == ["baseline", "nightly", "smoke"]


async def test_a_later_workflow_tag_reaches_only_later_runs() -> None:
    world = _World(workflow_tags=["nightly"])
    await world.install()
    await world.run("exec-before", [])

    await world.tag_workflow(["added-later"])
    await world.run("exec-after", [])

    assert await world.started_tags("exec-before") == ["nightly"]
    assert await world.started_tags("exec-after") == ["added-later", "nightly"]


async def test_an_untagged_run_of_an_untagged_workflow_records_none() -> None:
    world = _World(workflow_tags=[])
    await world.install()

    await world.run("exec-1", [])

    assert await world.started_tags("exec-1") == []


def test_an_invalid_request_tag_is_refused_not_dropped() -> None:
    with pytest.raises(ValidationError, match="contains characters outside"):
        ExecuteWorkflowCommand(
            aggregate_id="wf",
            tags=["ok", "Not OK!"],  # type: ignore[arg-type]
        )
