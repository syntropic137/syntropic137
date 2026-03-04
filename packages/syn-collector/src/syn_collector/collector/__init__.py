"""Event collector service components.

This module provides:
- FastAPI service for receiving batched events
- Deduplication filter for preventing duplicate events
- Observability store for persisting to TimescaleDB
"""

from syn_collector.collector.dedup import DeduplicationFilter
from syn_collector.collector.service import create_app
from syn_collector.collector.store import (
    InMemoryObservabilityStore,
    ObservabilityStoreProtocol,
    TimescaleDBObservabilityStore,
)

__all__ = [
    "DeduplicationFilter",
    "InMemoryObservabilityStore",
    "ObservabilityStoreProtocol",
    "TimescaleDBObservabilityStore",
    "create_app",
]
