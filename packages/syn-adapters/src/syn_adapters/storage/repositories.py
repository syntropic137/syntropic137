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

from syn_shared.settings import get_settings

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
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )

logger = logging.getLogger(__name__)


class RepositoryAdapter[TAggregate]:
    """Adapter that wraps EventStoreRepository to provide get_by_id interface.

    The SDK's EventStoreRepository uses `load()` for fetching aggregates,
    but our domain expects `get_by_id()`. This adapter provides the mapping.
    """

    def __init__(self, sdk_repository: Any) -> None:  # noqa: ANN401
        """Initialize with an SDK EventStoreRepository."""
        self._repo = sdk_repository

    async def get_by_id(self, aggregate_id: str) -> TAggregate | None:
        """Get aggregate by ID (maps to SDK's load method)."""
        return await self._repo.load(aggregate_id)

    async def save(self, aggregate: TAggregate) -> None:
        """Save an aggregate."""
        await self._repo.save(aggregate)

    async def save_new(self, aggregate: TAggregate) -> None:
        """Save a new aggregate (raises StreamAlreadyExistsError if stream exists)."""
        await self._repo.save_new(aggregate)

    async def exists(self, aggregate_id: str) -> bool:
        """Check if aggregate exists."""
        return await self._repo.exists(aggregate_id)

    # Allow access to underlying repository if needed
    @property
    def sdk_repository(self) -> Any:  # noqa: ANN401
        """Get the underlying SDK repository."""
        return self._repo


# Cached repository instances (wrapped adapters for SDK-based repos)
_workflow_repository: RepositoryAdapter[WorkflowTemplateAggregate] | None = None
_workflow_execution_repository: RepositoryAdapter[WorkflowExecutionAggregate] | None = None
_session_repository: RepositoryAdapter[AgentSessionAggregate] | None = None
_artifact_repository: RepositoryAdapter[ArtifactAggregate] | None = None
_trigger_repository: RepositoryAdapter[Any] | None = None
_organization_repository: RepositoryAdapter[Any] | None = None
_system_repository: RepositoryAdapter[Any] | None = None
_repo_repository: RepositoryAdapter[Any] | None = None
_repo_claim_repository: RepositoryAdapter[Any] | None = None


def _get_repository_factory() -> Any:  # noqa: ANN401
    """Get a RepositoryFactory with the appropriate EventStoreClient."""
    from event_sourcing import RepositoryFactory

    from syn_adapters.storage.event_store_client import get_event_store_client

    client = get_event_store_client()
    return RepositoryFactory(client)


def get_workflow_repository() -> (
    Any  # noqa: ANN401
):  # RepositoryAdapter[WorkflowTemplateAggregate] or InMemoryWorkflowRepository
    """Get a WorkflowTemplateAggregate repository.

    For TEST: Returns InMemoryWorkflowRepository (synchronous API)
    For DEV/PROD: Returns RepositoryAdapter wrapping EventStoreRepository (async SDK-based)

    Returns:
        Repository for WorkflowTemplateAggregate with get_by_id/save/exists interface.
    """
    settings = get_settings()

    if settings.is_test:
        # Use in-memory for tests (synchronous API, no external dependencies)
        from syn_adapters.storage.in_memory import (
            get_workflow_repository as get_inmem_workflow_repo,
        )

        return get_inmem_workflow_repo()

    # Use SDK-based repository for non-test environments
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

    logger.debug("Created WorkflowTemplateAggregate repository (SDK wrapped)")
    return _workflow_repository


def get_workflow_execution_repository() -> (
    Any  # noqa: ANN401
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
        from syn_adapters.storage.in_memory import (
            get_workflow_execution_repository as get_inmem_exec_repo,
        )

        return get_inmem_exec_repo()

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

    logger.debug("Created WorkflowExecutionAggregate repository (SDK wrapped)")
    return _workflow_execution_repository


def get_session_repository() -> (
    Any  # noqa: ANN401
):  # RepositoryAdapter[AgentSessionAggregate] or InMemorySessionRepository
    """Get an AgentSessionAggregate repository.

    For TEST: Returns InMemorySessionRepository (synchronous API)
    For DEV/PROD: Returns RepositoryAdapter wrapping EventStoreRepository (async SDK-based)

    Returns:
        Repository for AgentSessionAggregate with get_by_id/save/exists interface.
    """
    settings = get_settings()

    if settings.is_test:
        from syn_adapters.storage.in_memory import (
            get_session_repository as get_inmem_session_repo,
        )

        return get_inmem_session_repo()

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

    logger.debug("Created AgentSessionAggregate repository (SDK wrapped)")
    return _session_repository


def get_artifact_repository() -> (
    Any  # noqa: ANN401
):  # RepositoryAdapter[ArtifactAggregate] or InMemoryArtifactRepository
    """Get an ArtifactAggregate repository.

    For TEST: Returns InMemoryArtifactRepository (synchronous API)
    For DEV/PROD: Returns RepositoryAdapter wrapping EventStoreRepository (async SDK-based)

    Returns:
        Repository for ArtifactAggregate with get_by_id/save/exists interface.
    """
    settings = get_settings()

    if settings.is_test:
        from syn_adapters.storage.in_memory import (
            get_artifact_repository as get_inmem_artifact_repo,
        )

        return get_inmem_artifact_repo()

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

    logger.debug("Created ArtifactAggregate repository (SDK wrapped)")
    return _artifact_repository


def get_trigger_repository() -> Any:  # noqa: ANN401
    """Get a TriggerRuleAggregate repository.

    For TEST: Returns in-memory query store (backward-compatible)
    For DEV/PROD: Returns RepositoryAdapter wrapping EventStoreRepository

    Returns:
        Repository for TriggerRuleAggregate with get_by_id/save interface.
    """
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

    logger.debug("Created TriggerRuleAggregate repository (SDK wrapped)")
    return _trigger_repository


def get_organization_repository() -> Any:  # noqa: ANN401
    """Get an OrganizationAggregate repository.

    For TEST: Returns in-memory repository
    For DEV/PROD: Returns RepositoryAdapter wrapping EventStoreRepository

    Returns:
        Repository for OrganizationAggregate with get_by_id/save/exists interface.
    """
    settings = get_settings()

    if settings.is_test:
        from syn_adapters.storage.in_memory import (
            get_organization_repository as get_inmem_org_repo,
        )

        return get_inmem_org_repo()

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

    logger.debug("Created OrganizationAggregate repository (SDK wrapped)")
    return _organization_repository


def get_system_repository() -> Any:  # noqa: ANN401
    """Get a SystemAggregate repository.

    For TEST: Returns in-memory repository
    For DEV/PROD: Returns RepositoryAdapter wrapping EventStoreRepository

    Returns:
        Repository for SystemAggregate with get_by_id/save/exists interface.
    """
    settings = get_settings()

    if settings.is_test:
        from syn_adapters.storage.in_memory import (
            get_system_repository as get_inmem_sys_repo,
        )

        return get_inmem_sys_repo()

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

    logger.debug("Created SystemAggregate repository (SDK wrapped)")
    return _system_repository


def get_repo_repository() -> Any:  # noqa: ANN401
    """Get a RepoAggregate repository.

    For TEST: Returns in-memory repository
    For DEV/PROD: Returns RepositoryAdapter wrapping EventStoreRepository

    Returns:
        Repository for RepoAggregate with get_by_id/save/exists interface.
    """
    settings = get_settings()

    if settings.is_test:
        from syn_adapters.storage.in_memory import (
            get_repo_repository as get_inmem_repo_repo,
        )

        return get_inmem_repo_repo()

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

    logger.debug("Created RepoAggregate repository (SDK wrapped)")
    return _repo_repository


def get_repo_claim_repository() -> Any:  # noqa: ANN401
    """Get a RepoClaimAggregate repository.

    For TEST: Returns in-memory repository
    For DEV/PROD: Returns RepositoryAdapter wrapping EventStoreRepository

    Returns:
        Repository for RepoClaimAggregate with get_by_id/save/save_new/exists interface.
    """
    settings = get_settings()

    if settings.is_test:
        from syn_adapters.storage.in_memory import (
            get_repo_claim_repository as get_inmem_claim_repo,
        )

        return get_inmem_claim_repo()

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

    logger.debug("Created RepoClaimAggregate repository (SDK wrapped)")
    return _repo_claim_repository


def reset_repositories() -> None:
    """Reset all cached repositories (for testing).

    Clears all cached repository instances. Call this along with
    reset_event_store_client() for a clean state.
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

    # Also reset in-memory repos if we're in test mode
    settings = get_settings()
    if settings.is_test:
        from syn_adapters.storage.in_memory import reset_storage

        reset_storage()

    logger.debug("Reset all repository caches")
