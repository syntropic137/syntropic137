"""A phase's ``resources.memory_mb`` reaches the workspace it sizes (okrs-51p.30).

Same five hops as ``platform_access`` (#1744): ``PhaseYamlDefinition``,
``PhaseDefinition``, a serialized ``WorkflowTemplateCreated`` event,
``ExecutablePhase`` and ``WorkspaceProvisionHandler``. Any of them can drop it
while both ends look right, and a dropped request runs the build in the
default and gets it OOM-killed. So the assertion is on the
``create_workspace`` call, built from YAML through the real handlers. What
the adapter does with it is pinned in ``test_workspace_memory_request.py``.

2048 rather than a large value: below the default ceiling, so the start
check passes and only the carrying is measured, and not the default, so a
dropped request cannot satisfy it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.orchestration import WorkspaceResourceRequest
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

pytestmark = pytest.mark.unit

_WORKFLOW_YAML = """
id: build-51p30
name: Build
type: custom
classification: standard
phases:
  - id: build
    name: Build
    order: 1
    prompt_template: "build it"
    resources:
      memory_mb: 2048
  - id: review
    name: Review
    order: 2
    prompt_template: "review it"
"""


class _CapturingProcessor:
    def __init__(self) -> None:
        self.phases: list[ExecutablePhase] = []

    async def run(
        self, *, workflow_id: str, phases: list[ExecutablePhase], execution_id: str, **_: object
    ) -> WorkflowExecutionResult:
        self.phases = list(phases)
        return WorkflowExecutionResult(
            workflow_id=workflow_id,
            execution_id=execution_id,
            status="completed",
            started_at=datetime.now(UTC),
        )


class _WorkflowRepositoryStub:
    def __init__(self, aggregate: WorkflowTemplateAggregate) -> None:
        self._aggregate = aggregate

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        del aggregate_id
        return self._aggregate


async def _executable_phases() -> dict[str, ExecutablePhase]:
    """The phases production would run, after the template's event round trip."""
    command = build_command_from_definition(WorkflowDefinition.from_yaml(_WORKFLOW_YAML))
    origin = WorkflowTemplateAggregate()
    origin.create_workflow(command)
    (envelope,) = origin.get_uncommitted_events()
    created = envelope.event
    rehydrated = WorkflowTemplateAggregate()
    rehydrated.apply_event(type(created).model_validate(created.model_dump(mode="json")))

    processor = _CapturingProcessor()
    handler = ExecuteWorkflowHandler(
        processor=processor,  # type: ignore[arg-type]
        workflow_repository=_WorkflowRepositoryStub(rehydrated),
    )
    await handler.handle(ExecuteWorkflowCommand(aggregate_id="build-51p30"))
    return {p.phase_id: p for p in processor.phases}


class _StopAfterCreate(Exception):
    pass


async def _resources_the_workspace_was_created_with(phase: ExecutablePhase) -> object:
    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(side_effect=_StopAfterCreate)
    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value = workspace_cm
    handler = WorkspaceProvisionHandler(
        workspace_service=workspace_service,
        prompt_builder=AsyncMock(),
        command_builder=MagicMock(),
    )
    todo = TodoItem(
        execution_id="exec-51p30", action=TodoAction.PROVISION_WORKSPACE, phase_id=phase.phase_id
    )
    with pytest.raises(_StopAfterCreate):
        await handler.handle(todo=todo, phase=phase, workflow_id="build-51p30", session_id="s")
    return workspace_service.create_workspace.call_args.kwargs["resources"]


async def test_a_phase_that_requests_memory_gets_it_on_its_workspace() -> None:
    phases = await _executable_phases()
    assert await _resources_the_workspace_was_created_with(
        phases["build"]
    ) == WorkspaceResourceRequest(memory_mb=2048)


async def test_a_phase_that_requests_nothing_asks_for_the_default() -> None:
    phases = await _executable_phases()
    assert (
        await _resources_the_workspace_was_created_with(phases["review"])
        == WorkspaceResourceRequest()
    )
