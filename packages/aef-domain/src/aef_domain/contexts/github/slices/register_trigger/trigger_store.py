"""Trigger store port and in-memory adapter.

Provides storage abstraction for TriggerRuleAggregates.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aef_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
        TriggerRuleAggregate,
    )

logger = logging.getLogger(__name__)


class TriggerStore(ABC):
    """Abstract port for trigger rule persistence."""

    @abstractmethod
    async def save(self, aggregate: TriggerRuleAggregate) -> None:
        """Persist a trigger rule aggregate."""

    @abstractmethod
    async def get(self, trigger_id: str) -> TriggerRuleAggregate | None:
        """Get a trigger rule by ID."""

    @abstractmethod
    async def list_by_event_and_repo(
        self, event: str, repository: str
    ) -> list[TriggerRuleAggregate]:
        """List active trigger rules matching event type and repository."""

    @abstractmethod
    async def list_all(
        self,
        repository: str | None = None,
        status: str | None = None,
    ) -> list[TriggerRuleAggregate]:
        """List all trigger rules with optional filters."""

    @abstractmethod
    async def get_fire_count(self, trigger_id: str, pr_number: int) -> int:
        """Get the fire count for a trigger on a specific PR."""

    @abstractmethod
    async def get_last_fired_at(self, trigger_id: str, pr_number: int) -> datetime | None:
        """Get the last fired timestamp for a trigger on a specific PR."""

    @abstractmethod
    async def get_daily_fire_count(self, trigger_id: str) -> int:
        """Get the number of times a trigger has fired today."""

    @abstractmethod
    async def was_delivery_processed(self, delivery_id: str) -> bool:
        """Check if a webhook delivery has already been processed."""

    @abstractmethod
    async def record_delivery(self, delivery_id: str, trigger_id: str) -> None:
        """Record that a webhook delivery has been processed."""

    @abstractmethod
    async def record_fire(
        self,
        trigger_id: str,
        pr_number: int | None,
        execution_id: str,
    ) -> None:
        """Record a trigger firing for tracking purposes."""


class InMemoryTriggerStore(TriggerStore):
    """In-memory implementation of TriggerStore for development and testing."""

    def __init__(self) -> None:
        """Initialize the store."""
        self._triggers: dict[str, TriggerRuleAggregate] = {}
        self._fire_records: list[dict] = []
        self._processed_deliveries: set[str] = set()

    async def save(self, aggregate: TriggerRuleAggregate) -> None:
        """Persist a trigger rule aggregate."""
        self._triggers[aggregate.trigger_id] = aggregate
        aggregate.clear_pending_events()

    async def get(self, trigger_id: str) -> TriggerRuleAggregate | None:
        """Get a trigger rule by ID."""
        return self._triggers.get(trigger_id)

    async def list_by_event_and_repo(
        self, event: str, repository: str
    ) -> list[TriggerRuleAggregate]:
        """List active trigger rules matching event type and repository."""
        from aef_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import (
            TriggerStatus,
        )

        return [
            t
            for t in self._triggers.values()
            if t.event == event and t.repository == repository and t.status == TriggerStatus.ACTIVE
        ]

    async def list_all(
        self,
        repository: str | None = None,
        status: str | None = None,
    ) -> list[TriggerRuleAggregate]:
        """List all trigger rules with optional filters."""
        results = list(self._triggers.values())
        if repository:
            results = [t for t in results if t.repository == repository]
        if status:
            results = [t for t in results if t.status.value == status]
        return results

    async def get_fire_count(self, trigger_id: str, pr_number: int) -> int:
        """Get the fire count for a trigger on a specific PR."""
        return sum(
            1
            for r in self._fire_records
            if r["trigger_id"] == trigger_id and r.get("pr_number") == pr_number
        )

    async def get_last_fired_at(self, trigger_id: str, pr_number: int) -> datetime | None:
        """Get the last fired timestamp for a trigger on a specific PR."""
        matching = [
            r
            for r in self._fire_records
            if r["trigger_id"] == trigger_id and r.get("pr_number") == pr_number
        ]
        if not matching:
            return None
        return max(r["fired_at"] for r in matching)

    async def get_daily_fire_count(self, trigger_id: str) -> int:
        """Get the number of times a trigger has fired today."""
        today = datetime.now(UTC).date()
        return sum(
            1
            for r in self._fire_records
            if r["trigger_id"] == trigger_id and r["fired_at"].date() == today
        )

    async def was_delivery_processed(self, delivery_id: str) -> bool:
        """Check if a webhook delivery has already been processed."""
        return delivery_id in self._processed_deliveries

    async def record_delivery(self, delivery_id: str, trigger_id: str) -> None:  # noqa: ARG002
        """Record that a webhook delivery has been processed."""
        self._processed_deliveries.add(delivery_id)

    async def record_fire(
        self,
        trigger_id: str,
        pr_number: int | None,
        execution_id: str,
    ) -> None:
        """Record a trigger firing for tracking purposes."""
        self._fire_records.append(
            {
                "trigger_id": trigger_id,
                "pr_number": pr_number,
                "execution_id": execution_id,
                "fired_at": datetime.now(UTC),
            }
        )


# Singleton
_store: TriggerStore | None = None


def get_trigger_store() -> TriggerStore:
    """Get the global trigger store instance."""
    global _store
    if _store is None:
        _store = InMemoryTriggerStore()
    return _store


def set_trigger_store(store: TriggerStore) -> None:
    """Set the global trigger store instance (for DI/testing)."""
    global _store
    _store = store


def reset_trigger_store() -> None:
    """Reset the global trigger store (for testing)."""
    global _store
    _store = None
