"""Repository implementations using Event Sourcing SDK.

This module provides repository factories that use the event_sourcing SDK's
EventStoreRepository pattern for non-test environments. For tests, it falls
back to in-memory implementations.

See ADR-007 for architecture details.

Usage:
    # Get repositories (auto-selects client based on environment)
    workflow_repo = get_workflow_repository()
    session_repo = get_session_repository()
    artifact_repo = get_artifact_repository()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aef_shared.settings import get_settings

if TYPE_CHECKING:
    from event_sourcing import EventStoreRepository

    from aef_domain.contexts.artifacts._shared.ArtifactAggregate import ArtifactAggregate
    from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from aef_domain.contexts.workflows._shared.WorkflowAggregate import WorkflowAggregate

logger = logging.getLogger(__name__)

# Cached repository instances (for SDK-based repos)
_workflow_repository: EventStoreRepository[WorkflowAggregate] | None = None
_session_repository: EventStoreRepository[AgentSessionAggregate] | None = None
_artifact_repository: EventStoreRepository[ArtifactAggregate] | None = None


def _get_repository_factory() -> Any:
    """Get a RepositoryFactory with the appropriate EventStoreClient."""
    from event_sourcing import RepositoryFactory

    from aef_adapters.storage.event_store_client import get_event_store_client

    client = get_event_store_client()
    return RepositoryFactory(client)


def get_workflow_repository() -> (
    Any
):  # EventStoreRepository[WorkflowAggregate] or InMemoryWorkflowRepository
    """Get a WorkflowAggregate repository.

    For TEST: Returns InMemoryWorkflowRepository (synchronous API)
    For DEV/PROD: Returns EventStoreRepository (async SDK-based)

    Returns:
        Repository for WorkflowAggregate.
    """
    settings = get_settings()

    if settings.is_test:
        # Use in-memory for tests (synchronous API, no external dependencies)
        from aef_adapters.storage.in_memory import (
            get_workflow_repository as get_inmem_workflow_repo,
        )

        return get_inmem_workflow_repo()

    # Use SDK-based repository for non-test environments
    global _workflow_repository

    if _workflow_repository is not None:
        return _workflow_repository

    from aef_domain.contexts.workflows._shared.WorkflowAggregate import WorkflowAggregate

    factory = _get_repository_factory()
    _workflow_repository = factory.create_repository(
        WorkflowAggregate,
        aggregate_type="Workflow",
    )

    logger.debug("Created WorkflowAggregate repository (SDK)")
    return _workflow_repository


def get_session_repository() -> (
    Any
):  # EventStoreRepository[AgentSessionAggregate] or InMemorySessionRepository
    """Get an AgentSessionAggregate repository.

    For TEST: Returns InMemorySessionRepository (synchronous API)
    For DEV/PROD: Returns EventStoreRepository (async SDK-based)

    Returns:
        Repository for AgentSessionAggregate.
    """
    settings = get_settings()

    if settings.is_test:
        from aef_adapters.storage.in_memory import (
            get_session_repository as get_inmem_session_repo,
        )

        return get_inmem_session_repo()

    global _session_repository

    if _session_repository is not None:
        return _session_repository

    from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
        AgentSessionAggregate,
    )

    factory = _get_repository_factory()
    _session_repository = factory.create_repository(
        AgentSessionAggregate,
        aggregate_type="AgentSession",
    )

    logger.debug("Created AgentSessionAggregate repository (SDK)")
    return _session_repository


def get_artifact_repository() -> (
    Any
):  # EventStoreRepository[ArtifactAggregate] or InMemoryArtifactRepository
    """Get an ArtifactAggregate repository.

    For TEST: Returns InMemoryArtifactRepository (synchronous API)
    For DEV/PROD: Returns EventStoreRepository (async SDK-based)

    Returns:
        Repository for ArtifactAggregate.
    """
    settings = get_settings()

    if settings.is_test:
        from aef_adapters.storage.in_memory import (
            get_artifact_repository as get_inmem_artifact_repo,
        )

        return get_inmem_artifact_repo()

    global _artifact_repository

    if _artifact_repository is not None:
        return _artifact_repository

    from aef_domain.contexts.artifacts._shared.ArtifactAggregate import ArtifactAggregate

    factory = _get_repository_factory()
    _artifact_repository = factory.create_repository(
        ArtifactAggregate,
        aggregate_type="Artifact",
    )

    logger.debug("Created ArtifactAggregate repository (SDK)")
    return _artifact_repository


def reset_repositories() -> None:
    """Reset all cached repositories (for testing).

    Clears all cached repository instances. Call this along with
    reset_event_store_client() for a clean state.
    """
    global _workflow_repository, _session_repository, _artifact_repository
    _workflow_repository = None
    _session_repository = None
    _artifact_repository = None

    # Also reset in-memory repos if we're in test mode
    settings = get_settings()
    if settings.is_test:
        from aef_adapters.storage.in_memory import reset_storage

        reset_storage()

    logger.debug("Reset all repository caches")
