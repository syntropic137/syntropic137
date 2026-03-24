"""In-memory repository for Repo aggregates (TESTING ONLY).

Extracted from in_memory_org_repos.py to reduce module complexity.

WARNING: This repository is for unit/integration tests only.
"""

from __future__ import annotations

from typing import Any

from syn_adapters.storage.in_memory import _assert_test_environment


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
