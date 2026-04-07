"""Event dispatch helpers for ProjectionManager.

Extracted from manager.py to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.projections.manager_event_map import (
    EventProvenance,
    dispatch_to_handlers,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

    from syn_adapters.projections.manager import ProjectionManager

# Re-exported for consumers that import dispatch_to_handlers from here
__all__ = ["dispatch_to_handlers", "process_event_envelope"]


async def process_event_envelope(
    mgr: ProjectionManager, envelope: EventEnvelope[DomainEvent]
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

    # Extract event data — events may use to_dict() (legacy) or model_dump() (Pydantic)
    event = envelope.event
    to_dict = getattr(event, "to_dict", None)
    if to_dict is not None:
        event_data = to_dict()
    elif hasattr(event, "model_dump"):
        event_data = event.model_dump()
    else:
        event_data = vars(event) if hasattr(event, "__dict__") else {}

    # Dispatch to handlers
    await dispatch_to_handlers(mgr, provenance.event_type, event_data)

    return provenance
