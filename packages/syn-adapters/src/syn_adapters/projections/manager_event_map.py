"""Event provenance for the projection manager.

The hand-kept event-to-handler map that used to live here is gone (#2265):
the manager now delivers through ``handle_event`` on the adapters the
coordinator registers, so there is one routing, derived from the projections.

Refs: #504, #517
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope


@runtime_checkable
class Projection(Protocol):
    """Protocol for projections that can handle events."""

    @property
    def name(self) -> str:
        """Get the projection name."""
        ...


@dataclass(frozen=True, slots=True)
class EventProvenance:
    """Provenance metadata for events from event store."""

    stream_id: str
    global_nonce: int | None
    event_type: str

    @classmethod
    def from_envelope(cls, envelope: EventEnvelope[DomainEvent]) -> EventProvenance:
        """Extract provenance from an event store envelope."""
        metadata = getattr(envelope, "metadata", None)
        if metadata is None:
            raise ValueError("Event envelope missing metadata - not from event store")
        stream_id = getattr(metadata, "stream_id", None)
        global_nonce = getattr(metadata, "global_nonce", None)
        event = getattr(envelope, "event", None)
        if event is None:
            raise ValueError("Event envelope missing event")
        event_type = getattr(event, "event_type", None) or type(event).__name__
        return cls(
            stream_id=stream_id or "unknown",
            global_nonce=global_nonce,
            event_type=event_type,
        )
