"""A phase's ``platform_access`` declaration reaches the workspace it describes (#1744).

The value starts in workflow YAML and is only useful at
``WorkspaceService.create_workspace``, which mints the phase's platform token
with it. Between the two it crosses ``PhaseYamlDefinition``,
``PhaseDefinition``, a serialized ``WorkflowTemplateCreated`` event,
``ExecutablePhase`` and ``WorkspaceProvisionHandler``: five hops, any of which
can drop it while both ends still look right. So the assertion is on the
``create_workspace`` call, built from YAML through the real handlers. What the
adapter does with the value is pinned beside it, in
``test_pc127_platform_grant_lifecycle.py``.

Dropping it at any hop falls back to READ - less access than declared, never
more - so the EVAL phase is the one that proves the path, and the undeclared
phase beside it is the control that the default did not move.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

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
from syn_shared.platform_access import PlatformScope

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

pytestmark = pytest.mark.unit

_WORKFLOW_YAML = """
id: eval-runner-1744
name: Eval runner
type: custom
classification: standard
phases:
  - id: run_and_score
    name: Run and score
    order: 1
    prompt_template: "launch the eval runs, then score them"
    platform_access: eval
  - id: summarize
    name: Summarize
    order: 2
    prompt_template: "summarize"
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
    # Through JSON: the shape the event store persists and rehydration reads.
    rehydrated = WorkflowTemplateAggregate()
    rehydrated.apply_event(type(created).model_validate(created.model_dump(mode="json")))

    processor = _CapturingProcessor()
    handler = ExecuteWorkflowHandler(
        processor=processor,  # type: ignore[arg-type]
        workflow_repository=_WorkflowRepositoryStub(rehydrated),
    )
    await handler.handle(ExecuteWorkflowCommand(aggregate_id="eval-runner-1744"))
    return {p.phase_id: p for p in processor.phases}


class _StopAfterCreate(Exception):
    pass


async def _scope_the_workspace_was_created_with(phase: ExecutablePhase) -> object:
    """Run the real provision handler up to the workspace, and read what it asked for."""
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
        execution_id="exec-1744", action=TodoAction.PROVISION_WORKSPACE, phase_id=phase.phase_id
    )
    with pytest.raises(_StopAfterCreate):
        await handler.handle(todo=todo, phase=phase, workflow_id="eval-runner-1744", session_id="s")
    return workspace_service.create_workspace.call_args.kwargs["platform_access"]


async def test_a_phase_that_declares_eval_gets_an_eval_workspace() -> None:
    phases = await _executable_phases()
    assert (
        await _scope_the_workspace_was_created_with(phases["run_and_score"]) is PlatformScope.EVAL
    )


async def test_a_phase_that_declares_nothing_stays_read_only() -> None:
    phases = await _executable_phases()
    assert await _scope_the_workspace_was_created_with(phases["summarize"]) is PlatformScope.READ


def test_an_unknown_scope_is_refused_at_install() -> None:
    with pytest.raises(ValueError, match="platform_access"):
        WorkflowDefinition.from_yaml(
            _WORKFLOW_YAML.replace("platform_access: eval", "platform_access: admin")
        )
