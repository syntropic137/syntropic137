"""In-memory repository implementations for TESTING ONLY.

WARNING: These repositories are for unit/integration tests only.
For local development, use Docker with PostgreSQL (see docker/docker-compose.dev.yaml).

See in_memory.py for the event store and core utilities.
InMemoryWorkflowRepository lives in in_memory_workflow_repo.py.
InMemoryOrganizationRepository, InMemorySystemRepository, and InMemoryRepoRepository
live in in_memory_org_repos.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.storage.in_memory import _assert_test_environment
from syn_adapters.storage.in_memory_org_repos import (
    InMemoryOrganizationRepository,
    InMemoryRepoRepository,
    InMemorySystemRepository,
)
from syn_adapters.storage.in_memory_workflow_repo import InMemoryWorkflowRepository

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

__all__ = [
    "InMemoryWorkflowRepository",
    "InMemoryOrganizationRepository",
    "InMemorySystemRepository",
    "InMemoryRepoRepository",
    "InMemorySessionRepository",
    "InMemoryArtifactRepository",
    "InMemoryWorkflowExecutionRepository",
]


class InMemorySessionRepository:
    """In-memory repository for AgentSession aggregates.

    Used for testing ONLY.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self) -> None:
        _assert_test_environment()
        self._sessions: dict[str, AgentSessionAggregate] = {}

    async def save(self, aggregate: AgentSessionAggregate) -> None:
        """Save the session aggregate."""
        if aggregate.id:
            self._sessions[str(aggregate.id)] = aggregate
            aggregate.mark_events_as_committed()

    async def get(self, session_id: str) -> AgentSessionAggregate | None:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def get_all(self) -> list[AgentSessionAggregate]:
        """Get all sessions."""
        return list(self._sessions.values())

    def get_by_workflow(self, workflow_id: str) -> list[AgentSessionAggregate]:
        """Get all sessions for a workflow."""
        return [s for s in self._sessions.values() if s.workflow_id == workflow_id]

    def clear(self) -> None:
        """Clear all sessions."""
        self._sessions = {}


class InMemoryArtifactRepository:
    """In-memory repository for Artifact aggregates.

    Used for testing ONLY.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self) -> None:
        _assert_test_environment()
        self._artifacts: dict[str, ArtifactAggregate] = {}

    async def save(self, aggregate: ArtifactAggregate) -> None:
        """Save the artifact aggregate."""
        if aggregate.id:
            self._artifacts[str(aggregate.id)] = aggregate
            aggregate.mark_events_as_committed()

    async def get(self, artifact_id: str) -> ArtifactAggregate | None:
        """Get artifact by ID."""
        return self._artifacts.get(artifact_id)

    def get_all(self) -> list[ArtifactAggregate]:
        """Get all artifacts."""
        return list(self._artifacts.values())

    def get_by_workflow(self, workflow_id: str) -> list[ArtifactAggregate]:
        """Get all artifacts for a workflow."""
        return [a for a in self._artifacts.values() if a.workflow_id == workflow_id]

    def get_by_phase(self, workflow_id: str, phase_id: str) -> list[ArtifactAggregate]:
        """Get all artifacts for a specific phase."""
        return [
            a
            for a in self._artifacts.values()
            if a.workflow_id == workflow_id and a.phase_id == phase_id
        ]

    def clear(self) -> None:
        """Clear all artifacts."""
        self._artifacts = {}


class InMemoryWorkflowExecutionRepository:
    """In-memory repository for WorkflowExecution aggregates.

    Used for testing ONLY.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self) -> None:
        _assert_test_environment()
        self._executions: dict[str, WorkflowExecutionAggregate] = {}

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        """Save the execution aggregate."""
        if aggregate.id:
            self._executions[str(aggregate.id)] = aggregate
            aggregate.mark_events_as_committed()

    async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None:
        """Get execution by ID."""
        return self._executions.get(execution_id)

    async def exists(self, execution_id: str) -> bool:
        """Check if execution exists."""
        return execution_id in self._executions

    def get_all(self) -> list[WorkflowExecutionAggregate]:
        """Get all executions."""
        return list(self._executions.values())

    def get_by_workflow(self, workflow_id: str) -> list[WorkflowExecutionAggregate]:
        """Get all executions for a workflow."""
        return [e for e in self._executions.values() if e.workflow_id == workflow_id]

    def clear(self) -> None:
        """Clear all executions."""
        self._executions = {}
