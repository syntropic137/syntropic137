"""HTTP client for sending events to collector service.

This module provides:
- EventCollectorClient: Batched HTTP client with retry logic
"""

from syn_collector.client.http import EventCollectorClient

__all__ = [
    "EventCollectorClient",
]
