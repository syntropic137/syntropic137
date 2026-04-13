"""Types for WorkflowExecutionProcessor dependency injection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    ExecutionMetrics,
    PhaseResult,
)

if TYPE_CHECKING:
    from datetime import datetime

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )

PromptBuilder = Callable[
    [ExecutablePhase, str, str, str | None, dict[str, str], dict[str, Any]],
    Awaitable[str],
]

CommandBuilder = Callable[[ExecutablePhase, str], list[str]]


class TodoProjection(Protocol):
    """Protocol for the to-do list projection used by the processor."""

    async def get_pending(self, execution_id: str) -> list[TodoItem]: ...


class ExecutionRepository(Protocol):
    """Repository for WorkflowExecution aggregates."""

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None: ...
    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None: ...


class SessionRepository(Protocol):
    """Repository for AgentSession aggregates."""

    async def save(self, aggregate: AgentSessionAggregate) -> None: ...


class ArtifactRepository(Protocol):
    """Repository for Artifact aggregates."""

    async def save(self, aggregate: ArtifactAggregate) -> None: ...
    async def get_by_id(self, aggregate_id: str) -> ArtifactAggregate | None: ...


class AgentHandlerProtocol(Protocol):
    """Structural Protocol for AgentExecutionHandler.

    Defines the contract for running an agent phase. Any class that satisfies this
    Protocol — including ``FakeAgentExecutionHandler`` in tests — will break pyright
    if ``AgentExecutionHandler.handle()`` ever changes its signature, preventing silent
    drift between the real handler and its test doubles.

    Usage in tests::

        processor = WorkflowExecutionProcessor(
            ...
            agent_handler=FakeAgentExecutionHandler.cancelled(),
        )
    """

    async def handle(
        self,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
    ) -> AgentExecutionResult: ...


@dataclass(frozen=True)
class WorkflowExecutionResult:
    """Immutable execution outcome."""

    workflow_id: str
    execution_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    phase_results: list[PhaseResult] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    error_message: str | None = None
