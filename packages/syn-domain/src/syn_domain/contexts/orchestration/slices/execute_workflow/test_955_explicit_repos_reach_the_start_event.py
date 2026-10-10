"""A repository the caller names is used even when the workflow needs none (#955).

`syn workflow run <id> -R owner/repo` against a workflow whose template says
`requires_repos: false` used to start with no repository at all: the handler
skipped repo resolution entirely, so the explicit `-R` was dropped without a
word. `requires_repos` decides whether the template's DEFAULTS apply, never
whether the caller's own choice is honoured.

Driven through the REAL `ExecuteWorkflowHandler` and the REAL
`WorkflowExecutionProcessor` over a real event-store repository, and asserted
on the stored `WorkflowExecutionStarted` event: a repo dropped anywhere
between the command and the store fails here, wherever the hop is.

Provisioning is made to fail on purpose. The start event is written before any
workspace is asked for, so a failing workspace proves the launch without
running an agent.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
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
_SHA = "955955955955955955955955955955955955955a"


@dataclass(frozen=True)
class _Started:
    """What a stored start event says about the run's repositories."""

    source_repositories: list[str]
    """One per repository the run recorded a commit for (#1457)."""
    repos_input: str | None
    """The ``inputs["repos"]`` the prompt builder reads, or None if unset."""


class _Resolver:
    """Names a commit for every repository it is asked about."""

    async def head_sha(self, repo: RepositoryRef) -> str | None:
        del repo
        return _SHA


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
    """A `requires_repos: false` template, a real handler and processor."""

    def __init__(self) -> None:
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
            commit_resolver=_Resolver(),
        )

    async def install(self, *, template_repos: list[str]) -> None:
        template = WorkflowTemplateAggregate()
        command = build_command_from_definition(self.definition).model_copy(
            update={"requires_repos": False, "repos": template_repos}
        )
        template.create_workflow(command)
        assert template.requires_repos is False
        await self.templates.save_new(template)

    async def run(self, execution_id: str, *slugs: str) -> None:
        await self.handler.handle(
            ExecuteWorkflowCommand(
                aggregate_id=self.definition.id,
                execution_id=execution_id,
                repos=[RepositoryRef.from_slug(s) for s in slugs],
                inputs={"task": "fix it"},
            )
        )

    async def started(self, execution_id: str) -> _Started:
        for envelope in await stored_envelopes(self.executions_store):
            event = envelope.event
            data = event.model_dump()
            if (
                event.event_type == "WorkflowExecutionStarted"
                and data["execution_id"] == execution_id
            ):
                return _Started(
                    source_repositories=[c["repository"] for c in data["source_commits"] or []],
                    repos_input=data["inputs"].get("repos"),
                )
        msg = f"no WorkflowExecutionStarted stored for {execution_id}"
        raise AssertionError(msg)


async def test_explicit_repos_are_on_the_start_event_of_a_workflow_that_needs_none() -> None:
    world = _World()
    await world.install(template_repos=[])

    await world.run("exec-explicit", "acme/widgets", "acme/gadgets")

    started = await world.started("exec-explicit")
    assert started.source_repositories == ["acme/widgets", "acme/gadgets"]
    assert started.repos_input == (
        "https://github.com/acme/widgets,https://github.com/acme/gadgets"
    )


async def test_the_templates_own_repos_still_do_not_apply_when_it_needs_none() -> None:
    # The other half of the rule: requires_repos still gates the DEFAULTS.
    # A template that lists a repo but says it needs none, run with no `-R`,
    # starts with no repository - exactly as before #955.
    world = _World()
    await world.install(template_repos=["https://github.com/acme/template-default"])

    await world.run("exec-bare")

    started = await world.started("exec-bare")
    assert started.source_repositories == []
    assert started.repos_input is None
