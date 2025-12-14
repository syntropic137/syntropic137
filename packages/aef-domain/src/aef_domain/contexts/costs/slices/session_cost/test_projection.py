"""Tests for SessionCostProjection."""

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from aef_domain.contexts.costs.slices.session_cost.projection import SessionCostProjection


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


class TestSessionCostProjection:
    """Tests for SessionCostProjection."""

    @pytest.mark.asyncio
    async def test_on_cost_recorded_creates_session(
        self, projection: SessionCostProjection
    ) -> None:
        """Test that CostRecorded creates a new session cost."""
        event_data = {
            "session_id": "session-1",
            "execution_id": "exec-1",
            "cost_type": "llm_tokens",
            "amount_usd": "0.01",
            "model": "claude-sonnet-4-20250514",
            "input_tokens": 1000,
            "output_tokens": 500,
            "timestamp": datetime.now().isoformat(),
        }

        await projection.on_cost_recorded(event_data)

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        assert session_cost.session_id == "session-1"
        assert session_cost.execution_id == "exec-1"
        assert session_cost.total_cost_usd == Decimal("0.01")
        assert session_cost.token_cost_usd == Decimal("0.01")
        assert session_cost.input_tokens == 1000
        assert session_cost.output_tokens == 500

    @pytest.mark.asyncio
    async def test_on_cost_recorded_accumulates_costs(
        self, projection: SessionCostProjection
    ) -> None:
        """Test that multiple CostRecorded events accumulate."""
        # First event
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.01",
                "input_tokens": 1000,
                "output_tokens": 500,
            }
        )

        # Second event
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.02",
                "input_tokens": 2000,
                "output_tokens": 1000,
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        assert session_cost.total_cost_usd == Decimal("0.03")
        assert session_cost.input_tokens == 3000
        assert session_cost.output_tokens == 1500
        assert session_cost.turns == 2

    @pytest.mark.asyncio
    async def test_on_cost_recorded_tool_execution(self, projection: SessionCostProjection) -> None:
        """Test handling tool execution costs."""
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "tool_execution",
                "amount_usd": "0.001",
                "tool_name": "read_file",
                "tool_duration_ms": 150,
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        assert session_cost.compute_cost_usd == Decimal("0.001")
        assert session_cost.tool_calls == 1
        assert session_cost.duration_ms == 150
        assert "read_file" in session_cost.cost_by_tool

    @pytest.mark.asyncio
    async def test_on_session_cost_finalized(self, projection: SessionCostProjection) -> None:
        """Test handling SessionCostFinalized event."""
        # First add some incremental costs
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.01",
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

    @pytest.mark.asyncio
    async def test_get_sessions_for_execution(self, projection: SessionCostProjection) -> None:
        """Test getting all sessions for an execution."""
        # Create two sessions for same execution
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.01",
            }
        )

        await projection.on_cost_recorded(
            {
                "session_id": "session-2",
                "execution_id": "exec-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.02",
            }
        )

        # Create one for different execution
        await projection.on_cost_recorded(
            {
                "session_id": "session-3",
                "execution_id": "exec-2",
                "cost_type": "llm_tokens",
                "amount_usd": "0.03",
            }
        )

        sessions = await projection.get_sessions_for_execution("exec-1")
        assert len(sessions) == 2
        session_ids = [s.session_id for s in sessions]
        assert "session-1" in session_ids
        assert "session-2" in session_ids

    @pytest.mark.asyncio
    async def test_skip_event_without_session_id(self, projection: SessionCostProjection) -> None:
        """Test that events without session_id are skipped."""
        await projection.on_cost_recorded(
            {
                "cost_type": "llm_tokens",
                "amount_usd": "0.01",
            }
        )

        all_sessions = await projection.get_all()
        assert len(all_sessions) == 0


class TestToolTokenAggregation:
    """Tests for tool token aggregation in SessionCostProjection."""

    @pytest.mark.asyncio
    async def test_aggregate_tool_tokens_single_event(
        self, projection: SessionCostProjection
    ) -> None:
        """Test aggregating tool tokens from a single event."""
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.01",
                "tool_token_breakdown": {
                    "Read": {"tool_use": 30, "tool_result": 500},
                    "Write": {"tool_use": 200, "tool_result": 10},
                },
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        assert session_cost.tokens_by_tool == {"Read": 530, "Write": 210}

    @pytest.mark.asyncio
    async def test_aggregate_tool_tokens_multiple_events(
        self, projection: SessionCostProjection
    ) -> None:
        """Test that tool tokens aggregate across multiple events."""
        # First event
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.01",
                "tool_token_breakdown": {
                    "Read": {"tool_use": 30, "tool_result": 500},
                },
            }
        )

        # Second event with more Read and new Write
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.02",
                "tool_token_breakdown": {
                    "Read": {"tool_use": 30, "tool_result": 1000},
                    "Write": {"tool_use": 500, "tool_result": 10},
                },
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        # Read: 530 + 1030 = 1560
        assert session_cost.tokens_by_tool["Read"] == 1560
        # Write: 510 (only from second event)
        assert session_cost.tokens_by_tool["Write"] == 510

    @pytest.mark.asyncio
    async def test_no_tool_tokens_when_empty_breakdown(
        self, projection: SessionCostProjection
    ) -> None:
        """Test that empty breakdown doesn't affect tokens_by_tool."""
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.01",
                "tool_token_breakdown": {},
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        assert session_cost.tokens_by_tool == {}

    @pytest.mark.asyncio
    async def test_tool_tokens_serialization_roundtrip(
        self, projection: SessionCostProjection
    ) -> None:
        """Test that tokens_by_tool survives serialization/deserialization."""
        # Create with tool tokens
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.01",
                "tool_token_breakdown": {
                    "Shell": {"tool_use": 50, "tool_result": 1000},
                },
            }
        )

        # Add more to same session (forces reload from store)
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.01",
                "tool_token_breakdown": {
                    "Shell": {"tool_use": 50, "tool_result": 2000},
                },
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        # Shell: 1050 + 2050 = 3100
        assert session_cost.tokens_by_tool["Shell"] == 3100

    @pytest.mark.asyncio
    async def test_cost_by_tool_tokens_calculated(self, projection: SessionCostProjection) -> None:
        """Test that cost_by_tool_tokens is calculated proportionally."""
        # Event with 1000 total tokens and $0.10 cost
        # Write has 500 tokens (50%), should get $0.05
        # Read has 300 tokens (30%), should get $0.03
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.10",
                "input_tokens": 600,
                "output_tokens": 400,
                "tool_token_breakdown": {
                    "Write": {"tool_use": 200, "tool_result": 300},  # 500 tokens
                    "Read": {"tool_use": 100, "tool_result": 200},  # 300 tokens
                },
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None

        # Verify cost_by_tool_tokens calculated
        assert "Write" in session_cost.cost_by_tool_tokens
        assert "Read" in session_cost.cost_by_tool_tokens

        # Write: 500/1000 * 0.10 = 0.05
        from decimal import Decimal

        assert session_cost.cost_by_tool_tokens["Write"] == Decimal("0.05")
        # Read: 300/1000 * 0.10 = 0.03
        assert session_cost.cost_by_tool_tokens["Read"] == Decimal("0.03")

    @pytest.mark.asyncio
    async def test_cost_by_tool_tokens_aggregates_across_events(
        self, projection: SessionCostProjection
    ) -> None:
        """Test that cost_by_tool_tokens aggregates across multiple events."""
        from decimal import Decimal

        # First event: Write gets 50% of $0.10 = $0.05
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.10",
                "input_tokens": 500,
                "output_tokens": 500,
                "tool_token_breakdown": {
                    "Write": {"tool_use": 250, "tool_result": 250},  # 500/1000 = 50%
                },
            }
        )

        # Second event: Write gets 25% of $0.20 = $0.05
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.20",
                "input_tokens": 1000,
                "output_tokens": 1000,
                "tool_token_breakdown": {
                    "Write": {"tool_use": 200, "tool_result": 300},  # 500/2000 = 25%
                },
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None

        # Write: $0.05 + $0.05 = $0.10
        assert session_cost.cost_by_tool_tokens["Write"] == Decimal("0.10")

    @pytest.mark.asyncio
    async def test_cost_by_tool_tokens_zero_when_no_tokens(
        self, projection: SessionCostProjection
    ) -> None:
        """Test that cost is not calculated when total tokens is zero."""
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.10",
                "input_tokens": 0,
                "output_tokens": 0,
                "tool_token_breakdown": {
                    "Write": {"tool_use": 100, "tool_result": 100},
                },
            }
        )

        session_cost = await projection.get_session_cost("session-1")
        assert session_cost is not None
        # Tokens recorded but no cost (would be divide by zero)
        assert session_cost.tokens_by_tool.get("Write") == 200
        assert session_cost.cost_by_tool_tokens.get("Write") is None
