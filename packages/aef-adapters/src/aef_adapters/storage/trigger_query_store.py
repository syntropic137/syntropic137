"""Persistent TriggerQueryStore backed by ProjectionStoreProtocol.

Reads from the same projection tables that TriggerQueryProjection writes to.
All write methods are no-ops — writes come exclusively from the projection
processing domain events.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from aef_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import (
    TriggerConfig,
)
from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
    TriggerQueryStore,
    _IndexedTrigger,
)

logger = logging.getLogger(__name__)

NS_TRIGGER_INDEX = "trigger_index"
NS_FIRE_RECORDS = "trigger_fire_records"
NS_DELIVERIES = "trigger_deliveries"


class PersistentTriggerQueryStore(TriggerQueryStore):
    """TriggerQueryStore backed by PostgreSQL via ProjectionStoreProtocol.

    Reads from projection tables populated by TriggerQueryProjection.
    Write methods are no-ops since all mutations flow through events.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    def _to_indexed_trigger(self, data: dict[str, Any]) -> _IndexedTrigger:
        """Reconstruct an _IndexedTrigger from projection store data."""
        config_data = data.get("config", {})
        if isinstance(config_data, dict):
            config = TriggerConfig(**config_data) if config_data else TriggerConfig()
        else:
            config = config_data

        trigger = _IndexedTrigger(
            trigger_id=data.get("trigger_id", ""),
            name=data.get("name", ""),
            event=data.get("event", ""),
            repository=data.get("repository", ""),
            workflow_id=data.get("workflow_id", ""),
            conditions=data.get("conditions", []),
            input_mapping=data.get("input_mapping", {}),
            config=config,
            installation_id=data.get("installation_id", ""),
            created_by=data.get("created_by", ""),
            status=data.get("status", "active"),
        )
        trigger.fire_count = data.get("fire_count", 0)
        return trigger

    # --- Read methods ---

    async def get(self, trigger_id: str) -> _IndexedTrigger | None:
        data = await self._store.get(NS_TRIGGER_INDEX, trigger_id)
        if data is None:
            return None
        return self._to_indexed_trigger(data)

    async def list_by_event_and_repo(self, event: str, repository: str) -> list[_IndexedTrigger]:
        results = await self._store.query(
            NS_TRIGGER_INDEX,
            filters={"event": event, "repository": repository, "status": "active"},
        )
        return [self._to_indexed_trigger(d) for d in results]

    async def list_all(
        self,
        repository: str | None = None,
        status: str | None = None,
    ) -> list[_IndexedTrigger]:
        filters: dict[str, Any] = {}
        if repository:
            filters["repository"] = repository
        if status:
            filters["status"] = status
        results = await self._store.query(
            NS_TRIGGER_INDEX,
            filters=filters if filters else None,
        )
        return [self._to_indexed_trigger(d) for d in results]

    async def get_fire_count(self, trigger_id: str, pr_number: int) -> int:
        records = await self._store.query(
            NS_FIRE_RECORDS,
            filters={"trigger_id": trigger_id, "pr_number": str(pr_number)},
        )
        return len(records)

    async def get_last_fired_at(self, trigger_id: str, pr_number: int) -> datetime | None:
        records = await self._store.query(
            NS_FIRE_RECORDS,
            filters={"trigger_id": trigger_id, "pr_number": str(pr_number)},
        )
        if not records:
            return None
        latest = max(records, key=lambda r: r.get("fired_at", ""))
        return datetime.fromisoformat(latest["fired_at"])

    async def get_daily_fire_count(self, trigger_id: str) -> int:
        records = await self._store.query(
            NS_FIRE_RECORDS,
            filters={"trigger_id": trigger_id},
        )
        today = datetime.now(UTC).date()
        return sum(
            1 for r in records if datetime.fromisoformat(r.get("fired_at", "")).date() == today
        )

    async def get_last_any_fired_at(
        self, pr_number: int, exclude_trigger_id: str | None = None
    ) -> datetime | None:
        records = await self._store.query(
            NS_FIRE_RECORDS,
            filters={"pr_number": str(pr_number)},
        )
        if exclude_trigger_id:
            records = [r for r in records if r.get("trigger_id") != exclude_trigger_id]
        if not records:
            return None
        latest = max(records, key=lambda r: r.get("fired_at", ""))
        return datetime.fromisoformat(latest["fired_at"])

    async def was_delivery_processed(self, delivery_id: str) -> bool:
        data = await self._store.get(NS_DELIVERIES, delivery_id)
        return data is not None

    # --- Write methods (no-ops, writes come from projection) ---

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
        pass  # Writes come from TriggerQueryProjection

    async def update_status(self, trigger_id: str, status: str) -> None:
        pass  # Writes come from TriggerQueryProjection

    async def record_delivery(self, delivery_id: str, trigger_id: str) -> None:
        pass  # Writes come from TriggerQueryProjection

    async def record_fire(
        self,
        trigger_id: str,
        pr_number: int | None,
        execution_id: str,
    ) -> None:
        pass  # Writes come from TriggerQueryProjection
