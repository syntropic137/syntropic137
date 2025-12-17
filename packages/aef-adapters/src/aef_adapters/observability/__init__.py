"""Observability adapters for agent telemetry.

This module provides implementations of the ObservabilityPort protocol
for different backends.

Exports:
    - TimescaleObservability: Production adapter writing to TimescaleDB
    - get_observability: Factory function for getting the adapter
"""

from aef_adapters.observability.factory import get_observability
from aef_adapters.observability.timescale import TimescaleObservability

__all__ = [
    "TimescaleObservability",
    "get_observability",
]
