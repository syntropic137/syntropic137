"""Singleton factory functions for in-memory storage (TESTING ONLY).

Lazy-loaded global instances for simple DI in test environments.
These are created on first access, not at module import time.

See in_memory.py for the event store and core utilities.
See in_memory_repositories.py for repository implementations.
"""

from __future__ import annotations

from syn_adapters.storage.in_memory import InMemoryEventPublisher, InMemoryEventStore
from syn_adapters.storage.in_memory_repositories import (
    InMemoryArtifactRepository,
    InMemoryOrganizationRepository,
    InMemoryRepoRepository,
    InMemorySessionRepository,
    InMemorySystemRepository,
    InMemoryWorkflowExecutionRepository,
    InMemoryWorkflowRepository,
)

# Lazy-loaded global instances for simple DI (test environments only)
# These are created on first access, not at module import time
_event_store: InMemoryEventStore | None = None
_workflow_repository: InMemoryWorkflowRepository | None = None
_workflow_execution_repository: InMemoryWorkflowExecutionRepository | None = None
_event_publisher: InMemoryEventPublisher | None = None
_session_repository: InMemorySessionRepository | None = None
_artifact_repository: InMemoryArtifactRepository | None = None
_organization_repository: InMemoryOrganizationRepository | None = None
_system_repository: InMemorySystemRepository | None = None
_repo_repository: InMemoryRepoRepository | None = None


def get_event_store() -> InMemoryEventStore:
    """Get the global in-memory event store.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _event_store
    if _event_store is None:
        _event_store = InMemoryEventStore()
    return _event_store


def get_workflow_repository() -> InMemoryWorkflowRepository:
    """Get the global in-memory workflow repository.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _workflow_repository
    if _workflow_repository is None:
        _workflow_repository = InMemoryWorkflowRepository(get_event_store())
    return _workflow_repository


def get_event_publisher() -> InMemoryEventPublisher:
    """Get the global in-memory event publisher.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _event_publisher
    if _event_publisher is None:
        _event_publisher = InMemoryEventPublisher()
    return _event_publisher


def get_session_repository() -> InMemorySessionRepository:
    """Get the global in-memory session repository.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _session_repository
    if _session_repository is None:
        _session_repository = InMemorySessionRepository()
    return _session_repository


def get_artifact_repository() -> InMemoryArtifactRepository:
    """Get the global in-memory artifact repository.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _artifact_repository
    if _artifact_repository is None:
        _artifact_repository = InMemoryArtifactRepository()
    return _artifact_repository


def get_workflow_execution_repository() -> InMemoryWorkflowExecutionRepository:
    """Get the global in-memory workflow execution repository.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _workflow_execution_repository
    if _workflow_execution_repository is None:
        _workflow_execution_repository = InMemoryWorkflowExecutionRepository()
    return _workflow_execution_repository


def get_organization_repository() -> InMemoryOrganizationRepository:
    """Get the global in-memory organization repository.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _organization_repository
    if _organization_repository is None:
        _organization_repository = InMemoryOrganizationRepository()
    return _organization_repository


def get_system_repository() -> InMemorySystemRepository:
    """Get the global in-memory system repository.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _system_repository
    if _system_repository is None:
        _system_repository = InMemorySystemRepository()
    return _system_repository


def get_repo_repository() -> InMemoryRepoRepository:
    """Get the global in-memory repo repository.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _repo_repository
    if _repo_repository is None:
        _repo_repository = InMemoryRepoRepository()
    return _repo_repository


def reset_storage() -> None:
    """Reset all storage (for testing between tests).

    Clears all in-memory stores if they have been initialized.
    """
    if _event_store is not None:
        _event_store.clear()
    if _event_publisher is not None:
        _event_publisher.clear()
    if _session_repository is not None:
        _session_repository.clear()
    if _artifact_repository is not None:
        _artifact_repository.clear()
    if _workflow_execution_repository is not None:
        _workflow_execution_repository.clear()
    if _organization_repository is not None:
        _organization_repository.clear()
    if _system_repository is not None:
        _system_repository.clear()
    if _repo_repository is not None:
        _repo_repository.clear()
