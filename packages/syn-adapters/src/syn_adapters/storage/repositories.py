"""Repository implementations using Event Sourcing SDK.

All repositories use the SDK's EventStoreRepository, wrapped by RepositoryAdapter.
The event store client (event_store_client.py) is the single decision point:
MemoryEventStoreClient for tests, GrpcEventStoreClient for dev/prod.

See ADR-007 for architecture details.

Usage:
    # Get repositories (auto-selects client based on environment)
    workflow_repo = get_workflow_repository()
    session_repo = get_session_repository()
    artifact_repo = get_artifact_repository()
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RepositoryAdapter[TAggregate]:
    """Adapter that wraps EventStoreRepository to provide get_by_id interface.

    The SDK's EventStoreRepository uses `load()` for fetching aggregates,
    but our domain expects `get_by_id()`. This adapter provides the mapping.

    After each save, uncommitted events are published to the event publisher
    so that ``sync_published_events_to_projections()`` can dispatch them to
    projections in test mode. In production the publisher is a no-op.
    """

    def __init__(self, sdk_repository: Any) -> None:
        """Initialize with an SDK EventStoreRepository."""
        self._repo = sdk_repository

    async def get_by_id(self, aggregate_id: str) -> TAggregate | None:
        """Get aggregate by ID (maps to SDK's load method)."""
        return await self._repo.load(aggregate_id)

    async def save(self, aggregate: TAggregate) -> None:
        """Save an aggregate and publish events for projection sync."""
        uncommitted = self._capture_uncommitted(aggregate)
        await self._repo.save(aggregate)
        await self._publish_events(uncommitted)

    async def save_new(self, aggregate: TAggregate) -> None:
        """Save a new aggregate (raises StreamAlreadyExistsError if stream exists)."""
        uncommitted = self._capture_uncommitted(aggregate)
        await self._repo.save_new(aggregate)
        await self._publish_events(uncommitted)

    async def exists(self, aggregate_id: str) -> bool:
        """Check if aggregate exists."""
        return await self._repo.exists(aggregate_id)

    # Allow access to underlying repository if needed
    @property
    def sdk_repository(self) -> Any:
        """Get the underlying SDK repository."""
        return self._repo

    @staticmethod
    def _capture_uncommitted(aggregate: Any) -> list[Any]:
        """Capture uncommitted events before the SDK marks them as committed."""
        if hasattr(aggregate, "get_uncommitted_events"):
            return list(aggregate.get_uncommitted_events())
        return []

    @staticmethod
    async def _publish_events(events: list[Any]) -> None:
        """Publish events to the event publisher (no-op in production)."""
        if events:
            from syn_adapters.storage import get_event_publisher

            publisher = get_event_publisher()
            await publisher.publish(events)


# Cached repository instances (RepositoryAdapter wrapping SDK repos)
_workflow_repository: RepositoryAdapter[Any] | None = None
_workflow_execution_repository: RepositoryAdapter[Any] | None = None
_session_repository: RepositoryAdapter[Any] | None = None
_artifact_repository: RepositoryAdapter[Any] | None = None
_trigger_repository: RepositoryAdapter[Any] | None = None
_organization_repository: RepositoryAdapter[Any] | None = None
_system_repository: RepositoryAdapter[Any] | None = None
_repo_repository: RepositoryAdapter[Any] | None = None
_repo_claim_repository: RepositoryAdapter[Any] | None = None


def _get_repository_factory() -> Any:
    """Get a RepositoryFactory with the appropriate EventStoreClient.

    The client is the single decision point: MemoryEventStoreClient for
    tests, GrpcEventStoreClient for dev/prod (see event_store_client.py).
    """
    from event_sourcing import RepositoryFactory

    from syn_adapters.storage.event_store_client import get_event_store_client

    client = get_event_store_client()
    return RepositoryFactory(client)


def get_workflow_repository() -> Any:
    """Get a WorkflowTemplateAggregate repository."""
    global _workflow_repository
    if _workflow_repository is not None:
        return _workflow_repository

    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        WorkflowTemplateAggregate,
        aggregate_type="WorkflowTemplate",
    )
    _workflow_repository = RepositoryAdapter(sdk_repo)
    return _workflow_repository


def get_workflow_execution_repository() -> Any:
    """Get a WorkflowExecutionAggregate repository."""
    global _workflow_execution_repository
    if _workflow_execution_repository is not None:
        return _workflow_execution_repository

    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        WorkflowExecutionAggregate,
        aggregate_type="WorkflowExecution",
    )
    _workflow_execution_repository = RepositoryAdapter(sdk_repo)
    return _workflow_execution_repository


def get_session_repository() -> Any:
    """Get an AgentSessionAggregate repository."""
    global _session_repository
    if _session_repository is not None:
        return _session_repository

    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        AgentSessionAggregate,
        aggregate_type="AgentSession",
    )
    _session_repository = RepositoryAdapter(sdk_repo)
    return _session_repository


def get_artifact_repository() -> Any:
    """Get an ArtifactAggregate repository."""
    global _artifact_repository
    if _artifact_repository is not None:
        return _artifact_repository

    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        ArtifactAggregate,
        aggregate_type="Artifact",
    )
    _artifact_repository = RepositoryAdapter(sdk_repo)
    return _artifact_repository


def get_trigger_repository() -> Any:
    """Get a TriggerRuleAggregate repository.

    NOTE: In test mode, returns InMemoryTriggerQueryStore (a query store
    with a different interface). This is a special case because the trigger
    system uses a query store pattern, not the standard repository pattern.
    """
    from syn_shared.settings import get_settings

    settings = get_settings()
    if settings.is_test:
        from syn_domain.contexts.github.slices.register_trigger.trigger_store import (
            InMemoryTriggerQueryStore,
        )

        return InMemoryTriggerQueryStore()

    global _trigger_repository
    if _trigger_repository is not None:
        return _trigger_repository

    from syn_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
        TriggerRuleAggregate,
    )

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        TriggerRuleAggregate,
        aggregate_type="TriggerRule",
    )
    _trigger_repository = RepositoryAdapter(sdk_repo)
    return _trigger_repository


def get_organization_repository() -> Any:
    """Get an OrganizationAggregate repository."""
    global _organization_repository
    if _organization_repository is not None:
        return _organization_repository

    from syn_domain.contexts.organization.domain.aggregate_organization.OrganizationAggregate import (
        OrganizationAggregate,
    )

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        OrganizationAggregate,
        aggregate_type="Organization",
    )
    _organization_repository = RepositoryAdapter(sdk_repo)
    return _organization_repository


def get_system_repository() -> Any:
    """Get a SystemAggregate repository."""
    global _system_repository
    if _system_repository is not None:
        return _system_repository

    from syn_domain.contexts.organization.domain.aggregate_system.SystemAggregate import (
        SystemAggregate,
    )

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        SystemAggregate,
        aggregate_type="System",
    )
    _system_repository = RepositoryAdapter(sdk_repo)
    return _system_repository


def get_repo_repository() -> Any:
    """Get a RepoAggregate repository."""
    global _repo_repository
    if _repo_repository is not None:
        return _repo_repository

    from syn_domain.contexts.organization.domain.aggregate_repo.RepoAggregate import (
        RepoAggregate,
    )

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        RepoAggregate,
        aggregate_type="Repo",
    )
    _repo_repository = RepositoryAdapter(sdk_repo)
    return _repo_repository


def get_repo_claim_repository() -> Any:
    """Get a RepoClaimAggregate repository."""
    global _repo_claim_repository
    if _repo_claim_repository is not None:
        return _repo_claim_repository

    from syn_domain.contexts.organization.domain.aggregate_repo_claim.RepoClaimAggregate import (
        RepoClaimAggregate,
    )

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        RepoClaimAggregate,
        aggregate_type="RepoClaim",
    )
    _repo_claim_repository = RepositoryAdapter(sdk_repo)
    return _repo_claim_repository


def reset_repositories() -> None:
    """Reset all cached repository instances.

    After reset, the next call to any factory function creates a fresh
    RepositoryAdapter backed by a new EventStoreRepository. Combined with
    reset_event_store_client() (which replaces the MemoryEventStoreClient),
    this gives each test a clean slate.
    """
    global \
        _workflow_repository, \
        _workflow_execution_repository, \
        _session_repository, \
        _artifact_repository, \
        _trigger_repository, \
        _organization_repository, \
        _system_repository, \
        _repo_repository, \
        _repo_claim_repository
    _workflow_repository = None
    _workflow_execution_repository = None
    _session_repository = None
    _artifact_repository = None
    _trigger_repository = None
    _organization_repository = None
    _system_repository = None
    _repo_repository = None
    _repo_claim_repository = None
