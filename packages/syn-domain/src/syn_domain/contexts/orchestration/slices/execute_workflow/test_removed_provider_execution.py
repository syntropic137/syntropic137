"""A stored ``claude-interactive`` template must be REJECTED, never remapped.

ADR-068 removed the interactive-tmux path and made the YAML parser reject
``agent.provider: claude-interactive`` rather than silently remapping it to
headless Claude: the workflow was authored against an interactive REPL, so
running it headless would change what the phase does while still reporting
success.

YAML is not the only entry point. A template stored BEFORE the removal is
rehydrated straight from its historical ``WorkflowTemplateCreated`` event and
never passes the YAML validator. These tests pin both halves of the contract:

1. rehydration still SUCCEEDS (operators must be able to read and fix an old
   template);
2. execution of that rehydrated template fails at the execution boundary,
   before any workspace is provisioned and before any agent command is built.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
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
from syn_shared.agents import (
    REMOVED_INTERACTIVE_PROVIDER,
    AgentProvider,
    UnsupportedAgentProviderError,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent


WORKFLOW_ID = "wf-legacy-interactive"


class _HistoricalPhase(TypedDict):
    """A phase dict exactly as it was recorded before the removal."""

    phase_id: str
    name: str
    order: int
    prompt_template: str
    provider: str
    agent_id: str
    """The tmux pane selector. Gone from ``PhaseDefinition``; still in history."""


class _HistoricalTemplate(TypedDict):
    """The ``WorkflowTemplateCreated`` payload as it sits in the event store."""

    workflow_id: str
    name: str
    workflow_type: str
    classification: str
    repository_url: str
    repository_ref: str
    requires_repos: bool
    phases: list[_HistoricalPhase]


class _HistoricalEvent:
    """A ``WorkflowTemplateCreated`` as the event store replays it.

    The gRPC store hands the aggregate a generic, dict-backed event, which is
    why a phase dict recorded before the removal still carries the fields the
    current ``PhaseDefinition`` no longer declares.
    """

    def __init__(self, data: _HistoricalTemplate) -> None:
        self._data = data

    def model_dump(self) -> _HistoricalTemplate:
        return self._data.copy()


def _historical_created_event(provider: str = REMOVED_INTERACTIVE_PROVIDER) -> _HistoricalEvent:
    """Build the event as it was written before the interactive path was removed."""
    return _HistoricalEvent(
        _HistoricalTemplate(
            workflow_id=WORKFLOW_ID,
            name="Legacy Interactive Workflow",
            workflow_type="custom",
            classification="standard",
            repository_url="https://github.com/test/repo",
            repository_ref="main",
            requires_repos=False,
            phases=[
                _HistoricalPhase(
                    phase_id="p1",
                    name="Interactive Phase",
                    order=1,
                    prompt_template="do the thing",
                    provider=provider,
                    agent_id="codex",
                )
            ],
        )
    )


def _rehydrate(provider: str = REMOVED_INTERACTIVE_PROVIDER) -> WorkflowTemplateAggregate:
    """Replay the historical creation event onto the CURRENT aggregate code."""
    aggregate = WorkflowTemplateAggregate()
    aggregate._initialize(WORKFLOW_ID)
    event: DomainEvent = _historical_created_event(provider)  # type: ignore[assignment]
    aggregate.on_workflow_created(event)
    return aggregate


class _WorkflowRepositoryStub:
    """Returns the rehydrated template, like the real repository would."""

    def __init__(self, aggregate: WorkflowTemplateAggregate) -> None:
        self._aggregate = aggregate

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        return self._aggregate if aggregate_id == WORKFLOW_ID else None


class ExecutionSpies:
    """The infrastructure a remapped run WOULD have touched."""

    def __init__(self) -> None:
        self.workspace_service = MagicMock()
        self.workspace_service.create_workspace = MagicMock()
        self.command_builder = MagicMock(return_value=["claude", "-p", "do the thing"])
        self.execution_repository = AsyncMock()


def _make_handler(
    aggregate: WorkflowTemplateAggregate,
) -> tuple[ExecuteWorkflowHandler, ExecutionSpies]:
    """Wire the real handler onto the real processor with spied infrastructure."""
    from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
        ExecutionTodoProjection,
    )

    spies = ExecutionSpies()
    processor = WorkflowExecutionProcessor(
        execution_repository=spies.execution_repository,
        session_repository=AsyncMock(),
        workspace_service=spies.workspace_service,
        artifact_repository=AsyncMock(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=AsyncMock(return_value="test prompt"),
        command_builder=spies.command_builder,
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
    )
    handler = ExecuteWorkflowHandler(
        processor=processor,
        workflow_repository=_WorkflowRepositoryStub(aggregate),
    )
    return handler, spies


@pytest.mark.unit
def test_rehydration_of_a_stored_interactive_template_still_succeeds() -> None:
    """Replay must NOT fail: operators still have to read and fix old templates."""
    aggregate = _rehydrate()

    assert aggregate.name == "Legacy Interactive Workflow"
    assert len(aggregate.phases) == 1
    # The stale value survives rehydration verbatim - that is the point. It is
    # execution, not replay, that refuses it.
    assert aggregate.phases[0].provider == REMOVED_INTERACTIVE_PROVIDER


@pytest.mark.unit
async def test_executing_a_stored_interactive_template_is_rejected() -> None:
    """The execution boundary refuses before provisioning or command building."""
    handler, spies = _make_handler(_rehydrate())

    with pytest.raises(UnsupportedAgentProviderError) as exc_info:
        await handler.handle(ExecuteWorkflowCommand(aggregate_id=WORKFLOW_ID))

    message = str(exc_info.value)
    assert REMOVED_INTERACTIVE_PROVIDER in message
    assert "removed" in message
    # Actionable migration path, not a bare "unknown provider".
    assert AgentProvider.CLAUDE in message
    assert AgentProvider.CODEX in message

    # No workspace, no agent command, no execution stream: nothing ran and
    # nothing could have been reported successful.
    spies.workspace_service.create_workspace.assert_not_called()
    spies.command_builder.assert_not_called()
    spies.execution_repository.save.assert_not_awaited()


@pytest.mark.unit
async def test_a_stored_claude_template_still_executes() -> None:
    """The guard rejects the removed provider only, not ordinary headless work."""
    handler, spies = _make_handler(_rehydrate(provider=AgentProvider.CLAUDE))

    result = await handler.handle(ExecuteWorkflowCommand(aggregate_id=WORKFLOW_ID))

    assert result is not None
    spies.execution_repository.save.assert_awaited()
