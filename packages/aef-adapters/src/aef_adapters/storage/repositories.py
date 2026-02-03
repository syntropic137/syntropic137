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
    from aef_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import ArtifactAggregate
    from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from aef_domain.contexts.orchestration.domain.aggregate_workflow.WorkflowAggregate import (
        WorkflowAggregate,
    )
    from aef_domain.contexts.sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )

logger = logging.getLogger(__name__)


class RepositoryAdapter[TAggregate]:
    """Adapter that wraps EventStoreRepository to provide get_by_id interface.

    The SDK's EventStoreRepository uses `load()` for fetching aggregates,
    but our domain expects `get_by_id()`. This adapter provides the mapping.
    """

    def __init__(self, sdk_repository: Any) -> None:
        """Initialize with an SDK EventStoreRepository."""
        self._repo = sdk_repository

    async def get_by_id(self, aggregate_id: str) -> TAggregate | None:
        """Get aggregate by ID (maps to SDK's load method)."""
        return await self._repo.load(aggregate_id)

    async def save(self, aggregate: TAggregate) -> None:
        """Save an aggregate."""
        await self._repo.save(aggregate)

    async def exists(self, aggregate_id: str) -> bool:
        """Check if aggregate exists."""
        return await self._repo.exists(aggregate_id)

    # Allow access to underlying repository if needed
    @property
    def sdk_repository(self) -> Any:
        """Get the underlying SDK repository."""
        return self._repo


# Cached repository instances (wrapped adapters for SDK-based repos)
_workflow_repository: RepositoryAdapter[WorkflowAggregate] | None = None
_workflow_execution_repository: RepositoryAdapter[WorkflowExecutionAggregate] | None = None
_session_repository: RepositoryAdapter[AgentSessionAggregate] | None = None
_artifact_repository: RepositoryAdapter[ArtifactAggregate] | None = None


def _get_repository_factory() -> Any:
    """Get a RepositoryFactory with the appropriate EventStoreClient."""
    from event_sourcing import RepositoryFactory

    from aef_adapters.storage.event_store_client import get_event_store_client

    client = get_event_store_client()
    return RepositoryFactory(client)


def get_workflow_repository() -> (
    Any
):  # RepositoryAdapter[WorkflowAggregate] or InMemoryWorkflowRepository
    """Get a WorkflowAggregate repository.

    For TEST: Returns InMemoryWorkflowRepository (synchronous API)
    For DEV/PROD: Returns RepositoryAdapter wrapping EventStoreRepository (async SDK-based)

    Returns:
        Repository for WorkflowAggregate with get_by_id/save/exists interface.
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

    from aef_domain.contexts.orchestration.domain.aggregate_workflow.WorkflowAggregate import (
        WorkflowAggregate,
    )

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        WorkflowAggregate,
        aggregate_type="Workflow",
    )
    _workflow_repository = RepositoryAdapter(sdk_repo)

    logger.debug("Created WorkflowAggregate repository (SDK wrapped)")
    return _workflow_repository


def get_workflow_execution_repository() -> (
    Any
):  # RepositoryAdapter[WorkflowExecutionAggregate] or in-memory
    """Get a WorkflowExecutionAggregate repository.

    For TEST: Returns in-memory repository
    For DEV/PROD: Returns RepositoryAdapter wrapping EventStoreRepository

    Returns:
        Repository for WorkflowExecutionAggregate with get_by_id/save/exists interface.
    """
    settings = get_settings()

    if settings.is_test:
        # For tests, use in-memory (needs to be implemented if not exists)
        from aef_adapters.storage.in_memory import (
            get_workflow_execution_repository as get_inmem_exec_repo,
        )

        return get_inmem_exec_repo()

    global _workflow_execution_repository

    if _workflow_execution_repository is not None:
        return _workflow_execution_repository

    from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        WorkflowExecutionAggregate,
        aggregate_type="WorkflowExecution",
    )
    _workflow_execution_repository = RepositoryAdapter(sdk_repo)

    logger.debug("Created WorkflowExecutionAggregate repository (SDK wrapped)")
    return _workflow_execution_repository


def get_session_repository() -> (
    Any
):  # RepositoryAdapter[AgentSessionAggregate] or InMemorySessionRepository
    """Get an AgentSessionAggregate repository.

    For TEST: Returns InMemorySessionRepository (synchronous API)
    For DEV/PROD: Returns RepositoryAdapter wrapping EventStoreRepository (async SDK-based)

    Returns:
        Repository for AgentSessionAggregate with get_by_id/save/exists interface.
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

    from aef_domain.contexts.sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        AgentSessionAggregate,
        aggregate_type="AgentSession",
    )
    _session_repository = RepositoryAdapter(sdk_repo)

    logger.debug("Created AgentSessionAggregate repository (SDK wrapped)")
    return _session_repository


def get_artifact_repository() -> (
    Any
):  # RepositoryAdapter[ArtifactAggregate] or InMemoryArtifactRepository
    """Get an ArtifactAggregate repository.

    For TEST: Returns InMemoryArtifactRepository (synchronous API)
    For DEV/PROD: Returns RepositoryAdapter wrapping EventStoreRepository (async SDK-based)

    Returns:
        Repository for ArtifactAggregate with get_by_id/save/exists interface.
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

    from aef_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import ArtifactAggregate

    factory = _get_repository_factory()
    sdk_repo = factory.create_repository(
        ArtifactAggregate,
        aggregate_type="Artifact",
    )
    _artifact_repository = RepositoryAdapter(sdk_repo)

    logger.debug("Created ArtifactAggregate repository (SDK wrapped)")
    return _artifact_repository


def reset_repositories() -> None:
    """Reset all cached repositories (for testing).

    Clears all cached repository instances. Call this along with
    reset_event_store_client() for a clean state.
    """
    global \
        _workflow_repository, \
        _workflow_execution_repository, \
        _session_repository, \
        _artifact_repository
    _workflow_repository = None
    _workflow_execution_repository = None
    _session_repository = None
    _artifact_repository = None

    # Also reset in-memory repos if we're in test mode
    settings = get_settings()
    if settings.is_test:
        from aef_adapters.storage.in_memory import reset_storage

        reset_storage()

    logger.debug("Reset all repository caches")
