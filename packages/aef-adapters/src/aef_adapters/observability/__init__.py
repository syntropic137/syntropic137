"""Observability adapters for agent telemetry.

This module provides implementations for observability backends and
OTel configuration utilities.

Exports:
    OTel-First (recommended):
    - AEFSemanticConventions: Resource attribute constants
    - create_phase_otel_config: Factory for phase-level OTelConfig

    Legacy (deprecated):
    - TimescaleObservability: Production adapter writing to TimescaleDB
    - get_observability: Factory function for getting the adapter
"""

from aef_adapters.observability.conventions import AEFSemanticConventions
from aef_adapters.observability.factory import get_observability
from aef_adapters.observability.otel_config import (
    create_phase_otel_config,
    get_collector_endpoint,
)
from aef_adapters.observability.timescale import TimescaleObservability

__all__ = [
    "AEFSemanticConventions",
    "TimescaleObservability",
    "create_phase_otel_config",
    "get_collector_endpoint",
    "get_observability",
]
