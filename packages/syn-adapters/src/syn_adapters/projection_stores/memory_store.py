"""In-memory projection store for testing.

This implementation stores all projection data in memory,
making it fast for unit tests while maintaining the same
interface as the production PostgreSQL store.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from syn_adapters.projection_stores.memory_store_helpers import (
    apply_filters,
    apply_pagination,
    apply_sorting,
)
from syn_shared.settings import get_settings


class InMemoryProjectionStoreError(Exception):
    """Error raised when in-memory store is used outside test environment."""


def _assert_test_environment() -> None:
    """Assert that we're in a test environment."""
    settings = get_settings()
    if not settings.is_test:
        raise InMemoryProjectionStoreError(
            "InMemoryProjectionStore can ONLY be used in test environments. "
            f"Current environment: {settings.app_environment}. "
            "For local development, use PostgresProjectionStore. "
            "Set APP_ENVIRONMENT=test to use in-memory storage for unit tests."
        )


@dataclass
class ProjectionState:
    """Tracks state for a single projection."""

    last_position: int | None = None
    last_updated: datetime | None = None


@dataclass
class InMemoryProjectionStore:
    """In-memory implementation of ProjectionStoreProtocol.

    All data is stored in dictionaries. This implementation is only
    available in test environments (APP_ENVIRONMENT=test).
    """

    # Per-projection data: projection_name -> {key -> data}
    _data: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    # Per-projection state: projection_name -> ProjectionState
    _state: dict[str, ProjectionState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate that we're in a test environment."""
        _assert_test_environment()

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        """Save or update a projection record."""
        self._data.setdefault(projection, {})[key] = data.copy()
        self._update_state(projection)

    async def get(self, projection: str, key: str) -> dict[str, Any] | None:
        """Get a single projection record by key."""
        if projection not in self._data:
            return None
        return self._data[projection].get(key)

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        """Get all records for a projection."""
        if projection not in self._data:
            return []
        return list(self._data[projection].values())

    async def delete(self, projection: str, key: str) -> None:
        """Delete a projection record."""
        if projection in self._data and key in self._data[projection]:
            del self._data[projection][key]
            self._update_state(projection)

    async def query(
        self,
        projection: str,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query projection records with optional filtering."""
        if projection not in self._data:
            return []

        results = list(self._data[projection].values())
        results = apply_filters(results, filters)
        results = apply_sorting(results, order_by)
        return apply_pagination(results, offset, limit)

    async def get_position(self, projection: str) -> int | None:
        """Get the last processed event position for a projection."""
        state = self._state.get(projection)
        return state.last_position if state else None

    async def set_position(self, projection: str, position: int) -> None:
        """Update the last processed event position for a projection."""
        state = self._ensure_state(projection)
        state.last_position = position
        state.last_updated = datetime.now(UTC)

    async def get_last_updated(self, projection: str) -> datetime | None:
        """Get the last update timestamp for a projection."""
        state = self._state.get(projection)
        return state.last_updated if state else None

    def _update_state(self, projection: str) -> None:
        """Update the state timestamp for a projection."""
        self._ensure_state(projection).last_updated = datetime.now(UTC)

    def _ensure_state(self, projection: str) -> ProjectionState:
        """Get or create the ProjectionState for a projection."""
        if projection not in self._state:
            self._state[projection] = ProjectionState()
        return self._state[projection]

    def clear(self) -> None:
        """Clear all data (useful for test setup/teardown)."""
        self._data.clear()
        self._state.clear()

    def clear_projection(self, projection: str) -> None:
        """Clear data for a specific projection."""
        if projection in self._data:
            del self._data[projection]
        if projection in self._state:
            del self._state[projection]
