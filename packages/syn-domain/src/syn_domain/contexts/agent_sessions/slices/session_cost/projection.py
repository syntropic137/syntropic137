"""Projection for session cost tracking.

Pattern: Event Log + CQRS (ADR-018 Pattern 2)

Data Sources:
- TimescaleDB: agent_events table (token_usage, tool_execution_completed)
- Event Store: SessionCostFinalized events (optional finalized totals)

See ADR-029: Simplified Event System
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost


class SessionCostProjection:
    """Builds session cost from cost events.

    This projection maintains running totals for each session,
    enabling queries like "how much has session X cost so far".

    The session is the atomic unit for cost tracking:
    - Single agent
    - Single phase
    - Single workspace/sandbox
    """

    PROJECTION_NAME = "session_cost"

    def __init__(self, store: Any, pool: Any | None = None):
        """Initialize with a projection store and optional DB pool.

        Args:
            store: A ProjectionStoreProtocol implementation
            pool: asyncpg Pool for querying TimescaleDB (ADR-029)
        """
        self._store = store
        self._pool = pool

    @property
    def name(self) -> str:
        """Get the projection name."""
        return self.PROJECTION_NAME

    async def on_agent_observation(self, event_data: dict[str, Any]) -> None:
        """Handle AgentObservation event.

        Processes unified telemetry:
        - TOKEN_USAGE: Calculate cost from tokens, update counts
        - TOOL_EXECUTION_COMPLETED: Increment tool_calls count
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        # Support both domain events (observation_type) and raw JSONL events (event_type)
        event_type = event_data.get("event_type") or event_data.get("observation_type")
        if not event_type:
            return

        # Get existing session cost or create new
        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        session_cost = (
            SessionCost.from_dict(existing) if existing else SessionCost(session_id=session_id)
        )

        # Update linkage if not set
        if not session_cost.execution_id and event_data.get("execution_id"):
            session_cost.execution_id = event_data["execution_id"]
        if not session_cost.phase_id and event_data.get("phase_id"):
            session_cost.phase_id = event_data["phase_id"]
        if not session_cost.workspace_id and event_data.get("workspace_id"):
            session_cost.workspace_id = event_data["workspace_id"]

        # Update started_at on first event
        if not session_cost.started_at:
            ts = event_data.get("timestamp")
            if ts:
                if isinstance(ts, str):
                    session_cost.started_at = datetime.fromisoformat(ts)
                elif isinstance(ts, datetime):
                    session_cost.started_at = ts

        # Type-specific payload
        data = event_data.get("data", {})

        # Handle TOKEN_USAGE observations
        if event_type == ObservationType.TOKEN_USAGE.value:
            input_tokens = data.get("input_tokens") or 0
            output_tokens = data.get("output_tokens") or 0
            cache_creation = data.get("cache_creation_tokens") or 0
            cache_read = data.get("cache_read_tokens") or 0

            # Update token counts
            session_cost.input_tokens += input_tokens
            session_cost.output_tokens += output_tokens
            session_cost.cache_creation_tokens += cache_creation
            session_cost.cache_read_tokens += cache_read

            # Calculate cost (using default pricing - can be enhanced with ModelPricing)
            # Prices per 1M tokens (Claude 3.5 Sonnet pricing)
            input_price_per_million = Decimal("3.00")  # $3/MTok input
            output_price_per_million = Decimal("15.00")  # $15/MTok output
            cache_write_per_million = Decimal("3.75")  # $3.75/MTok cache write
            cache_read_per_million = Decimal("0.30")  # $0.30/MTok cache read

            input_cost = (Decimal(input_tokens) / 1_000_000) * input_price_per_million
            output_cost = (Decimal(output_tokens) / 1_000_000) * output_price_per_million
            cache_write_cost = (Decimal(cache_creation) / 1_000_000) * cache_write_per_million
            cache_read_cost = (Decimal(cache_read) / 1_000_000) * cache_read_per_million

            token_cost = input_cost + output_cost + cache_write_cost + cache_read_cost
            session_cost.token_cost_usd += token_cost
            session_cost.total_cost_usd += token_cost

            # Update cost by model
            model = data.get("model")
            if model:
                current = session_cost.cost_by_model.get(model, Decimal("0"))
                session_cost.cost_by_model[model] = current + token_cost

            # Increment turns (each token_usage = one turn)
            session_cost.turns += 1

        # Handle TOOL_EXECUTION_COMPLETED observations
        elif event_type == ObservationType.TOOL_EXECUTION_COMPLETED.value:
            session_cost.tool_calls += 1

            # Track duration if available
            duration_ms = data.get("duration_ms")
            if duration_ms:
                session_cost.duration_ms += duration_ms

            # Track tool name for breakdown
            tool_name = data.get("tool_name")
            if tool_name:
                # Track call count by tool (using cost_by_tool as counter for now)
                # Note: actual tool execution cost would need compute pricing
                pass  # Tool execution itself is free - cost is in tokens

        # Save updated session cost
        await self._store.save(self.PROJECTION_NAME, session_id, session_cost.to_dict())

    async def on_session_summary(self, event_data: dict[str, Any]) -> None:
        """Handle session_summary event with accurate cumulative totals.

        This event is produced at the end of agent execution and contains
        the authoritative totals from Claude CLI's result event.
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        # Get existing or create new
        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        session_cost = (
            SessionCost.from_dict(existing) if existing else SessionCost(session_id=session_id)
        )

        # Update linkage
        if event_data.get("execution_id"):
            session_cost.execution_id = event_data["execution_id"]
        if event_data.get("phase_id"):
            session_cost.phase_id = event_data["phase_id"]

        # Extract summary data
        data = event_data.get("data", {})

        # Use authoritative totals from SessionSummary
        session_cost.input_tokens = data.get("total_input_tokens", session_cost.input_tokens)
        session_cost.output_tokens = data.get("total_output_tokens", session_cost.output_tokens)
        session_cost.tool_calls = data.get("tool_count", session_cost.tool_calls)
        session_cost.turns = data.get("num_turns", session_cost.turns)
        session_cost.duration_ms = data.get("duration_ms", session_cost.duration_ms)

        # Use SDK-provided cost if available (most accurate)
        if data.get("total_cost_usd") is not None:
            session_cost.total_cost_usd = Decimal(str(data["total_cost_usd"]))
            session_cost.token_cost_usd = session_cost.total_cost_usd

        # Update timestamp
        ts = event_data.get("timestamp")
        if ts:
            if isinstance(ts, str):
                session_cost.completed_at = datetime.fromisoformat(ts)
            elif isinstance(ts, datetime):
                session_cost.completed_at = ts

        # Mark as finalized since this is the end-of-session summary
        session_cost.is_finalized = True

        # Save
        await self._store.save(self.PROJECTION_NAME, session_id, session_cost.to_dict())

    async def on_session_cost_finalized(self, event_data: dict[str, Any]) -> None:
        """Handle SessionCostFinalized event.

        Marks the session as complete with final totals.
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        # Get existing or create from finalized data
        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            session_cost = SessionCost.from_dict(existing)
        else:
            session_cost = SessionCost(session_id=session_id)

        # Update from finalized event
        session_cost.execution_id = event_data.get("execution_id") or session_cost.execution_id
        session_cost.phase_id = event_data.get("phase_id") or session_cost.phase_id
        session_cost.workspace_id = event_data.get("workspace_id") or session_cost.workspace_id

        # Use finalized totals
        total_cost = event_data.get("total_cost_usd")
        if total_cost:
            session_cost.total_cost_usd = Decimal(str(total_cost))

        token_cost = event_data.get("token_cost_usd")
        if token_cost:
            session_cost.token_cost_usd = Decimal(str(token_cost))

        compute_cost = event_data.get("compute_cost_usd")
        if compute_cost:
            session_cost.compute_cost_usd = Decimal(str(compute_cost))

        # Token counts
        session_cost.input_tokens = event_data.get("input_tokens", session_cost.input_tokens)
        session_cost.output_tokens = event_data.get("output_tokens", session_cost.output_tokens)
        session_cost.cache_creation_tokens = event_data.get(
            "cache_creation_tokens", session_cost.cache_creation_tokens
        )
        session_cost.cache_read_tokens = event_data.get(
            "cache_read_tokens", session_cost.cache_read_tokens
        )

        # Metrics
        session_cost.tool_calls = event_data.get("tool_calls", session_cost.tool_calls)
        session_cost.turns = event_data.get("turns", session_cost.turns)
        session_cost.duration_ms = event_data.get("duration_ms", session_cost.duration_ms)

        # Breakdowns
        cost_by_model = event_data.get("cost_by_model", {})
        if cost_by_model:
            session_cost.cost_by_model = {k: Decimal(str(v)) for k, v in cost_by_model.items()}

        cost_by_tool = event_data.get("cost_by_tool", {})
        if cost_by_tool:
            session_cost.cost_by_tool = {k: Decimal(str(v)) for k, v in cost_by_tool.items()}

        # Timing
        started_at = event_data.get("started_at")
        if started_at:
            if isinstance(started_at, str):
                session_cost.started_at = datetime.fromisoformat(started_at)
            else:
                session_cost.started_at = started_at

        completed_at = event_data.get("completed_at")
        if completed_at:
            if isinstance(completed_at, str):
                session_cost.completed_at = datetime.fromisoformat(completed_at)
            else:
                session_cost.completed_at = completed_at

        # Mark as finalized
        session_cost.is_finalized = True

        # Save
        await self._store.save(self.PROJECTION_NAME, session_id, session_cost.to_dict())

    async def get_session_cost(self, session_id: str) -> SessionCost | None:
        """Get session cost by session ID.

        Queries TimescaleDB directly for real-time cost calculation.

        Args:
            session_id: The session to get cost for.

        Returns:
            SessionCost if found, None otherwise.
        """
        # Query TimescaleDB directly if observability_writer is available
        if self._pool is not None:
            return await self._calculate_from_timescale(session_id)

        # Fallback to projection store (legacy path)
        data = await self._store.get(self.PROJECTION_NAME, session_id)
        if not data:
            return None
        return SessionCost.from_dict(data)

    async def _calculate_from_timescale(self, session_id: str) -> SessionCost | None:
        """Calculate session cost directly from TimescaleDB observations.

        Args:
            session_id: The session to calculate cost for

        Returns:
            SessionCost with aggregated metrics, or None if no observations found
        """
        # Guard: this method should only be called when _pool is set
        if self._pool is None:
            return None

        async with self._pool.acquire() as conn:
            # First try execution_completed which has reliable totals
            # (SDK only provides token usage in ResultMessage, not per-turn)
            exec_result = await conn.fetchrow(
                """
                SELECT
                    (data->>'input_tokens')::int as total_input,
                    (data->>'output_tokens')::int as total_output,
                    (data->>'tool_call_count')::int as tool_count,
                    (data->>'total_cost_usd')::numeric as sdk_cost,
                    time as completed_at,
                    execution_id,
                    phase_id
                FROM agent_events
                WHERE session_id = $1 AND event_type = 'execution_completed'
                ORDER BY time DESC
                LIMIT 1
                """,
                session_id,
            )

            # Fall back to aggregating token_usage if no execution_completed
            if not exec_result or exec_result["total_input"] is None:
                token_result = await conn.fetchrow(
                    """
                    SELECT
                        SUM((data->>'input_tokens')::int) as total_input,
                        SUM((data->>'output_tokens')::int) as total_output,
                        SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
                        SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
                        MIN(time) as started_at,
                        MAX(time) as last_observation,
                        execution_id,
                        phase_id
                    FROM agent_events
                    WHERE session_id = $1 AND event_type = 'token_usage'
                    GROUP BY execution_id, phase_id
                    """,
                    session_id,
                )
            else:
                # Use execution_completed data
                token_result = exec_result

            if not token_result or token_result["total_input"] is None:
                return None

            # Get tool count - prefer from exec_result if available, else count events
            if exec_result and exec_result.get("tool_count"):
                tool_count = exec_result["tool_count"]
            else:
                tool_count = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM agent_events
                    WHERE session_id = $1 AND event_type = 'tool_completed'
                    """,
                    session_id,
                )

            # Get started_at from session_started event
            started_at = await conn.fetchval(
                """
                SELECT MIN(time)
                FROM agent_events
                WHERE session_id = $1 AND event_type IN ('session_started', 'execution_started')
                """,
                session_id,
            )

            # Get token counts
            input_tokens = token_result["total_input"] or 0
            output_tokens = token_result["total_output"] or 0
            # Cache tokens only available from token_usage aggregation
            cache_creation = token_result.get("cache_creation") or 0
            cache_read = token_result.get("cache_read") or 0

            # Prefer SDK-provided cost (includes tool token costs accurately)
            # Fall back to our calculation if SDK cost not available
            sdk_cost = exec_result.get("sdk_cost") if exec_result else None
            if sdk_cost is not None:
                total_cost = Decimal(str(sdk_cost))
            else:
                # Calculate cost (Claude Sonnet 4 pricing)
                input_cost = Decimal(input_tokens) * Decimal("0.000003")
                output_cost = Decimal(output_tokens) * Decimal("0.000015")
                cache_creation_cost = Decimal(cache_creation) * Decimal("0.00000375")
                cache_read_cost = Decimal(cache_read) * Decimal("0.0000003")
                total_cost = input_cost + output_cost + cache_creation_cost + cache_read_cost

            # Build SessionCost
            session_cost = SessionCost(session_id=session_id)
            session_cost.input_tokens = input_tokens
            session_cost.output_tokens = output_tokens
            session_cost.cache_creation_tokens = cache_creation
            session_cost.cache_read_tokens = cache_read
            session_cost.tool_calls = tool_count or 0
            session_cost.token_cost_usd = total_cost
            session_cost.total_cost_usd = total_cost
            session_cost.started_at = started_at
            session_cost.execution_id = token_result.get("execution_id")
            session_cost.phase_id = token_result.get("phase_id")
            session_cost.workspace_id = token_result.get("workspace_id")

            return session_cost

    async def get_sessions_for_execution(self, execution_id: str) -> list[SessionCost]:
        """Get all session costs for an execution.

        Args:
            execution_id: The execution to get sessions for.

        Returns:
            List of SessionCost for all sessions in the execution.
        """
        data = await self._store.query(
            self.PROJECTION_NAME,
            filters={"execution_id": execution_id},
            order_by="started_at",
        )
        return [SessionCost.from_dict(d) for d in data]

    async def get_all(self) -> list[SessionCost]:
        """Get all session costs."""
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [SessionCost.from_dict(d) for d in data]
