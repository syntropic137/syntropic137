"""Port interface for observability data recording.

Per ADR-026 (TimescaleDB Observability Storage), observability data is stored
in TimescaleDB for real-time querying and dashboard display.
"""

from typing import Any, Protocol


class ObservabilityServicePort(Protocol):
    """Port for recording agent observations to TimescaleDB.

    Per ADR-026, observability events are stored in:
    - `agent_events` table (TimescaleDB hypertable)
    - Indexed by session_id, execution_id, phase_id
    - Supports real-time queries for dashboard

    Observation types (from ADR-037):
    - TOKEN_USAGE: Input/output token counts, cache stats
    - TOOL_STARTED: Tool invocation with input preview
    - TOOL_COMPLETED: Tool result with output preview, success status
    - SUBAGENT_STARTED: Task tool invocation (subagent creation)
    - SUBAGENT_STOPPED: Task tool completion with tools_used breakdown
    """

    async def record_observation(
        self,
        session_id: str,
        observation_type: str,
        data: dict[str, Any],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        """Record an agent observation to TimescaleDB.

        Args:
            session_id: The session ID (required).
            observation_type: Type of observation (TOKEN_USAGE, TOOL_STARTED, etc.).
            data: Observation data as JSONB (structure depends on observation_type).
            execution_id: Optional execution ID for workflow context.
            phase_id: Optional phase ID for workflow context.
            workspace_id: Optional workspace ID for container context.

        Example:
            await observability.record_observation(
                session_id="session-123",
                observation_type="TOKEN_USAGE",
                data={
                    "input_tokens": 1500,
                    "output_tokens": 300,
                    "cache_read_tokens": 800,
                    "model": "claude-sonnet-4-20250514",
                },
                execution_id="exec-123",
                phase_id="phase-456",
            )
        """
        ...

    async def initialize(self) -> None:
        """Initialize the observability storage (create tables if needed).

        This method is typically called once at application startup to ensure
        the TimescaleDB schema exists.
        """
        ...
