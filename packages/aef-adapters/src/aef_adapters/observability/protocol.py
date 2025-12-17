"""Legacy Observability Protocol (deprecated).

This module provides a local copy of the ObservabilityPort protocol
that was previously in agentic-primitives/agentic_observability.

DEPRECATED: New code should use OTel-first approach with:
- agentic_otel.OTelConfig
- agentic_otel.HookOTelEmitter
- AEFSemanticConventions

This protocol is kept for backward compatibility during migration.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

# Emit deprecation warning on import
warnings.warn(
    "aef_adapters.observability.protocol is deprecated. "
    "Use agentic_otel for OTel-first observability.",
    DeprecationWarning,
    stacklevel=2,
)


class ObservationType(Enum):
    """Types of agent observations (legacy)."""

    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOKEN_USAGE = "token_usage"
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    ERROR = "error"
    CUSTOM = "custom"
    PROGRESS = "progress"  # Generic progress update


@dataclass
class ObservationContext:
    """Context for an observation (legacy).

    Contains all the identifiers needed to correlate observations
    across sessions, executions, and workflows.
    """

    session_id: str
    execution_id: str | None = None
    phase_id: str | None = None
    workflow_id: str | None = None
    agent_id: str | None = None
    correlation_id: str | None = None
    workspace_path: str | None = None
    observation_id: str = field(default_factory=lambda: str(uuid4()))


@runtime_checkable
class ObservabilityPort(Protocol):
    """Protocol for observability adapters (legacy).

    DEPRECATED: Use OTel-first observability instead.
    """

    async def record(
        self,
        observation_type: ObservationType,
        context: ObservationContext,
        data: dict[str, Any],
    ) -> None:
        """Record a generic observation."""
        ...

    async def record_tool_started(
        self,
        context: ObservationContext,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> str:
        """Record a tool execution starting."""
        ...

    async def record_tool_completed(
        self,
        context: ObservationContext,
        operation_id: str,
        tool_name: str,
        success: bool,
        duration_ms: int,
        output_preview: str | None = None,
    ) -> None:
        """Record a tool execution completing."""
        ...

    async def record_token_usage(
        self,
        context: ObservationContext,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        model: str | None = None,
    ) -> None:
        """Record token usage."""
        ...

    async def flush(self) -> None:
        """Flush any buffered observations."""
        ...

    async def close(self) -> None:
        """Close the adapter."""
        ...


class NullObservability:
    """No-op observability adapter for testing (legacy).

    DEPRECATED: Use mocks or OTel-first observability instead.

    This adapter implements ObservabilityPort but discards all observations.
    Useful for unit tests that don't need observability.
    """

    async def record(
        self,
        observation_type: ObservationType,
        context: ObservationContext,
        data: dict[str, Any],
    ) -> None:
        """Discard observation."""

    async def record_tool_started(
        self,
        context: ObservationContext,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> str:
        """Return a dummy operation ID."""
        return "null-op-" + str(uuid4())[:8]

    async def record_tool_completed(
        self,
        context: ObservationContext,
        operation_id: str,
        tool_name: str,
        success: bool,
        duration_ms: int,
        output_preview: str | None = None,
    ) -> None:
        """Discard completion record."""

    async def record_token_usage(
        self,
        context: ObservationContext,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        model: str | None = None,
    ) -> None:
        """Discard token usage."""

    async def flush(self) -> None:
        """No-op flush."""

    async def close(self) -> None:
        """No-op close."""
