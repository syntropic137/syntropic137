"""Trigger Query Projection.

Subscribes to trigger lifecycle events and populates the query store
tables used by handlers and safety guards.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
Writes to 3 projection namespaces: trigger_index, trigger_fire_records,
trigger_deliveries.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from event_sourcing import (
    CheckpointedProjection,
    EventEnvelope,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)

logger = logging.getLogger(__name__)

_SUBSCRIBED_EVENTS = {
    "github.TriggerRegistered",
    "github.TriggerPaused",
    "github.TriggerResumed",
    "github.TriggerDeleted",
    "github.TriggerFired",
}

NS_TRIGGER_INDEX = "trigger_index"
NS_FIRE_RECORDS = "trigger_fire_records"
NS_DELIVERIES = "trigger_deliveries"


class TriggerQueryProjection(CheckpointedProjection):
    """Builds the trigger query store from domain events.

    This projection:
    1. Subscribes to all trigger lifecycle events
    2. Maintains trigger_index for fast lookups
    3. Records fire history for safety guards
    4. Tracks delivery IDs for idempotency
    """

    PROJECTION_NAME = "trigger_query"
    VERSION = 1

    def __init__(self, store: Any) -> None:
        self._store = store

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return _SUBSCRIBED_EVENTS

    _EVENT_DISPATCH: ClassVar[dict[str, str]] = {
        "github.TriggerRegistered": "_on_trigger_registered",
        "github.TriggerPaused": "_on_trigger_paused",
        "github.TriggerResumed": "_on_trigger_resumed",
        "github.TriggerDeleted": "_on_trigger_deleted",
    }

    async def _dispatch_event(
        self, event_type: str, event_data: dict[str, Any], envelope: EventEnvelope[Any]
    ) -> None:
        """Route an event to the appropriate handler method."""
        if event_type == "github.TriggerFired":
            await self._on_trigger_fired(event_data, envelope)
            return
        handler_name = self._EVENT_DISPATCH.get(event_type)
        if handler_name is not None:
            handler = getattr(self, handler_name)
            await handler(event_data, envelope)

    async def handle_event(
        self,
        envelope: EventEnvelope[Any],
        checkpoint_store: ProjectionCheckpointStore,
    ) -> ProjectionResult:
        event_type = envelope.event.event_type
        event_data = envelope.event.model_dump()
        global_nonce = envelope.metadata.global_nonce or 0

        try:
            await self._dispatch_event(event_type, event_data, envelope)

            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=global_nonce,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS

        except Exception:
            logger.exception(
                "Error handling trigger event",
                extra={"event_type": event_type},
            )
            return ProjectionResult.FAILURE

    async def clear_all_data(self) -> None:
        """Clear all projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(NS_TRIGGER_INDEX)
            await self._store.delete_all(NS_FIRE_RECORDS)
            await self._store.delete_all(NS_DELIVERIES)

    async def _on_trigger_registered(
        self, data: dict[str, Any], envelope: EventEnvelope[Any]
    ) -> None:
        trigger_id = data.get("trigger_id", "")
        await self._store.save(
            NS_TRIGGER_INDEX,
            trigger_id,
            {
                "trigger_id": trigger_id,
                "name": data.get("name", ""),
                "event": data.get("event", ""),
                "repository": data.get("repository", ""),
                "workflow_id": data.get("workflow_id", ""),
                "conditions": list(data.get("conditions", ())),
                "input_mapping": data.get("input_mapping", {}),
                "config": data.get("config", {}),
                "installation_id": data.get("installation_id", ""),
                "created_by": data.get("created_by", ""),
                "status": "active",
                "fire_count": 0,
                "created_at": envelope.metadata.timestamp.isoformat(),
            },
        )

    async def _on_trigger_paused(self, data: dict[str, Any], _envelope: EventEnvelope[Any]) -> None:
        trigger_id = data.get("trigger_id", "")
        existing = await self._store.get(NS_TRIGGER_INDEX, trigger_id)
        if existing:
            existing["status"] = "paused"
            await self._store.save(NS_TRIGGER_INDEX, trigger_id, existing)

    async def _on_trigger_resumed(
        self, data: dict[str, Any], _envelope: EventEnvelope[Any]
    ) -> None:
        trigger_id = data.get("trigger_id", "")
        existing = await self._store.get(NS_TRIGGER_INDEX, trigger_id)
        if existing:
            existing["status"] = "active"
            await self._store.save(NS_TRIGGER_INDEX, trigger_id, existing)

    async def _on_trigger_deleted(
        self, data: dict[str, Any], _envelope: EventEnvelope[Any]
    ) -> None:
        trigger_id = data.get("trigger_id", "")
        existing = await self._store.get(NS_TRIGGER_INDEX, trigger_id)
        if existing:
            existing["status"] = "deleted"
            await self._store.save(NS_TRIGGER_INDEX, trigger_id, existing)

    async def _on_trigger_fired(self, data: dict[str, Any], envelope: EventEnvelope[Any]) -> None:
        trigger_id = data.get("trigger_id", "")
        execution_id = data.get("execution_id", "")
        delivery_id = data.get("webhook_delivery_id", "")
        pr_number = data.get("pr_number")
        fired_at = envelope.metadata.timestamp.isoformat()

        # Record fire
        fire_key = f"{trigger_id}#{execution_id}"
        await self._store.save(
            NS_FIRE_RECORDS,
            fire_key,
            {
                "trigger_id": trigger_id,
                "execution_id": execution_id,
                "pr_number": str(pr_number) if pr_number is not None else "",
                "fired_at": fired_at,
            },
        )

        # Record delivery for idempotency
        if delivery_id:
            await self._store.save(
                NS_DELIVERIES,
                delivery_id,
                {
                    "delivery_id": delivery_id,
                    "trigger_id": trigger_id,
                    "processed_at": fired_at,
                },
            )

        # Increment fire count and update last_fired_at on trigger index
        existing = await self._store.get(NS_TRIGGER_INDEX, trigger_id)
        if existing:
            existing["fire_count"] = existing.get("fire_count", 0) + 1
            existing["last_fired_at"] = fired_at
            await self._store.save(NS_TRIGGER_INDEX, trigger_id, existing)
