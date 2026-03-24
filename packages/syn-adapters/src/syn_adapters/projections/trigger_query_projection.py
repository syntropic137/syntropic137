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
from typing import Any

from event_sourcing import (
    CheckpointedProjection,
    EventEnvelope,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)

from syn_adapters.projections.trigger_query_helpers import (
    NS_DELIVERIES,
    NS_FIRE_RECORDS,
    NS_TRIGGER_INDEX,
    dispatch_trigger_event,
)

logger = logging.getLogger(__name__)

_SUBSCRIBED_EVENTS = {
    "github.TriggerRegistered",
    "github.TriggerPaused",
    "github.TriggerResumed",
    "github.TriggerDeleted",
    "github.TriggerFired",
}


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

    # Status-update events: event_type -> new status value
    _STATUS_UPDATES: dict[str, str] = {
        "github.TriggerPaused": "paused",
        "github.TriggerResumed": "active",
        "github.TriggerDeleted": "deleted",
    }

    def __init__(self, store: Any) -> None:
        self._store = store

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return _SUBSCRIBED_EVENTS

    async def handle_event(
        self,
        envelope: EventEnvelope[Any],
        checkpoint_store: ProjectionCheckpointStore,
    ) -> ProjectionResult:
        event_type = envelope.event.event_type

        try:
            await self._dispatch_event(event_type, envelope)
            await self._save_checkpoint(checkpoint_store, envelope)
            return ProjectionResult.SUCCESS
        except Exception:
            logger.exception(
                "Error handling trigger event",
                extra={"event_type": event_type},
            )
            return ProjectionResult.FAILURE

    async def _dispatch_event(
        self, event_type: str, envelope: EventEnvelope[Any]
    ) -> None:
        """Route an event to the appropriate handler."""
        await dispatch_trigger_event(self, event_type, envelope)

    async def _save_checkpoint(
        self,
        checkpoint_store: ProjectionCheckpointStore,
        envelope: EventEnvelope[Any],
    ) -> None:
        """Persist the projection checkpoint after successful handling."""
        global_nonce = envelope.metadata.global_nonce or 0
        await checkpoint_store.save_checkpoint(
            ProjectionCheckpoint(
                projection_name=self.PROJECTION_NAME,
                global_position=global_nonce,
                updated_at=datetime.now(UTC),
                version=self.VERSION,
            )
        )

    async def clear_all_data(self) -> None:
        """Clear all projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(NS_TRIGGER_INDEX)
            await self._store.delete_all(NS_FIRE_RECORDS)
            await self._store.delete_all(NS_DELIVERIES)

    async def _on_trigger_registered(self, data: dict[str, Any]) -> None:
        from syn_adapters.projections.trigger_query_helpers import on_trigger_registered
        await on_trigger_registered(self, data)

    async def _update_trigger_status(self, data: dict[str, Any], status: str) -> None:
        """Update a trigger's status in the index."""
        from syn_adapters.projections.trigger_query_helpers import update_trigger_status
        await update_trigger_status(self, data, status)

    async def _on_trigger_fired(self, data: dict[str, Any], envelope: EventEnvelope[Any]) -> None:
        from syn_adapters.projections.trigger_query_helpers import on_trigger_fired
        await on_trigger_fired(self, data, envelope)

    async def _record_fire(
        self, trigger_id: str, execution_id: str, pr_number: Any, fired_at: str
    ) -> None:
        """Record a fire event in the fire records namespace."""
        from syn_adapters.projections.trigger_query_helpers import record_fire
        await record_fire(self, trigger_id, execution_id, pr_number, fired_at)

    async def _record_delivery(
        self, delivery_id: str, trigger_id: str, fired_at: str
    ) -> None:
        """Record delivery for idempotency (no-op if delivery_id is empty)."""
        from syn_adapters.projections.trigger_query_helpers import record_delivery
        await record_delivery(self, delivery_id, trigger_id, fired_at)

    async def _increment_fire_count(self, trigger_id: str) -> None:
        """Increment the fire count on the trigger index entry."""
        from syn_adapters.projections.trigger_query_helpers import increment_fire_count
        await increment_fire_count(self, trigger_id)
