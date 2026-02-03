"""Tests for ExecutionCostProjection with unified AgentObservation model."""

from datetime import datetime
from typing import Any

import pytest

from aef_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from aef_domain.contexts.orchestration.slices.execution_cost.projection import (
    ExecutionCostProjection,
)


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


@pytest.mark.unit
class TestAgentObservationHandling:
    """Tests for unified AgentObservation event handling."""

    @pytest.mark.asyncio
    async def test_token_usage_observation_creates_execution(
        self, projection: ExecutionCostProjection
    ) -> None:
        """Test that TOKEN_USAGE observation creates a new execution cost."""
        event_data = {
            "session_id": "session-1",
            "execution_id": "exec-1",
            "observation_type": ObservationType.TOKEN_USAGE.value,
            "data": {
                "input_tokens": 5000,
                "output_tokens": 2000,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
            },
            "timestamp": datetime.now().isoformat(),
        }

        await projection.on_agent_observation(event_data)

        execution_cost = await projection.get_execution_cost("exec-1")
        assert execution_cost is not None
        assert execution_cost.execution_id == "exec-1"
        assert execution_cost.input_tokens == 5000
        assert execution_cost.output_tokens == 2000
        assert "session-1" in execution_cost.session_ids
        assert execution_cost.session_count == 1

    @pytest.mark.asyncio
    async def test_token_usage_aggregates_sessions(
        self, projection: ExecutionCostProjection
    ) -> None:
        """Test that multiple sessions aggregate to execution."""
        # First session
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "observation_type": ObservationType.TOKEN_USAGE.value,
                "data": {"input_tokens": 1000, "output_tokens": 500},
            }
        )

        # Second session
        await projection.on_agent_observation(
            {
                "session_id": "session-2",
                "execution_id": "exec-1",
                "observation_type": ObservationType.TOKEN_USAGE.value,
                "data": {"input_tokens": 2000, "output_tokens": 1000},
            }
        )

        execution_cost = await projection.get_execution_cost("exec-1")
        assert execution_cost is not None
        assert execution_cost.session_count == 2
        assert "session-1" in execution_cost.session_ids
        assert "session-2" in execution_cost.session_ids
        assert execution_cost.input_tokens == 3000
        assert execution_cost.output_tokens == 1500

    @pytest.mark.asyncio
    async def test_observation_without_execution_skipped(
        self, projection: ExecutionCostProjection
    ) -> None:
        """Test that observations without execution_id are skipped."""
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "observation_type": ObservationType.TOKEN_USAGE.value,
                "data": {"input_tokens": 1000, "output_tokens": 500},
            }
        )

        all_executions = await projection.get_all()
        assert len(all_executions) == 0

    @pytest.mark.asyncio
    async def test_tool_completed_increments_count(
        self, projection: ExecutionCostProjection
    ) -> None:
        """Test that TOOL_COMPLETED observation increments tool calls."""
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "observation_type": ObservationType.TOOL_COMPLETED.value,
                "data": {
                    "tool_name": "Read",
                    "tool_use_id": "tool-1",
                    "success": True,
                    "duration_ms": 100,
                },
            }
        )

        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "observation_type": ObservationType.TOOL_COMPLETED.value,
                "data": {
                    "tool_name": "Write",
                    "tool_use_id": "tool-2",
                    "success": True,
                    "duration_ms": 200,
                },
            }
        )

        execution_cost = await projection.get_execution_cost("exec-1")
        assert execution_cost is not None
        assert execution_cost.tool_calls == 2
        assert execution_cost.duration_ms == 300

    @pytest.mark.asyncio
    async def test_session_counted_once(self, projection: ExecutionCostProjection) -> None:
        """Test that same session is only counted once."""
        # Multiple observations from same session
        for _ in range(5):
            await projection.on_agent_observation(
                {
                    "session_id": "session-1",
                    "execution_id": "exec-1",
                    "observation_type": ObservationType.TOKEN_USAGE.value,
                    "data": {"input_tokens": 100, "output_tokens": 50},
                }
            )

        execution_cost = await projection.get_execution_cost("exec-1")
        assert execution_cost is not None
        assert execution_cost.session_count == 1
        assert len(execution_cost.session_ids) == 1


class TestSessionCostFinalized:
    """Tests for SessionCostFinalized event handling."""

    @pytest.mark.asyncio
    async def test_session_cost_finalized_tracks_completion(
        self, projection: ExecutionCostProjection
    ) -> None:
        """Test that SessionCostFinalized updates completion time."""
        # First some observations
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "observation_type": ObservationType.TOKEN_USAGE.value,
                "data": {"input_tokens": 1000, "output_tokens": 500},
            }
        )

        # Then finalize
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
