"""Event types and ID generation for Syn137 collector.

This module provides:
- Event type definitions (Pydantic models)
- Deterministic event ID generation for deduplication
"""

from syn_collector.events.ids import (
    generate_event_id,
    generate_token_event_id,
    generate_tool_event_id,
)
from syn_collector.events.types import (
    BatchResponse,
    CollectedEvent,
    EventBatch,
    EventType,
)

__all__ = [
    "BatchResponse",
    "CollectedEvent",
    "EventBatch",
    "EventType",
    "generate_event_id",
    "generate_token_event_id",
    "generate_tool_event_id",
]
