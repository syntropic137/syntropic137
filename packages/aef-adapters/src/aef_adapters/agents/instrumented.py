"""Instrumented agent wrapper with hook integration.

This module provides the InstrumentedAgent class that wraps any AgentProtocol
implementation and emits hook events for observability.

Example:
    from aef_adapters.agents import MockAgent
    from aef_adapters.agents.instrumented import InstrumentedAgent
    from aef_adapters.hooks import get_hook_client, ValidatorRegistry

    # Create instrumented agent
    async with get_hook_client() as hook_client:
        agent = InstrumentedAgent(
            agent=MockAgent(),
            hook_client=hook_client,
            validators=ValidatorRegistry(),
        )

        # Set session context
        agent.set_session_context("session-123", workflow_id="wf-456")

        # Use as normal - events are emitted automatically
        response = await agent.complete(messages, config)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentic_hooks import EventType, HookEvent

from aef_adapters.agents.session_context import SessionContext
from aef_adapters.hooks import AEFHookClient, ValidationResult, ValidatorRegistry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from aef_adapters.agents.protocol import (
        AgentConfig,
        AgentMessage,
        AgentProtocol,
        AgentProvider,
        AgentResponse,
    )


@dataclass
class InstrumentedAgent:
    """Agent wrapper with hook instrumentation.

    Wraps any AgentProtocol implementation and emits hook events
    for observability. Supports:
    - Pre/post request hooks for token tracking
    - Tool validation via ValidatorRegistry
    - Session context for event correlation

    Attributes:
        agent: The underlying agent implementation.
        hook_client: Client for emitting hook events.
        validators: Optional validator registry for tool validation.
    """

    agent: AgentProtocol
    hook_client: AEFHookClient
    validators: ValidatorRegistry | None = None

    _session_context: SessionContext | None = field(default=None, init=False)

    @property
    def provider(self) -> AgentProvider:
        """Get the agent provider type."""
        return self.agent.provider

    @property
    def is_available(self) -> bool:
        """Check if the agent is available."""
        return self.agent.is_available

    def set_session_context(
        self,
        session_id: str,
        workflow_id: str | None = None,
        phase_id: str | None = None,
        milestone_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set context for all emitted events.

        Args:
            session_id: Unique session identifier.
            workflow_id: Optional workflow identifier.
            phase_id: Optional phase identifier.
            milestone_id: Optional milestone identifier.
            metadata: Optional additional metadata.
        """
        self._session_context = SessionContext(
            session_id=session_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            milestone_id=milestone_id,
            metadata=metadata,
        )

    def clear_session_context(self) -> None:
        """Clear the session context."""
        self._session_context = None

    async def complete(
        self,
        messages: Sequence[AgentMessage],
        config: AgentConfig,
    ) -> AgentResponse:
        """Execute completion with instrumentation.

        Emits AGENT_REQUEST_STARTED before the request and
        AGENT_REQUEST_COMPLETED after with token metrics.

        Args:
            messages: Conversation history.
            config: Request configuration.

        Returns:
            Agent response with content and metrics.
        """
        ctx = self._session_context
        session_id = ctx.session_id if ctx else "unknown"

        # Pre-request hook
        await self.hook_client.emit(
            HookEvent(
                event_type=EventType.AGENT_REQUEST_STARTED,
                session_id=session_id,
                workflow_id=ctx.workflow_id if ctx else None,
                phase_id=ctx.phase_id if ctx else None,
                milestone_id=ctx.milestone_id if ctx else None,
                data={
                    "message_count": len(messages),
                    "model": config.model,
                    "max_tokens": config.max_tokens,
                    "temperature": config.temperature,
                    "provider": self.agent.provider.value,
                },
            )
        )

        start_time = time.monotonic()
        response = await self.agent.complete(list(messages), config)
        duration = time.monotonic() - start_time

        # Post-request hook
        await self.hook_client.emit(
            HookEvent(
                event_type=EventType.AGENT_REQUEST_COMPLETED,
                session_id=session_id,
                workflow_id=ctx.workflow_id if ctx else None,
                phase_id=ctx.phase_id if ctx else None,
                milestone_id=ctx.milestone_id if ctx else None,
                data={
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "total_tokens": response.total_tokens,
                    "duration_seconds": round(duration, 3),
                    "model": response.model,
                    "stop_reason": response.stop_reason,
                    "cost_estimate_usd": response.cost_estimate,
                    "provider": self.agent.provider.value,
                },
            )
        )

        return response

    async def stream(
        self,
        messages: Sequence[AgentMessage],
        config: AgentConfig,
    ) -> AsyncIterator[str]:
        """Stream a response with instrumentation.

        Note: Token counts may not be available during streaming.

        Args:
            messages: Conversation history.
            config: Request configuration.

        Yields:
            Response content chunks.
        """
        ctx = self._session_context
        session_id = ctx.session_id if ctx else "unknown"

        # Pre-request hook
        await self.hook_client.emit(
            HookEvent(
                event_type=EventType.AGENT_REQUEST_STARTED,
                session_id=session_id,
                workflow_id=ctx.workflow_id if ctx else None,
                phase_id=ctx.phase_id if ctx else None,
                data={
                    "message_count": len(messages),
                    "model": config.model,
                    "streaming": True,
                    "provider": self.agent.provider.value,
                },
            )
        )

        start_time = time.monotonic()
        chunk_count = 0
        total_content_length = 0

        async for chunk in self.agent.stream(list(messages), config):
            chunk_count += 1
            total_content_length += len(chunk)
            yield chunk

        duration = time.monotonic() - start_time

        # Post-request hook (limited metrics for streaming)
        await self.hook_client.emit(
            HookEvent(
                event_type=EventType.AGENT_REQUEST_COMPLETED,
                session_id=session_id,
                workflow_id=ctx.workflow_id if ctx else None,
                phase_id=ctx.phase_id if ctx else None,
                data={
                    "duration_seconds": round(duration, 3),
                    "streaming": True,
                    "chunk_count": chunk_count,
                    "content_length": total_content_length,
                    "provider": self.agent.provider.value,
                },
            )
        )

    async def validate_tool_use(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> ValidationResult:
        """Validate a tool use request.

        Runs validators and emits appropriate hook events.

        Args:
            tool_name: Name of the tool (e.g., 'Bash', 'Write').
            tool_input: Tool input parameters.

        Returns:
            ValidationResult indicating if the tool use is safe.
        """
        ctx = self._session_context
        session_id = ctx.session_id if ctx else "unknown"

        # Emit tool execution started
        await self.hook_client.emit(
            HookEvent(
                event_type=EventType.TOOL_EXECUTION_STARTED,
                session_id=session_id,
                workflow_id=ctx.workflow_id if ctx else None,
                phase_id=ctx.phase_id if ctx else None,
                data={
                    "tool_name": tool_name,
                    "tool_input_keys": list(tool_input.keys()),
                },
            )
        )

        # Run validators if available
        if self.validators is not None:
            context = ctx.to_dict() if ctx else None
            result = self.validators.validate(tool_name, tool_input, context)

            if not result.safe:
                # Tool blocked - emit event
                await self.hook_client.emit(
                    HookEvent(
                        event_type=EventType.TOOL_BLOCKED,
                        session_id=session_id,
                        workflow_id=ctx.workflow_id if ctx else None,
                        phase_id=ctx.phase_id if ctx else None,
                        data={
                            "tool_name": tool_name,
                            "reason": result.reason,
                            "validator": result.validator_name,
                            "metadata": result.metadata,
                        },
                    )
                )

            return result

        # No validators - allow by default
        return ValidationResult(safe=True)

    async def emit_tool_completed(
        self,
        tool_name: str,
        success: bool,
        duration_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Emit tool execution completed event.

        Call this after a tool completes to track execution metrics.

        Args:
            tool_name: Name of the tool.
            success: Whether the tool succeeded.
            duration_seconds: How long the tool took.
            metadata: Additional metadata.
        """
        ctx = self._session_context
        session_id = ctx.session_id if ctx else "unknown"

        data: dict[str, Any] = {
            "tool_name": tool_name,
            "success": success,
        }
        if duration_seconds is not None:
            data["duration_seconds"] = round(duration_seconds, 3)
        if metadata is not None:
            data.update(metadata)

        await self.hook_client.emit(
            HookEvent(
                event_type=EventType.TOOL_EXECUTION_COMPLETED,
                session_id=session_id,
                workflow_id=ctx.workflow_id if ctx else None,
                phase_id=ctx.phase_id if ctx else None,
                data=data,
            )
        )
