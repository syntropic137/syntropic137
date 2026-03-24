"""In-memory organization-related repositories (TESTING ONLY).

Extracted from in_memory_repositories.py to reduce module complexity.

WARNING: These repositories are for unit/integration tests only.
"""

from __future__ import annotations

from typing import Any

from syn_adapters.storage.in_memory import _assert_test_environment


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
