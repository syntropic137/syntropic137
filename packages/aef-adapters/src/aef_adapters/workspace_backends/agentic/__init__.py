"""Agentic workspace adapter - bridges agentic_isolation to AEF.

This module provides thin wrappers that connect the agentic_isolation
library to AEF's domain ports (IsolationBackendPort, EventStreamPort).

The heavy lifting is done by agentic_isolation in agentic-primitives.
AEF just orchestrates and captures observability.
"""

from aef_adapters.workspace_backends.agentic.adapter import (
    AgenticEventStreamAdapter,
    AgenticIsolationAdapter,
)

__all__ = [
    "AgenticEventStreamAdapter",
    "AgenticIsolationAdapter",
]
