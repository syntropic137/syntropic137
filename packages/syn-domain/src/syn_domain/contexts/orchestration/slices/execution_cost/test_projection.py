"""Tests for ExecutionCostProjection with unified AgentObservation model."""

from datetime import datetime
from typing import Any

import pytest

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
    ExecutionCostProjection,
    _calculate_token_cost,
    _get_or_create,
    _track_session,
    _update_completed_at,
    _update_started_at,
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
        """Test that TOOL_EXECUTION_COMPLETED observation increments tool calls."""
        await projection.on_agent_observation(
            {
                "session_id": "session-1",
                "execution_id": "exec-1",
                "observation_type": ObservationType.TOOL_EXECUTION_COMPLETED.value,
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
                "observation_type": ObservationType.TOOL_EXECUTION_COMPLETED.value,
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


@pytest.mark.unit
class TestExtractedHelpers:
    """Tests for module-level helper functions extracted for complexity reduction."""

    def test_get_or_create_from_none(self) -> None:
        """_get_or_create returns new ExecutionCost when existing is None."""
        result = _get_or_create(None, "exec-new")
        assert result.execution_id == "exec-new"
        assert result.input_tokens == 0

    def test_get_or_create_from_dict(self) -> None:
        """_get_or_create reconstitutes from existing dict."""
        existing = ExecutionCost(execution_id="exec-1")
        existing.input_tokens = 500
        result = _get_or_create(existing.to_dict(), "exec-1")
        assert result.execution_id == "exec-1"
        assert result.input_tokens == 500

    def test_track_session_adds_new(self) -> None:
        """_track_session adds a new session_id."""
        ec = ExecutionCost(execution_id="exec-1")
        _track_session(ec, "sess-1")
        assert "sess-1" in ec.session_ids
        assert ec.session_count == 1

    def test_track_session_idempotent(self) -> None:
        """_track_session does not duplicate existing session_id."""
        ec = ExecutionCost(execution_id="exec-1")
        _track_session(ec, "sess-1")
        _track_session(ec, "sess-1")
        assert ec.session_count == 1

    def test_track_session_skips_none(self) -> None:
        """_track_session is a no-op for None session_id."""
        ec = ExecutionCost(execution_id="exec-1")
        _track_session(ec, None)
        assert ec.session_count == 0

    def test_update_started_at_sets_from_string(self) -> None:
        """_update_started_at parses ISO string."""
        ec = ExecutionCost(execution_id="exec-1")
        _update_started_at(ec, "2026-03-23T10:00:00")
        assert ec.started_at is not None
        assert ec.started_at.hour == 10

    def test_update_started_at_no_overwrite(self) -> None:
        """_update_started_at does not overwrite existing value."""
        ec = ExecutionCost(execution_id="exec-1")
        first = datetime(2026, 1, 1)
        ec.started_at = first
        _update_started_at(ec, "2026-03-23T10:00:00")
        assert ec.started_at == first

    def test_calculate_token_cost(self) -> None:
        """_calculate_token_cost computes correct cost."""
        cost = _calculate_token_cost(1_000_000, 1_000_000, 0, 0)
        # 1M input @ $3 + 1M output @ $15 = $18
        from decimal import Decimal

        assert cost == Decimal("18.00")

    def test_update_completed_at_sets_latest(self) -> None:
        """_update_completed_at updates to latest timestamp."""
        ec = ExecutionCost(execution_id="exec-1")
        _update_completed_at(ec, "2026-03-23T10:00:00")
        assert ec.completed_at is not None

        _update_completed_at(ec, "2026-03-23T09:00:00")
        # Should keep the later time
        assert ec.completed_at.hour == 10

    def test_update_completed_at_skips_none(self) -> None:
        """_update_completed_at is a no-op for None."""
        ec = ExecutionCost(execution_id="exec-1")
        _update_completed_at(ec, None)
        assert ec.completed_at is None
