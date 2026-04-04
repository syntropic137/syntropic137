"""Persistent TriggerQueryStore backed by ProjectionStoreProtocol.

Reads from the same projection tables that TriggerQueryProjection writes to.
All write methods are no-ops — writes come exclusively from the projection
processing domain events.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from syn_domain.contexts.github._shared.trigger_query_store import (
    TriggerQueryStore,
    _IndexedTrigger,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import (
    TriggerConfig,
)

logger = logging.getLogger(__name__)

NS_TRIGGER_INDEX = "trigger_index"
NS_FIRE_RECORDS = "trigger_fire_records"
NS_DELIVERIES = "trigger_deliveries"


def _build_optional_filters(**kwargs: str | None) -> dict[str, Any] | None:
    """Build a filters dict from non-None keyword arguments, or None if empty."""
    filters = {k: v for k, v in kwargs.items() if v is not None}
    return filters or None


def _parse_trigger_config(config_data: Any) -> TriggerConfig:
    """Parse a TriggerConfig from raw projection store data."""
    if isinstance(config_data, dict):
        return TriggerConfig(**config_data) if config_data else TriggerConfig()
    return config_data


def _latest_fired_at(records: list[dict[str, Any]]) -> datetime | None:
    """Return the latest fired_at timestamp from fire records, or None."""
    if not records:
        return None
    latest = max(records, key=lambda r: r.get("fired_at", ""))
    return datetime.fromisoformat(latest["fired_at"])


class PersistentTriggerQueryStore(TriggerQueryStore):
    """TriggerQueryStore backed by PostgreSQL via ProjectionStoreProtocol.

    Reads from projection tables populated by TriggerQueryProjection.
    Write methods are no-ops since all mutations flow through events.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    def _to_indexed_trigger(self, data: dict[str, Any]) -> _IndexedTrigger:
        """Reconstruct an _IndexedTrigger from projection store data."""
        trigger = _IndexedTrigger(
            trigger_id=data.get("trigger_id", ""),
            name=data.get("name", ""),
            event=data.get("event", ""),
            repository=data.get("repository", ""),
            workflow_id=data.get("workflow_id", ""),
            conditions=data.get("conditions", []),
            input_mapping=data.get("input_mapping", {}),
            config=_parse_trigger_config(data.get("config", {})),
            installation_id=data.get("installation_id", ""),
            created_by=data.get("created_by", ""),
            status=data.get("status", "active"),
        )
        trigger.fire_count = data.get("fire_count", 0)
        raw_created_at = data.get("created_at")
        if isinstance(raw_created_at, str):
            trigger.created_at = datetime.fromisoformat(raw_created_at)
        raw_last_fired = data.get("last_fired_at")
        if isinstance(raw_last_fired, str):
            trigger.last_fired_at = datetime.fromisoformat(raw_last_fired)
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
        filters = _build_optional_filters(repository=repository, status=status)
        results = await self._store.query(
            NS_TRIGGER_INDEX,
            filters=filters,
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
        return _latest_fired_at(records)

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
        return _latest_fired_at(records)

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
        created_at: datetime | None = None,
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
