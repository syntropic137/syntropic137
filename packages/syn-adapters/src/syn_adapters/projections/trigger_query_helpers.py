"""Event handler helpers for TriggerQueryProjection.

Extracted from trigger_query_projection.py to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from event_sourcing import EventEnvelope

    from syn_adapters.projections.trigger_query_projection import TriggerQueryProjection

NS_TRIGGER_INDEX = "trigger_index"
NS_FIRE_RECORDS = "trigger_fire_records"
NS_DELIVERIES = "trigger_deliveries"


async def dispatch_trigger_event(
    proj: TriggerQueryProjection, event_type: str, envelope: EventEnvelope[Any]
) -> None:
    """Route an event to the appropriate handler."""
    event_data = envelope.event.model_dump()
    if event_type == "github.TriggerRegistered":
        await on_trigger_registered(proj, event_data)
    elif event_type == "github.TriggerFired":
        await on_trigger_fired(proj, event_data, envelope)
    elif event_type in proj._STATUS_UPDATES:
        await update_trigger_status(proj, event_data, proj._STATUS_UPDATES[event_type])


async def on_trigger_registered(proj: TriggerQueryProjection, data: dict[str, Any]) -> None:
    """Handle TriggerRegistered event."""
    trigger_id = data.get("trigger_id", "")
    await proj._store.save(
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
        },
    )


async def update_trigger_status(
    proj: TriggerQueryProjection, data: dict[str, Any], status: str
) -> None:
    """Update a trigger's status in the index."""
    trigger_id = data.get("trigger_id", "")
    existing = await proj._store.get(NS_TRIGGER_INDEX, trigger_id)
    if existing:
        existing["status"] = status
        await proj._store.save(NS_TRIGGER_INDEX, trigger_id, existing)


async def on_trigger_fired(
    proj: TriggerQueryProjection, data: dict[str, Any], envelope: EventEnvelope[Any]
) -> None:
    """Handle TriggerFired event."""
    trigger_id = data.get("trigger_id", "")
    execution_id = data.get("execution_id", "")
    delivery_id = data.get("webhook_delivery_id", "")
    pr_number = data.get("pr_number")
    fired_at = envelope.metadata.timestamp.isoformat()

    await record_fire(proj, trigger_id, execution_id, pr_number, fired_at)
    await record_delivery(proj, delivery_id, trigger_id, fired_at)
    await increment_fire_count(proj, trigger_id)


async def record_fire(
    proj: TriggerQueryProjection,
    trigger_id: str,
    execution_id: str,
    pr_number: Any,
    fired_at: str,
) -> None:
    """Record a fire event in the fire records namespace."""
    fire_key = f"{trigger_id}#{execution_id}"
    await proj._store.save(
        NS_FIRE_RECORDS,
        fire_key,
        {
            "trigger_id": trigger_id,
            "execution_id": execution_id,
            "pr_number": str(pr_number) if pr_number is not None else "",
            "fired_at": fired_at,
        },
    )


async def record_delivery(
    proj: TriggerQueryProjection,
    delivery_id: str,
    trigger_id: str,
    fired_at: str,
) -> None:
    """Record delivery for idempotency (no-op if delivery_id is empty)."""
    if not delivery_id:
        return
    await proj._store.save(
        NS_DELIVERIES,
        delivery_id,
        {
            "delivery_id": delivery_id,
            "trigger_id": trigger_id,
            "processed_at": fired_at,
        },
    )


async def increment_fire_count(proj: TriggerQueryProjection, trigger_id: str) -> None:
    """Increment the fire count on the trigger index entry."""
    existing = await proj._store.get(NS_TRIGGER_INDEX, trigger_id)
    if existing:
        existing["fire_count"] = existing.get("fire_count", 0) + 1
        await proj._store.save(NS_TRIGGER_INDEX, trigger_id, existing)
