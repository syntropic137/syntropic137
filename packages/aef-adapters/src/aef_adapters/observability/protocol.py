"""Observability protocol definitions.

DEPRECATED: This module is being replaced by aef_adapters.events.
Kept for backwards compatibility during migration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class ObservationType(str, Enum):
    """Types of observations that can be recorded."""

    # Session lifecycle
    SESSION_STARTED = "session_started"
    SESSION_COMPLETED = "session_completed"
    SESSION_ERROR = "session_error"

    # Execution lifecycle
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_ERROR = "execution_error"

    # Tool usage
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"

    # Token usage
    TOKEN_USAGE = "token_usage"


@dataclass
class ObservationContext:
    """Context for observations."""

    session_id: str
    execution_id: str | None = None
    phase_id: str | None = None
    workflow_id: str | None = None
    workspace_id: str | None = None
    workspace_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ObservabilityPort:
    """Interface for observability adapters.

    DEPRECATED: Use AgentEventStore instead for new code.
    """

    async def record(
        self,
        observation_type: ObservationType,
        context: ObservationContext,
        data: dict[str, Any] | None = None,
    ) -> str:
        """Record an observation. Returns observation ID."""
        raise NotImplementedError

    async def record_tool_started(
        self,
        context: ObservationContext,
        tool_name: str,
        tool_input: dict[str, Any] | None = None,
        tool_use_id: str | None = None,
    ) -> str:
        """Record tool started. Returns operation ID."""
        raise NotImplementedError

    async def record_tool_completed(
        self,
        context: ObservationContext,
        operation_id: str,
        success: bool,
        duration_ms: int | None = None,
        output_preview: str | None = None,
        error: str | None = None,
        tool_name: str | None = None,  # Added for correlation
    ) -> None:
        """Record tool completed."""
        raise NotImplementedError

    async def record_token_usage(
        self,
        context: ObservationContext,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> None:
        """Record token usage."""
        raise NotImplementedError

    async def flush(self) -> None:
        """Flush any buffered observations."""
        pass


class NullObservability(ObservabilityPort):
    """Null implementation that logs but doesn't store.

    Use for tests or when observability storage is not available.
    """

    async def record(
        self,
        observation_type: ObservationType,
        context: ObservationContext,
        data: dict[str, Any] | None = None,
    ) -> str:
        """Record an observation (logs only)."""
        obs_id = str(uuid4())
        logger.debug(
            "NullObservability.record: %s session=%s data=%s",
            observation_type.value,
            context.session_id,
            data,
        )
        return obs_id

    async def record_tool_started(
        self,
        context: ObservationContext,
        tool_name: str,
        tool_input: dict[str, Any] | None = None,  # noqa: ARG002
        tool_use_id: str | None = None,  # noqa: ARG002
    ) -> str:
        """Record tool started (logs only)."""
        operation_id = str(uuid4())
        logger.debug(
            "NullObservability.tool_started: %s session=%s",
            tool_name,
            context.session_id,
        )
        return operation_id

    async def record_tool_completed(
        self,
        context: ObservationContext,  # noqa: ARG002
        operation_id: str,
        success: bool,
        duration_ms: int | None = None,  # noqa: ARG002
        output_preview: str | None = None,  # noqa: ARG002
        error: str | None = None,  # noqa: ARG002
        tool_name: str | None = None,
    ) -> None:
        """Record tool completed (logs only)."""
        logger.debug(
            "NullObservability.tool_completed: op=%s tool=%s success=%s",
            operation_id,
            tool_name,
            success,
        )

    async def record_token_usage(
        self,
        context: ObservationContext,  # noqa: ARG002
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,  # noqa: ARG002
        cache_read_tokens: int = 0,  # noqa: ARG002
    ) -> None:
        """Record token usage (logs only)."""
        logger.debug(
            "NullObservability.token_usage: in=%d out=%d",
            input_tokens,
            output_tokens,
        )

    async def flush(self) -> None:
        """No-op flush."""
        pass
