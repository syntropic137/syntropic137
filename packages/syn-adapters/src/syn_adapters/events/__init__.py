"""Agent event storage and buffering.

This module provides:
- AgentEventStore: High-throughput event storage with batch inserts
- AgentEvent: Type-safe event model (SQLModel)
- EventBuffer: In-memory buffering for batch operations
- get_event_store: Factory for getting singleton store instance
- get_event_buffer: Factory for getting singleton buffer instance

See ADR-029: Simplified Event System
"""

from syn_adapters.events.buffer import EventBuffer, get_event_buffer
from syn_adapters.events.models import AgentEvent
from syn_adapters.events.schema import EventStoreSchema, SchemaValidationError
from syn_adapters.events.store import (
    AgentEventStore,
    EventValidationError,
    get_event_store,
)

__all__ = [
    "AgentEvent",
    "AgentEventStore",
    "EventBuffer",
    "EventStoreSchema",
    "EventValidationError",
    "SchemaValidationError",
    "get_event_buffer",
    "get_event_store",
]
