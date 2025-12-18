"""Agent event storage and buffering.

This module provides:
- AgentEventStore: High-throughput event storage with batch inserts
- EventBuffer: In-memory buffering for batch operations
- get_event_store: Factory for getting singleton store instance
"""

from aef_adapters.events.buffer import EventBuffer
from aef_adapters.events.store import AgentEventStore, get_event_store

__all__ = [
    "AgentEventStore",
    "EventBuffer",
    "get_event_store",
]
