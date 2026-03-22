"""ObservabilityCollector — Lane 2 telemetry recording (ISS-196).

Encapsulates all observability recording calls. Never touches domain
aggregates — purely writes to the observability backend.

Extracted from EventStreamProcessor to enforce two-lane separation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,
)
from syn_shared.events import SESSION_SUMMARY

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
    )

logger = logging.getLogger(__name__)


class ObservabilityCollector:
    """Lane 2: Records telemetry to observability backend.

    Never touches domain aggregates. All methods are no-op
    when the writer is None (e.g., in tests or local dev).
    """

    def __init__(
        self,
        writer: ObservabilityRecorder | None,
        session_id: str,
        execution_id: str,
        phase_id: str,
        workspace_id: str | None,
        agent_model: str,
    ) -> None:
        self._writer = writer
        self._session_id = session_id
        self._execution_id = execution_id
        self._phase_id = phase_id
        self._workspace_id = workspace_id
        self._agent_model = agent_model

    @property
    def has_writer(self) -> bool:
        """Whether this collector has an active writer."""
        return self._writer is not None

    async def record_hook_event(self, enriched: dict[str, Any]) -> None:
        """Record an enriched hook event to observability."""
        if self._writer is None:
            return

        hook_data = {
            **(enriched.get("context") or {}),
            **(enriched.get("metadata") or {}),
        }
        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=enriched.get("event_type", "unknown"),
            data=hook_data,
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )

    async def record_token_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int = 0,
        cache_read: int = 0,
    ) -> None:
        """Record token usage observation."""
        if self._writer is None:
            return

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=ObservationType.TOKEN_USAGE,
            data={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_tokens": cache_creation,
                "cache_read_tokens": cache_read,
                "model": self._agent_model,
            },
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )

    async def record_tool_started(
        self,
        tool_name: str,
        tool_use_id: str,
        input_preview: str,
    ) -> None:
        """Record tool execution started."""
        if self._writer is None:
            return

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=ObservationType.TOOL_EXECUTION_STARTED,
            data={
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "input_preview": input_preview,
            },
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )

    async def record_tool_completed(
        self,
        tool_name: str,
        tool_use_id: str,
        success: bool,
        output_preview: str | None,
    ) -> None:
        """Record tool execution completed."""
        if self._writer is None:
            return

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=ObservationType.TOOL_EXECUTION_COMPLETED,
            data={
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "success": success,
                "output_preview": output_preview,
            },
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )

    async def record_subagent_started(
        self,
        agent_name: str,
        tool_use_id: str,
    ) -> None:
        """Record subagent started."""
        if self._writer is None:
            return

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=ObservationType.SUBAGENT_STARTED,
            data={
                "agent_name": agent_name,
                "subagent_tool_use_id": tool_use_id,
            },
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )
        logger.info("Subagent started: %s (id=%s)", agent_name, tool_use_id)

    async def record_subagent_stopped(
        self,
        agent_name: str,
        tool_use_id: str,
        duration_ms: int | None,
        success: bool | None,
        tools_used: dict[str, int] | None,
    ) -> None:
        """Record subagent stopped."""
        if self._writer is None:
            return

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=ObservationType.SUBAGENT_STOPPED,
            data={
                "agent_name": agent_name,
                "subagent_tool_use_id": tool_use_id,
                "duration_ms": duration_ms,
                "success": success,
                "tools_used": tools_used,
            },
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )
        logger.info(
            "Subagent stopped: %s (id=%s, duration=%dms, tools=%s)",
            agent_name,
            tool_use_id,
            duration_ms or 0,
            tools_used,
        )

    async def record_session_summary(
        self,
        total_cost_usd: float | None,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int,
        cache_read: int,
        num_turns: int | None,
        duration_ms: int | None,
    ) -> None:
        """Record end-of-session summary with authoritative CLI totals (ISS-217).

        Emits a session_summary observation so SessionCostProjection.on_session_summary()
        can overwrite accumulated estimates with the SDK-reported values.
        """
        if self._writer is None:
            return

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=SESSION_SUMMARY,
            data={
                "total_cost_usd": total_cost_usd,
                "total_input_tokens": input_tokens,
                "total_output_tokens": output_tokens,
                "cache_creation_tokens": cache_creation,
                "cache_read_tokens": cache_read,
                "num_turns": num_turns,
                "duration_ms": duration_ms,
                "model": self._agent_model,
            },
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )
        logger.info(
            "Session summary recorded: cost=$%s, %d in, %d out, %d turns, %dms",
            total_cost_usd,
            input_tokens,
            output_tokens,
            num_turns or 0,
            duration_ms or 0,
        )

    async def record_embedded_event(
        self,
        event_type: str,
        enriched: dict[str, Any],
    ) -> None:
        """Record an embedded event (e.g., git hook events from tool output)."""
        if self._writer is None:
            return

        data = {
            **(enriched.get("context") or {}),
            **(enriched.get("metadata") or {}),
        }
        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=event_type,
            data=data,
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )
