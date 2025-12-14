"""Tests for ExecutionCostProjection."""

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from aef_domain.contexts.costs.slices.execution_cost.projection import ExecutionCostProjection


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

    async def get_all(self, projection_name: str) -> list[dict[str, Any]]:
        """Get all data from the store."""
        return list(self._data.get(projection_name, {}).values())


@pytest.fixture
def store() -> MockProjectionStore:
    """Create a mock projection store."""
    return MockProjectionStore()


@pytest.fixture
def projection(store: MockProjectionStore) -> ExecutionCostProjection:
    """Create an ExecutionCostProjection with mock store."""
    return ExecutionCostProjection(store)


class TestExecutionCostProjection:
    """Tests for ExecutionCostProjection."""

    @pytest.mark.asyncio
    async def test_on_cost_recorded_creates_execution(
        self, projection: ExecutionCostProjection
    ) -> None:
        """Test that CostRecorded creates a new execution cost."""
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

        execution_cost = await projection.get_execution_cost("exec-1")
        assert execution_cost is not None
        assert execution_cost.execution_id == "exec-1"
        assert execution_cost.total_cost_usd == Decimal("0.01")
        assert execution_cost.session_count == 1
        assert "session-1" in execution_cost.session_ids

    @pytest.mark.asyncio
    async def test_on_cost_recorded_aggregates_sessions(
        self, projection: ExecutionCostProjection
    ) -> None:
        """Test that costs from multiple sessions are aggregated."""
        # Session 1
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "phase_id": "research",
                "cost_type": "llm_tokens",
                "amount_usd": "0.50",
                "input_tokens": 5000,
                "output_tokens": 2500,
            }
        )

        # Session 2
        await projection.on_cost_recorded(
            {
                "session_id": "session-2",
                "execution_id": "exec-1",
                "phase_id": "execute",
                "cost_type": "llm_tokens",
                "amount_usd": "1.00",
                "input_tokens": 10000,
                "output_tokens": 5000,
            }
        )

        execution_cost = await projection.get_execution_cost("exec-1")
        assert execution_cost is not None
        assert execution_cost.total_cost_usd == Decimal("1.50")
        assert execution_cost.session_count == 2
        assert execution_cost.input_tokens == 15000
        assert execution_cost.output_tokens == 7500
        assert "research" in execution_cost.cost_by_phase
        assert "execute" in execution_cost.cost_by_phase

    @pytest.mark.asyncio
    async def test_on_cost_recorded_without_execution_skipped(
        self, projection: ExecutionCostProjection
    ) -> None:
        """Test that costs without execution_id are skipped."""
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "cost_type": "llm_tokens",
                "amount_usd": "0.01",
            }
        )

        all_executions = await projection.get_all()
        assert len(all_executions) == 0

    @pytest.mark.asyncio
    async def test_on_session_cost_finalized_tracks_completion(
        self, projection: ExecutionCostProjection
    ) -> None:
        """Test that SessionCostFinalized updates execution tracking."""
        # Add some costs
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "cost_type": "llm_tokens",
                "amount_usd": "1.00",
            }
        )

        # Finalize session
        completed_at = datetime.now()
        await projection.on_session_cost_finalized(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "completed_at": completed_at.isoformat(),
            }
        )

        execution_cost = await projection.get_execution_cost("exec-1")
        assert execution_cost is not None
        assert execution_cost.completed_at is not None

    @pytest.mark.asyncio
    async def test_session_counted_once(self, projection: ExecutionCostProjection) -> None:
        """Test that same session is only counted once."""
        # Multiple events from same session
        for _ in range(5):
            await projection.on_cost_recorded(
                {
                    "session_id": "session-1",
                    "execution_id": "exec-1",
                    "cost_type": "llm_tokens",
                    "amount_usd": "0.01",
                }
            )

        execution_cost = await projection.get_execution_cost("exec-1")
        assert execution_cost is not None
        assert execution_cost.session_count == 1
        assert len(execution_cost.session_ids) == 1
        assert execution_cost.total_cost_usd == Decimal("0.05")

    @pytest.mark.asyncio
    async def test_tool_execution_costs_aggregated(
        self, projection: ExecutionCostProjection
    ) -> None:
        """Test that tool execution costs are aggregated."""
        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "cost_type": "tool_execution",
                "amount_usd": "0.001",
                "tool_name": "read_file",
                "tool_duration_ms": 100,
            }
        )

        await projection.on_cost_recorded(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "cost_type": "tool_execution",
                "amount_usd": "0.002",
                "tool_name": "write_file",
                "tool_duration_ms": 200,
            }
        )

        execution_cost = await projection.get_execution_cost("exec-1")
        assert execution_cost is not None
        assert execution_cost.compute_cost_usd == Decimal("0.003")
        assert execution_cost.tool_calls == 2
        assert execution_cost.duration_ms == 300
        assert "read_file" in execution_cost.cost_by_tool
        assert "write_file" in execution_cost.cost_by_tool
