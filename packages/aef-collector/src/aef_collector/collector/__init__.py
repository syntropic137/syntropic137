"""Event collector service components.

This module provides:
- FastAPI service for receiving batched events
- Deduplication filter for preventing duplicate events
- Event store writer for persisting to gRPC event store
"""

from aef_collector.collector.dedup import DeduplicationFilter
from aef_collector.collector.service import app, create_app
from aef_collector.collector.store import EventStoreWriter, InMemoryEventStore

__all__ = [
    "DeduplicationFilter",
    "EventStoreWriter",
    "InMemoryEventStore",
    "app",
    "create_app",
]
