"""Tests for SessionCostProjection with unified AgentObservation model."""

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import SessionCostProjection


class MockProjectionStore:
    """Mock projection store for testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def save(self, projection_name: str, key: str, data: dict[str, Any]) -> None:
        """Save data to the store."""
        if projection_name not in self._data:
            self._data[projection_name] = {}
        self._data[projection_name][key] = data

    async def get(self, projection_name: str, key: str) -> dict[str, Any] | None:
        """Get data from the store."""
        return self._data.get(projection_name, {}).get(key)

    async def query(
        self,
        projection_name: str,
        filters: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Query data from the store."""
        results = list(self._data.get(projection_name, {}).values())
        if filters:
            results = [r for r in results if all(r.get(k) == v for k, v in filters.items())]
        return results

    async def get_all(self, projection_name: str) -> list[dict[str, Any]]:
        """Get all data from the store."""
        return list(self._data.get(projection_name, {}).values())


@pytest.fixture
def store() -> MockProjectionStore:
    """Create a mock projection store."""
    return MockProjectionStore()


@pytest.fixture
def projection(store: MockProjectionStore) -> SessionCostProjection:
    """Create a SessionCostProjection with mock store."""
    return SessionCostProjection(store)


@pytest.mark.unit
class TestAgentObservationHandling:
    """Tests for unified AgentObservation event handling."""

    @pytest.mark.asyncio
    async def test_token_usage_observation_creates_session(
        self, projection: SessionCostProjection
    ) -> None:
        """Test that TOKEN_USAGE observation creates a new session cost."""
        event_data = {
            "session_id": "session-1",
            "execution_id": "exec-1",
            "event_type": ObservationType.TOKEN_USAGE.value,
            "data": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_creation_tokens": 200,
                "cache_read_tokens": 1000,
                "model": "claude-sonnet-4-20250514",
            },
            "timestamp": datetime.now().isoformat(),
        }

        await projection.on_agent_observation(event_data)

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        assert session_cost.session_id == "session-1"
        assert session_cost.execution_id == "exec-1"
        assert session_cost.input_tokens == 1000
        assert session_cost.output_tokens == 500
        assert session_cost.cache_creation_tokens == 200
        assert session_cost.cache_read_tokens == 1000
        assert session_cost.turns == 1

    @pytest.mark.asyncio
    async def test_token_usage_observation_calculates_cost(
        self, projection: SessionCostProjection
    ) -> None:
        """Test that TOKEN_USAGE observation calculates cost correctly."""
        event_data = {
            "session_id": "session-1",
            "event_type": ObservationType.TOKEN_USAGE.value,
            "data": {
                "input_tokens": 1_000_000,  # 1M tokens
                "output_tokens": 1_000_000,  # 1M tokens
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
            },
            "timestamp": datetime.now().isoformat(),
        }

        await projection.on_agent_observation(event_data)

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        # 1M input @ $3/MTok = $3.00
        # 1M output @ $15/MTok = $15.00
        # Total = $18.00
        assert session_cost.token_cost_usd == Decimal("18.00")
        assert session_cost.total_cost_usd == Decimal("18.00")

    @pytest.mark.asyncio
    async def test_token_usage_accumulates_across_turns(
        self, projection: SessionCostProjection
    ) -> None:
        """Test that multiple TOKEN_USAGE observations accumulate."""
        # First turn
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                },
            }
        )

        # Second turn
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {
                    "input_tokens": 2000,
                    "output_tokens": 1000,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 5000,
                },
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        assert session_cost.input_tokens == 3000
        assert session_cost.output_tokens == 1500
        assert session_cost.cache_read_tokens == 5000
        assert session_cost.turns == 2

    @pytest.mark.asyncio
    async def test_tool_completed_observation_increments_count(
        self, projection: SessionCostProjection
    ) -> None:
        """Test that TOOL_EXECUTION_COMPLETED observation increments tool_calls."""
        # First tool
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "event_type": ObservationType.TOOL_EXECUTION_COMPLETED.value,
                "data": {
                    "tool_name": "Read",
                    "tool_use_id": "tool-1",
                    "success": True,
                    "duration_ms": 150,
                },
            }
        )

        # Second tool
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "event_type": ObservationType.TOOL_EXECUTION_COMPLETED.value,
                "data": {
                    "tool_name": "Write",
                    "tool_use_id": "tool-2",
                    "success": True,
                    "duration_ms": 250,
                },
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        assert session_cost.tool_calls == 2
        assert session_cost.duration_ms == 400  # 150 + 250

    @pytest.mark.asyncio
    async def test_mixed_observations(self, projection: SessionCostProjection) -> None:
        """Test handling both TOKEN_USAGE and TOOL_EXECUTION_COMPLETED observations."""
        # Token usage
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {
                    "input_tokens": 5000,
                    "output_tokens": 2000,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "model": "claude-sonnet-4-20250514",
                },
            }
        )

        # Tool completed
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "event_type": ObservationType.TOOL_EXECUTION_COMPLETED.value,
                "data": {
                    "tool_name": "Bash",
                    "tool_use_id": "tool-1",
                    "success": True,
                    "duration_ms": 500,
                },
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        assert session_cost.execution_id == "exec-1"
        assert session_cost.input_tokens == 5000
        assert session_cost.output_tokens == 2000
        assert session_cost.tool_calls == 1
        assert session_cost.turns == 1
        assert session_cost.total_cost_usd > Decimal("0")  # Has token cost

    @pytest.mark.asyncio
    async def test_cache_token_costs(self, projection: SessionCostProjection) -> None:
        """Test that cache token costs are calculated correctly."""
        event_data = {
            "session_id": "session-1",
            "event_type": ObservationType.TOKEN_USAGE.value,
            "data": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_tokens": 1_000_000,  # 1M tokens @ $3.75/MTok
                "cache_read_tokens": 1_000_000,  # 1M tokens @ $0.30/MTok
            },
        }

        await projection.on_agent_observation(event_data)

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        # Cache write: 1M @ $3.75/MTok = $3.75
        # Cache read: 1M @ $0.30/MTok = $0.30
        # Total = $4.05
        assert session_cost.total_cost_usd == Decimal("4.05")

    @pytest.mark.asyncio
    async def test_cost_by_model_tracking(self, projection: SessionCostProjection) -> None:
        """Test that cost is tracked by model."""
        # Event with model specified
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {
                    "input_tokens": 1_000_000,
                    "output_tokens": 1_000_000,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "model": "claude-sonnet-4-20250514",
                },
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        assert "claude-sonnet-4-20250514" in session_cost.cost_by_model
        assert session_cost.cost_by_model["claude-sonnet-4-20250514"] == Decimal("18.00")

    @pytest.mark.asyncio
    async def test_skip_observation_without_session_id(
        self, projection: SessionCostProjection
    ) -> None:
        """Test that observations without session_id are skipped."""
        await projection.on_agent_observation(
            {
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                },
            }
        )

        all_sessions = await projection.get_all()
        assert len(all_sessions) == 0


class TestSessionCostFinalized:
    """Tests for SessionCostFinalized event handling."""

    @pytest.mark.asyncio
    async def test_on_session_cost_finalized(self, projection: SessionCostProjection) -> None:
        """Test handling SessionCostFinalized event."""
        # First add some observations
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                },
            }
        )

        # Then finalize
        await projection.on_session_cost_finalized(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "total_cost_usd": "1.50",
                "token_cost_usd": "1.00",
                "compute_cost_usd": "0.50",
                "input_tokens": 10000,
                "output_tokens": 5000,
                "tool_calls": 10,
                "completed_at": datetime.now().isoformat(),
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        assert session_cost.is_finalized is True
        assert session_cost.total_cost_usd == Decimal("1.50")
        assert session_cost.tool_calls == 10
        assert session_cost.completed_at is not None


class TestOnSessionSummary:
    """Tests for on_session_summary — authoritative CLI totals (ISS-100/217)."""

    @pytest.mark.asyncio
    async def test_overwrites_accumulated_cost_with_sdk_value(
        self, projection: SessionCostProjection
    ) -> None:
        """session_summary total_cost_usd replaces accumulated estimate."""
        # Accumulate some per-turn costs first
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {
                    "input_tokens": 2713,
                    "output_tokens": 2017,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                },
            }
        )
        # session_summary arrives with SDK's authoritative total
        await projection.on_session_summary(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "phase_id": "phase-1",
                "data": {
                    "total_cost_usd": 0.0319359,
                    "total_input_tokens": 685,
                    "total_output_tokens": 1961,
                    "cache_creation_tokens": 5596,
                    "cache_read_tokens": 144509,
                    "num_turns": 7,
                    "duration_ms": 48022,
                    "model": "claude-haiku-4-5-20251001",
                },
            }
        )

        cost = await projection.get_session_cost("session-1")
        assert cost is not None
        assert cost.total_cost_usd == Decimal("0.0319359")
        assert cost.input_tokens == 685
        assert cost.output_tokens == 1961
        assert cost.cache_creation_tokens == 5596
        assert cost.cache_read_tokens == 144509
        assert cost.turns == 7
        assert cost.duration_ms == 48022
        assert cost.agent_model == "claude-haiku-4-5-20251001"
        assert cost.is_finalized is True

    @pytest.mark.asyncio
    async def test_cache_tokens_populated_from_summary(
        self, projection: SessionCostProjection
    ) -> None:
        """Cache tokens are set from session_summary data (not zeroed by the overwrite)."""
        await projection.on_session_summary(
            {
                "session_id": "session-1",
                "data": {
                    "total_cost_usd": 0.05,
                    "total_input_tokens": 100,
                    "total_output_tokens": 50,
                    "cache_creation_tokens": 8000,
                    "cache_read_tokens": 120000,
                    "num_turns": 3,
                    "duration_ms": 5000,
                    "model": "claude-sonnet-4-6",
                },
            }
        )

        cost = await projection.get_session_cost("session-1")
        assert cost is not None
        assert cost.cache_creation_tokens == 8000
        assert cost.cache_read_tokens == 120000

    @pytest.mark.asyncio
    async def test_agent_model_stored_from_summary(
        self, projection: SessionCostProjection
    ) -> None:
        """agent_model is populated from session_summary model field."""
        await projection.on_session_summary(
            {
                "session_id": "session-1",
                "data": {
                    "total_cost_usd": 0.01,
                    "total_input_tokens": 10,
                    "total_output_tokens": 5,
                    "model": "claude-haiku-4-5-20251001",
                },
            }
        )

        cost = await projection.get_session_cost("session-1")
        assert cost is not None
        assert cost.agent_model == "claude-haiku-4-5-20251001"

    @pytest.mark.asyncio
    async def test_summary_without_cost_preserves_existing(
        self, projection: SessionCostProjection
    ) -> None:
        """If total_cost_usd is absent, accumulated cost is not zeroed."""
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {
                    "input_tokens": 500,
                    "output_tokens": 100,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                },
            }
        )
        accumulated = (await projection.get_session_cost("session-1")).total_cost_usd  # type: ignore[union-attr]

        await projection.on_session_summary(
            {
                "session_id": "session-1",
                "data": {
                    # No total_cost_usd
                    "total_input_tokens": 500,
                    "total_output_tokens": 100,
                    "num_turns": 1,
                    "duration_ms": 2000,
                },
            }
        )

        cost = await projection.get_session_cost("session-1")
        assert cost is not None
        assert cost.total_cost_usd == accumulated


class TestQueryOperations:
    """Tests for projection query operations."""

    @pytest.mark.asyncio
    async def test_get_sessions_for_execution(self, projection: SessionCostProjection) -> None:
        """Test getting all sessions for an execution."""
        # Create two sessions for same execution
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {"input_tokens": 1000, "output_tokens": 500},
            }
        )

        await projection.on_agent_observation(
            {
                "session_id": "session-2",
                "execution_id": "exec-1",
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {"input_tokens": 2000, "output_tokens": 1000},
            }
        )

        # Create one for different execution
        await projection.on_agent_observation(
            {
                "session_id": "session-3",
                "execution_id": "exec-2",
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {"input_tokens": 3000, "output_tokens": 1500},
            }
        )

        sessions = await projection.get_sessions_for_execution("exec-1")
        assert len(sessions) == 2
        session_ids = [s.session_id for s in sessions]
        assert "session-1" in session_ids
        assert "session-2" in session_ids
