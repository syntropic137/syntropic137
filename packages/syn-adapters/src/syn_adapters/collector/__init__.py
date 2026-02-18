"""Collector client for sending observability events.

This module provides a client for sending observation events (Pattern 2: Event Log + CQRS)
to the Collector service. These events are distinct from domain events (Pattern 1).

See: ADR-017, ADR-018
"""

from syn_adapters.collector.client import CollectorClient

__all__ = ["CollectorClient"]
