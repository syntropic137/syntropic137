"""Tests for ExecutionCostProjection with unified AgentObservation model."""

from datetime import UTC, datetime
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


@pytest.mark.unit
class TestExecutionCostQueryServiceBuildFromTokenUsage:
    """Regression tests for _build_from_token_usage duration calculation.

    Regression: before the fix, _build_from_token_usage() omitted duration_ms,
    so 'syn costs execution <id>' always showed 'Duration: 0ms' for executions
    whose cost was computed from token_usage events (i.e. no session_summary yet).
    """

    def test_duration_computed_from_timestamps(self) -> None:
        """duration_ms is computed from started_at / last_observation when both present."""
        from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
            ExecutionCostQueryService,
        )

        service = ExecutionCostQueryService(pool=None)  # type: ignore[arg-type]
        started = datetime(2026, 4, 8, 20, 14, 0, tzinfo=UTC)
        completed = datetime(2026, 4, 8, 20, 16, 30, tzinfo=UTC)  # 2.5 min

        row: dict[str, object] = {
            "execution_id": "exec-1",
            "total_input": 1000,
            "total_output": 500,
            "cache_creation": 0,
            "cache_read": 0,
            "session_count": 1,
            "session_ids": ["s-1"],
            "started_at": started,
            "last_observation": completed,
        }
        result = service._build_from_token_usage(row, tool_counts={})

        assert result.duration_ms == pytest.approx(150_000.0)  # 2.5 min = 150,000 ms

    def test_duration_zero_when_no_timestamps(self) -> None:
        """duration_ms defaults to 0 when timestamps are missing (in-progress execution)."""
        from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
            ExecutionCostQueryService,
        )

        service = ExecutionCostQueryService(pool=None)  # type: ignore[arg-type]

        row: dict[str, object] = {
            "execution_id": "exec-2",
            "total_input": 500,
            "total_output": 200,
            "cache_creation": 0,
            "cache_read": 0,
            "session_count": 1,
            "session_ids": ["s-2"],
            "started_at": None,
            "last_observation": None,
        }
        result = service._build_from_token_usage(row, tool_counts={})

        assert result.duration_ms == 0.0


@pytest.mark.unit
class TestExecutionCostQueryServiceBuildFromSummary:
    """Regression tests for _build_from_summary duration calculation.

    Regression: session_summary event payloads rarely include duration_ms, so
    the SQL SUM of that field was always 0. The fix falls back to computing
    duration from MIN(time)/MAX(time) timestamps available in the same query.
    """

    def test_duration_falls_back_to_timestamps_when_summary_field_absent(self) -> None:
        """duration_ms is derived from started_at/completed_at when duration_ms_val is 0."""
        from decimal import Decimal

        from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
            ExecutionCostQueryService,
        )

        service = ExecutionCostQueryService(pool=None)  # type: ignore[arg-type]
        started = datetime(2026, 4, 8, 21, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 4, 8, 21, 5, 0, tzinfo=UTC)  # 5 min

        row: dict[str, object] = {
            "execution_id": "exec-s1",
            "total_input": 5000,
            "total_output": 2000,
            "cache_creation": 0,
            "cache_read": 0,
            "sdk_cost": Decimal("0.42"),
            "duration_ms_val": 0,  # not present in payload — the broken case
            "total_turns": 3,
            "session_count": 2,
            "session_ids": ["s-a", "s-b"],
            "started_at": started,
            "completed_at": completed,
        }
        result = service._build_from_summary(row, tool_counts={}, phase_map={}, model_map={})

        assert result.duration_ms == pytest.approx(300_000.0)  # 5 min = 300,000 ms

    def test_duration_uses_summary_field_when_present(self) -> None:
        """duration_ms uses duration_ms_val from session summaries when non-zero."""
        from decimal import Decimal

        from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
            ExecutionCostQueryService,
        )

        service = ExecutionCostQueryService(pool=None)  # type: ignore[arg-type]
        started = datetime(2026, 4, 8, 21, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 4, 8, 21, 5, 0, tzinfo=UTC)

        row: dict[str, object] = {
            "execution_id": "exec-s2",
            "total_input": 1000,
            "total_output": 500,
            "cache_creation": 0,
            "cache_read": 0,
            "sdk_cost": Decimal("0.10"),
            "duration_ms_val": 120_000,  # 2 min from session summary payload
            "total_turns": 1,
            "session_count": 1,
            "session_ids": ["s-c"],
            "started_at": started,
            "completed_at": completed,
        }
        result = service._build_from_summary(row, tool_counts={}, phase_map={}, model_map={})

        # Should use the explicit value, not recompute from timestamps
        assert result.duration_ms == pytest.approx(120_000.0)
