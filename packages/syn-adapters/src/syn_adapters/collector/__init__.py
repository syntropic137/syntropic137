"""Collector client for sending observability events.

This module provides a client for sending observation events (Pattern 2: Event Log + CQRS)
to the Collector service. These events are distinct from domain events (Pattern 1).

See: ADR-017, ADR-018
"""

from syn_adapters.collector.client import CollectorClient
from syn_adapters.collector.models import (
    BatchResponse,
    CollectorEvent,
    EventBatch,
    generate_event_id,
    generate_tool_event_id,
)

__all__ = [
    "BatchResponse",
    "CollectorClient",
    "CollectorEvent",
    "EventBatch",
    "generate_event_id",
    "generate_tool_event_id",
]
