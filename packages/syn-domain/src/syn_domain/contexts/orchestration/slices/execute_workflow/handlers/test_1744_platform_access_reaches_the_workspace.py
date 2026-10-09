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

from syn_domain.contexts.orchestration import TagSet, WorkflowExecutionAggregate
from syn_domain.contexts.orchestration._shared.eval_choice import EvalSelection, LaunchEval
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalId
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
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
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_workspace import (
    PhaseWorkspace,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
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


async def _eval_the_workspace_was_bound_to(launch_eval: LaunchEval | None) -> object:
    """Provision through ``PhaseWorkspace``, the hop that reads the execution aggregate.

    The eval an EVAL token may write to is the execution's own membership, never
    a value the workspace sends, so it is read here off a real started aggregate.
    """
    phase = (await _executable_phases())["run_and_score"]
    aggregate = WorkflowExecutionAggregate()
    aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
        StartExecutionCommand(
            execution_id="exec-1744",
            workflow_id="eval-runner-1744",
            workflow_name="Eval runner",
            total_phases=2,
            inputs={},
            tags=TagSet(),
            launch_eval=launch_eval,
        )
    )
    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(side_effect=_StopAfterCreate)
    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value = workspace_cm
    workspaces = PhaseWorkspace(
        session_repository=MagicMock(),
        workspace_service=workspace_service,
        artifact_repository=MagicMock(),
        artifact_content_storage=None,
        artifact_query=None,
        observability_writer=None,
        prompt_builder=AsyncMock(),
        command_builder=MagicMock(),
        claude_plugin_materializer=None,
        skill_materializer=None,
        runtime=MagicMock(),
        journal=MagicMock(),
        inputs={},
    )
    todo = TodoItem(
        execution_id="exec-1744", action=TodoAction.PROVISION_WORKSPACE, phase_id=phase.phase_id
    )
    with pytest.raises(_StopAfterCreate):
        await workspaces.provision(
            todo=todo,
            phase=phase,
            aggregate=aggregate,
            session_id="s",
            repo_urls=[],
            completed_phase_ids=[],
            phase_outputs=PhaseOutputCache(),
        )
    return workspace_service.create_workspace.call_args.kwargs["eval_id"]


async def test_the_workspace_is_bound_to_the_eval_its_execution_was_launched_into() -> None:
    launched = LaunchEval(EvalId("ev-1744"), EvalSelection.EXPLICIT)
    assert await _eval_the_workspace_was_bound_to(launched) == "ev-1744"


async def test_an_execution_in_no_eval_binds_its_workspace_to_none() -> None:
    assert await _eval_the_workspace_was_bound_to(None) is None
