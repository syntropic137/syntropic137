"""In-memory repository implementations for TESTING ONLY.

WARNING: These repositories are for unit/integration tests only.
For local development, use Docker with PostgreSQL (see docker/docker-compose.dev.yaml).

See in_memory.py for the event store and core utilities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from syn_adapters.storage.in_memory import InMemoryEventStore, _assert_test_environment

if TYPE_CHECKING:
    from uuid import UUID

    from event_sourcing import EventEnvelope

    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )


class InMemoryWorkflowRepository:
    """In-memory repository for Workflow aggregates.

    Implements the WorkflowRepository protocol defined in the handler.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        _assert_test_environment()
        self._event_store = event_store

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        """Save the aggregate's uncommitted events to the store."""
        events = aggregate.get_uncommitted_events()

        for i, event_envelope in enumerate(events):
            event = event_envelope.event
            # Extract event data for storage
            event_data = event.model_dump() if hasattr(event, "model_dump") else {}

            self._event_store.append(
                aggregate_id=str(aggregate.id) if aggregate.id else "",
                aggregate_type=aggregate.get_aggregate_type(),
                event_type=event.event_type
                if hasattr(event, "event_type")
                else type(event).__name__,
                event_data=event_data,
                version=aggregate.version + i + 1,
            )

    async def exists(self, workflow_id: str | UUID) -> bool:
        """Check if a workflow exists by ID."""
        str_id = str(workflow_id)
        stored_events = self._event_store.get_events(str_id)
        return len(stored_events) > 0

    async def get_by_id(self, workflow_id: str | UUID) -> WorkflowTemplateAggregate | None:
        """Retrieve a workflow by ID, replaying events."""
        from event_sourcing import EventEnvelope, EventMetadata

        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
            WorkflowTemplateAggregate,
        )
        from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
            WorkflowTemplateCreatedEvent,
        )

        str_id = str(workflow_id)
        stored_events = self._event_store.get_events(str_id)

        if not stored_events:
            return None

        # Reconstruct aggregate from events using SDK's rehydrate method
        aggregate = WorkflowTemplateAggregate()

        # Build EventEnvelope list for rehydration
        envelopes: list[EventEnvelope[WorkflowTemplateCreatedEvent]] = []
        for stored_event in stored_events:
            if stored_event.event_type == "WorkflowTemplateCreated":
                # Reconstruct the event from stored data
                event = WorkflowTemplateCreatedEvent(**stored_event.event_data)
                metadata = EventMetadata(
                    event_id=f"evt-{stored_event.sequence}",
                    aggregate_id=stored_event.aggregate_id,
                    aggregate_type=stored_event.aggregate_type,
                    aggregate_nonce=stored_event.version,
                )
                envelope = EventEnvelope(event=event, metadata=metadata)
                envelopes.append(envelope)

        # Use SDK's rehydrate method for proper event sourcing replay
        aggregate.rehydrate(envelopes)  # type: ignore[arg-type]  # generic covariance: list[EventEnvelope[SpecificEvent]] is compatible with list[EventEnvelope[DomainEvent]]

        return aggregate

    def get_all(self) -> list[WorkflowTemplateAggregate]:
        """Get all workflows."""
        from event_sourcing import EventEnvelope, EventMetadata

        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
            WorkflowTemplateAggregate,
        )
        from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
            WorkflowTemplateCreatedEvent,
        )

        # Get unique aggregate IDs
        aggregate_ids: set[str] = set()
        for event in self._event_store.get_all_events():
            if event.aggregate_type == "WorkflowTemplate":
                aggregate_ids.add(event.aggregate_id)

        workflows: list[WorkflowTemplateAggregate] = []
        for agg_id in aggregate_ids:
            stored_events = self._event_store.get_events(agg_id)
            if not stored_events:
                continue

            aggregate = WorkflowTemplateAggregate()
            envelopes: list[EventEnvelope[Any]] = []
            for stored_event in stored_events:
                if stored_event.event_type == "WorkflowTemplateCreated":
                    workflow_event = WorkflowTemplateCreatedEvent(**stored_event.event_data)
                    metadata = EventMetadata(
                        event_id=f"evt-{stored_event.sequence}",
                        aggregate_id=stored_event.aggregate_id,
                        aggregate_type=stored_event.aggregate_type,
                        aggregate_nonce=stored_event.version,
                    )
                    envelope: EventEnvelope[Any] = EventEnvelope(
                        event=workflow_event, metadata=metadata
                    )
                    envelopes.append(envelope)

            if envelopes:
                aggregate.rehydrate(envelopes)
                workflows.append(aggregate)

        return workflows


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


class InMemoryOrganizationRepository:
    """In-memory repository for Organization aggregates.

    Used for testing ONLY.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self) -> None:
        _assert_test_environment()
        self._organizations: dict[str, Any] = {}

    async def save(self, aggregate: Any) -> None:
        """Save the organization aggregate and publish uncommitted events.

        Publishes events to InMemoryEventPublisher so that
        sync_published_events_to_projections() can dispatch them — mirroring
        the production flow (SDK save -> event store -> subscription service).
        """
        if aggregate.id:
            self._organizations[str(aggregate.id)] = aggregate
        events = (
            aggregate.get_uncommitted_events()
            if hasattr(aggregate, "get_uncommitted_events")
            else []
        )
        if events:
            from syn_adapters.storage.in_memory_factories import get_event_publisher

            publisher = get_event_publisher()
            await publisher.publish(events)

    async def get_by_id(self, organization_id: str) -> Any:
        """Get organization by ID."""
        return self._organizations.get(organization_id)

    async def exists(self, organization_id: str) -> bool:
        """Check if organization exists."""
        return organization_id in self._organizations

    def get_all(self) -> list[Any]:
        """Get all organizations."""
        return list(self._organizations.values())

    def clear(self) -> None:
        """Clear all organizations."""
        self._organizations = {}


class InMemorySystemRepository:
    """In-memory repository for System aggregates.

    Used for testing ONLY.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self) -> None:
        _assert_test_environment()
        self._systems: dict[str, Any] = {}

    async def save(self, aggregate: Any) -> None:
        """Save the system aggregate and publish uncommitted events."""
        if aggregate.id:
            self._systems[str(aggregate.id)] = aggregate
        events = (
            aggregate.get_uncommitted_events()
            if hasattr(aggregate, "get_uncommitted_events")
            else []
        )
        if events:
            from syn_adapters.storage.in_memory_factories import get_event_publisher

            publisher = get_event_publisher()
            await publisher.publish(events)

    async def get_by_id(self, system_id: str) -> Any:
        """Get system by ID."""
        return self._systems.get(system_id)

    async def exists(self, system_id: str) -> bool:
        """Check if system exists."""
        return system_id in self._systems

    def get_all(self) -> list[Any]:
        """Get all systems."""
        return list(self._systems.values())

    def clear(self) -> None:
        """Clear all systems."""
        self._systems = {}


class InMemoryRepoRepository:
    """In-memory repository for Repo aggregates.

    Used for testing ONLY.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self) -> None:
        _assert_test_environment()
        self._repos: dict[str, Any] = {}

    async def save(self, aggregate: Any) -> None:
        """Save the repo aggregate and publish uncommitted events."""
        if aggregate.id:
            self._repos[str(aggregate.id)] = aggregate
        events = (
            aggregate.get_uncommitted_events()
            if hasattr(aggregate, "get_uncommitted_events")
            else []
        )
        if events:
            from syn_adapters.storage.in_memory_factories import get_event_publisher

            publisher = get_event_publisher()
            await publisher.publish(events)

    async def get_by_id(self, repo_id: str) -> Any:
        """Get repo by ID."""
        return self._repos.get(repo_id)

    async def exists(self, repo_id: str) -> bool:
        """Check if repo exists."""
        return repo_id in self._repos

    def get_all(self) -> list[Any]:
        """Get all repos."""
        return list(self._repos.values())

    def clear(self) -> None:
        """Clear all repos."""
        self._repos = {}


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
