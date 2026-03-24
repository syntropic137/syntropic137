"""Event dispatch helpers for ProjectionManager.

Extracted from manager.py to reduce module complexity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_adapters.projections.manager_event_map import EVENT_HANDLERS, EventProvenance

if TYPE_CHECKING:
    from syn_adapters.projections.manager import ProjectionManager

logger = logging.getLogger(__name__)


async def process_event_envelope(
    mgr: ProjectionManager, envelope: Any
) -> EventProvenance:
    """Process an event envelope from the event store.

    This is the ONLY correct way to dispatch events to projections.
    Events MUST come through the event store subscription, ensuring
    proper event sourcing guarantees.

    Args:
        mgr: The projection manager instance.
        envelope: Event envelope from event store (has metadata, event).

    Returns:
        EventProvenance with stream/position info for tracking.

    Raises:
        ValueError: If envelope is not from event store.
    """
    # Validate provenance - ensures event came from event store
    # O(1) check, ~50ns overhead - NOT a performance concern
    provenance = EventProvenance.from_envelope(envelope)

    # Extract event data
    event = envelope.event
    if hasattr(event, "to_dict"):
        event_data = event.to_dict()
    elif hasattr(event, "model_dump"):
        event_data = event.model_dump()
    else:
        event_data = vars(event) if hasattr(event, "__dict__") else {}

    # Dispatch to handlers
    await dispatch_to_handlers(mgr, provenance.event_type, event_data)

    return provenance


async def dispatch_to_handlers(
    mgr: ProjectionManager, event_type: str, event_data: dict
) -> None:
    """Internal: Dispatch event data to projection handlers.

    DO NOT CALL DIRECTLY - use process_event_envelope() instead.
    """
    mgr._ensure_initialized()

    handlers = EVENT_HANDLERS.get(event_type, [])
    if not handlers:
        logger.debug("No handlers registered for event type: %s", event_type)

    for projection_name, method_name in handlers:
        projection = mgr._projections.get(projection_name)
        if projection:
            handler = getattr(projection, method_name, None)
            if handler:
                try:
                    await handler(event_data)
                except Exception as e:
                    logger.error(
                        "Error in projection handler",
                        extra={
                            "projection": projection_name,
                            "method": method_name,
                            "event_type": event_type,
                            "error": str(e),
                        },
                        exc_info=True,
                    )
