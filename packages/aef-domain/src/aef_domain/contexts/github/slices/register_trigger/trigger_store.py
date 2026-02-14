"""Trigger query store port and in-memory adapter.

The query store handles read-side concerns:
- Trigger index for fast webhook matching
- Safety guard queries (fire counts, cooldowns)
- Delivery idempotency tracking

Write-side persistence is handled by EventStoreRepository (ADR-007).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class TriggerQueryStore(ABC):
    """Read-side query store for trigger rules.

    Provides fast lookups and safety guard queries.
    Write-side persistence is handled by the repository.
    """

    @abstractmethod
    async def index_trigger(
        self,
        trigger_id: str,
        name: str,
        event: str,
        repository: str,
        workflow_id: str,
        conditions: list[Any],
        input_mapping: dict[str, str],
        config: Any,
        installation_id: str,
        created_by: str,
        status: str,
    ) -> None:
        """Index a trigger for fast lookups."""
        ...

    @abstractmethod
    async def update_status(self, trigger_id: str, status: str) -> None:
        """Update a trigger's status in the index."""
        ...

    @abstractmethod
    async def get(self, trigger_id: str) -> Any | None:
        """Get a trigger by ID from the index."""
        ...

    @abstractmethod
    async def list_by_event_and_repo(self, event: str, repository: str) -> list[Any]:
        """List active triggers matching an event and repository."""
        ...

    @abstractmethod
    async def list_all(
        self,
        repository: str | None = None,
        status: str | None = None,
    ) -> list[Any]:
        """List all triggers with optional filters."""
        ...

    @abstractmethod
    async def get_fire_count(self, trigger_id: str, pr_number: int) -> int:
        """Get fire count for a trigger+PR combination."""
        ...

    @abstractmethod
    async def get_last_fired_at(self, trigger_id: str, pr_number: int) -> datetime | None:
        """Get the last fire time for a trigger+PR combination."""
        ...

    @abstractmethod
    async def get_daily_fire_count(self, trigger_id: str) -> int:
        """Get today's fire count for a trigger."""
        ...

    @abstractmethod
    async def was_delivery_processed(self, delivery_id: str) -> bool:
        """Check if a webhook delivery has been processed."""
        ...

    @abstractmethod
    async def record_delivery(self, delivery_id: str, trigger_id: str) -> None:
        """Record a processed webhook delivery."""
        ...

    @abstractmethod
    async def get_last_any_fired_at(
        self, pr_number: int, exclude_trigger_id: str | None = None
    ) -> datetime | None:
        """Get the last fire time for ANY trigger on this PR (excluding a specific trigger)."""
        ...

    @abstractmethod
    async def record_fire(
        self,
        trigger_id: str,
        pr_number: int | None,
        execution_id: str,
    ) -> None:
        """Record a trigger firing."""
        ...


class _IndexedTrigger:
    """Lightweight indexed trigger for query store."""

    def __init__(
        self,
        trigger_id: str,
        name: str,
        event: str,
        repository: str,
        workflow_id: str,
        conditions: list[Any],
        input_mapping: dict[str, str],
        config: Any,
        installation_id: str,
        created_by: str,
        status: str,
    ) -> None:
        self.trigger_id = trigger_id
        self.name = name
        self.event = event
        self.repository = repository
        self.workflow_id = workflow_id
        self.conditions = conditions
        self.input_mapping = input_mapping
        self.config = config
        self.installation_id = installation_id
        self.created_by = created_by
        self.status = status
        self.fire_count = 0


class InMemoryTriggerQueryStore(TriggerQueryStore):
    """In-memory implementation of TriggerQueryStore.

    Suitable for:
    - Tests (always)
    - Development (with acknowledgment that data is not persisted)
    """

    def __init__(self) -> None:
        self._triggers: dict[str, _IndexedTrigger] = {}
        self._fire_records: list[dict] = []
        self._processed_deliveries: set[str] = set()

    async def index_trigger(
        self,
        trigger_id: str,
        name: str,
        event: str,
        repository: str,
        workflow_id: str,
        conditions: list[Any],
        input_mapping: dict[str, str],
        config: Any,
        installation_id: str,
        created_by: str,
        status: str,
    ) -> None:
        self._triggers[trigger_id] = _IndexedTrigger(
            trigger_id=trigger_id,
            name=name,
            event=event,
            repository=repository,
            workflow_id=workflow_id,
            conditions=conditions,
            input_mapping=input_mapping,
            config=config,
            installation_id=installation_id,
            created_by=created_by,
            status=status,
        )

    async def update_status(self, trigger_id: str, status: str) -> None:
        trigger = self._triggers.get(trigger_id)
        if trigger:
            trigger.status = status

    async def get(self, trigger_id: str) -> _IndexedTrigger | None:
        return self._triggers.get(trigger_id)

    async def list_by_event_and_repo(self, event: str, repository: str) -> list[_IndexedTrigger]:
        return [
            t
            for t in self._triggers.values()
            if t.event == event and t.repository == repository and t.status == "active"
        ]

    async def list_all(
        self,
        repository: str | None = None,
        status: str | None = None,
    ) -> list[_IndexedTrigger]:
        results = list(self._triggers.values())
        if repository:
            results = [t for t in results if t.repository == repository]
        if status:
            results = [t for t in results if t.status == status]
        return results

    async def get_fire_count(self, trigger_id: str, pr_number: int) -> int:
        return sum(
            1
            for r in self._fire_records
            if r["trigger_id"] == trigger_id and r.get("pr_number") == pr_number
        )

    async def get_last_fired_at(self, trigger_id: str, pr_number: int) -> datetime | None:
        matching = [
            r
            for r in self._fire_records
            if r["trigger_id"] == trigger_id and r.get("pr_number") == pr_number
        ]
        if not matching:
            return None
        return max(r["fired_at"] for r in matching)

    async def get_daily_fire_count(self, trigger_id: str) -> int:
        today = datetime.now(UTC).date()
        return sum(
            1
            for r in self._fire_records
            if r["trigger_id"] == trigger_id and r["fired_at"].date() == today
        )

    async def get_last_any_fired_at(
        self, pr_number: int, exclude_trigger_id: str | None = None
    ) -> datetime | None:
        matching = [
            r
            for r in self._fire_records
            if r.get("pr_number") == pr_number
            and (exclude_trigger_id is None or r["trigger_id"] != exclude_trigger_id)
        ]
        if not matching:
            return None
        return max(r["fired_at"] for r in matching)

    async def was_delivery_processed(self, delivery_id: str) -> bool:
        return delivery_id in self._processed_deliveries

    async def record_delivery(self, delivery_id: str, trigger_id: str) -> None:  # noqa: ARG002
        self._processed_deliveries.add(delivery_id)

    async def record_fire(
        self,
        trigger_id: str,
        pr_number: int | None,
        execution_id: str,
    ) -> None:
        self._fire_records.append(
            {
                "trigger_id": trigger_id,
                "pr_number": pr_number,
                "execution_id": execution_id,
                "fired_at": datetime.now(UTC),
            }
        )
        trigger = self._triggers.get(trigger_id)
        if trigger:
            trigger.fire_count += 1


# --- Backward-compatible aliases ---
TriggerStore = TriggerQueryStore
InMemoryTriggerStore = InMemoryTriggerQueryStore


_store: TriggerQueryStore | None = None


def get_trigger_query_store() -> TriggerQueryStore:
    """Get the global trigger query store instance."""
    global _store
    if _store is None:
        from aef_shared.settings import get_settings

        settings = get_settings()
        if settings.is_test:
            _store = InMemoryTriggerQueryStore()
        else:
            from aef_adapters.projection_stores import get_projection_store
            from aef_adapters.storage.trigger_query_store import PersistentTriggerQueryStore

            _store = PersistentTriggerQueryStore(get_projection_store())
    return _store


# Backward-compatible alias
get_trigger_store = get_trigger_query_store


def set_trigger_store(store: TriggerQueryStore) -> None:
    """Set the global trigger query store instance."""
    global _store
    _store = store


def reset_trigger_store() -> None:
    """Reset the global store (for testing)."""
    global _store
    _store = None
