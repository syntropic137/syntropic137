"""Agentic workspace adapter - bridges agentic_isolation to Syn137.

This module provides thin wrappers that connect the agentic_isolation
library to Syn137's domain ports (IsolationBackendPort, EventStreamPort).

The heavy lifting is done by agentic_isolation in agentic-primitives.
Syn137 just orchestrates and captures observability.
"""

from syn_adapters.workspace_backends.agentic.adapter import (
    AgenticEventStreamAdapter,
    AgenticIsolationAdapter,
)

__all__ = [
    "AgenticEventStreamAdapter",
    "AgenticIsolationAdapter",
]
