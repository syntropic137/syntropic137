"""Types for WorkflowExecutionProcessor dependency injection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    ExecutionMetrics,
    PhaseResult,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
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
    async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None: ...


class SessionRepository(Protocol):
    """Repository for AgentSession aggregates."""

    async def save(self, aggregate: AgentSessionAggregate) -> None: ...


class ArtifactRepository(Protocol):
    """Repository for Artifact aggregates."""

    async def save(self, aggregate: ArtifactAggregate) -> None: ...
    async def get_by_id(self, artifact_id: str) -> ArtifactAggregate | None: ...


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
