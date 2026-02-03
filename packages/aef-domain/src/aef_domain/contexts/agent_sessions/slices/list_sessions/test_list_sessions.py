"""Tests for SessionListProjection.

These tests verify that the projection correctly handles events from the event store,
where datetime fields are serialized as ISO strings (not datetime objects).

This is critical because:
1. Events are serialized to JSON when saved to the event store
2. When read back, datetime fields come as strings, not datetime objects
3. Projections must handle both formats gracefully
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aef_domain.contexts.agent_sessions.slices.list_sessions.projection import (
    SessionListProjection,
)


class MockProjectionStore:
    """Mock projection store for testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {}

    async def save(self, projection_name: str, key: str, data: dict) -> None:
        if projection_name not in self._data:
            self._data[projection_name] = {}
        self._data[projection_name][key] = data

    async def get(self, projection_name: str, key: str) -> dict | None:
        return self._data.get(projection_name, {}).get(key)

    async def get_all(self, projection_name: str) -> list[dict]:
        return list(self._data.get(projection_name, {}).values())

    async def query(
        self,
        projection_name: str,
        filters: dict | None = None,
        order_by: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        items = list(self._data.get(projection_name, {}).values())
        if filters:
            items = [item for item in items if all(item.get(k) == v for k, v in filters.items())]
        return items[offset : offset + limit]


@pytest.fixture
def mock_store() -> MockProjectionStore:
    """Create a mock projection store."""
    return MockProjectionStore()


@pytest.fixture
def projection(mock_store: MockProjectionStore) -> SessionListProjection:
    """Create a SessionListProjection with mock store."""
    return SessionListProjection(mock_store)


@pytest.mark.unit
class TestSessionListProjection:
    """Tests for SessionListProjection event handlers."""

    @pytest.mark.asyncio
    async def test_on_session_started_with_datetime_object(
        self, projection: SessionListProjection, mock_store: MockProjectionStore
    ) -> None:
        """Test handling SessionStarted with datetime object (direct call)."""
        event_data = {
            "session_id": "session-123",
            "workflow_id": "workflow-456",
            "agent_provider": "claude",
            "started_at": datetime.now(UTC),  # datetime object
        }

        await projection.on_session_started(event_data)

        result = await mock_store.get("session_summaries", "session-123")
        assert result is not None
        assert result["id"] == "session-123"
        assert result["workflow_id"] == "workflow-456"
        assert result["agent_type"] == "claude"
        assert result["status"] == "running"
        assert "started_at" in result

    @pytest.mark.asyncio
    async def test_on_session_started_with_iso_string(
        self, projection: SessionListProjection, mock_store: MockProjectionStore
    ) -> None:
        """Test handling SessionStarted with ISO string (from event store).

        This is the critical test that catches the datetime serialization bug.
        When events come from the event store, datetime fields are strings.
        """
        event_data = {
            "session_id": "session-789",
            "workflow_id": "workflow-abc",
            "agent_provider": "openai",
            "started_at": "2025-12-04T01:00:00.000000Z",  # ISO string!
        }

        # This should NOT raise "'str' object has no attribute 'isoformat'"
        await projection.on_session_started(event_data)

        result = await mock_store.get("session_summaries", "session-789")
        assert result is not None
        assert result["id"] == "session-789"
        assert result["workflow_id"] == "workflow-abc"
        assert result["started_at"] == "2025-12-04T01:00:00.000000Z"

    @pytest.mark.asyncio
    async def test_on_session_started_with_none_datetime(
        self, projection: SessionListProjection, mock_store: MockProjectionStore
    ) -> None:
        """Test handling SessionStarted with None datetime."""
        event_data = {
            "session_id": "session-none",
            "workflow_id": "workflow-none",
            "agent_provider": "claude",
            "started_at": None,
        }

        await projection.on_session_started(event_data)

        result = await mock_store.get("session_summaries", "session-none")
        assert result is not None
        assert result["started_at"] is None

    @pytest.mark.asyncio
    async def test_on_session_completed_with_iso_string(
        self, projection: SessionListProjection, mock_store: MockProjectionStore
    ) -> None:
        """Test handling SessionCompleted with ISO string datetime."""
        # First create a session
        await projection.on_session_started(
            {
                "session_id": "session-complete",
                "workflow_id": "workflow-complete",
                "agent_provider": "claude",
                "started_at": "2025-12-04T01:00:00.000000Z",
            }
        )

        # Complete with ISO string datetime
        await projection.on_session_completed(
            {
                "session_id": "session-complete",
                "status": "completed",
                "completed_at": "2025-12-04T02:00:00.000000Z",  # ISO string!
                "total_tokens": 1500,
                "total_cost_usd": "0.015",
            }
        )

        result = await mock_store.get("session_summaries", "session-complete")
        assert result is not None
        assert result["status"] == "completed"
        assert result["completed_at"] == "2025-12-04T02:00:00.000000Z"
        assert result["total_tokens"] == 1500

    @pytest.mark.asyncio
    async def test_on_session_completed_extracts_token_breakdown(
        self, projection: SessionListProjection, mock_store: MockProjectionStore
    ) -> None:
        """Test that session completed extracts input/output token breakdown."""
        # Create session
        await projection.on_session_started(
            {
                "session_id": "session-tokens",
                "workflow_id": "workflow-tokens",
                "agent_provider": "claude",
                "started_at": "2025-12-04T01:00:00.000000Z",
            }
        )

        # Complete with token breakdown
        await projection.on_session_completed(
            {
                "session_id": "session-tokens",
                "status": "completed",
                "completed_at": "2025-12-04T01:30:00.000000Z",
                "total_tokens": 2500,
                "total_input_tokens": 1000,
                "total_output_tokens": 1500,
                "total_cost_usd": "0.025",
            }
        )

        result = await mock_store.get("session_summaries", "session-tokens")
        assert result is not None
        assert result["total_tokens"] == 2500
        assert result["input_tokens"] == 1000
        assert result["output_tokens"] == 1500

    @pytest.mark.asyncio
    async def test_on_session_completed_calculates_duration(
        self, projection: SessionListProjection, mock_store: MockProjectionStore
    ) -> None:
        """Test that session completed calculates duration from timestamps."""
        # Create session
        await projection.on_session_started(
            {
                "session_id": "session-duration",
                "workflow_id": "workflow-duration",
                "agent_provider": "claude",
                "started_at": "2025-12-04T01:00:00.000000Z",
            }
        )

        # Complete 1 hour later
        await projection.on_session_completed(
            {
                "session_id": "session-duration",
                "status": "completed",
                "completed_at": "2025-12-04T02:00:00.000000Z",
                "total_tokens": 1000,
                "total_cost_usd": "0.01",
            }
        )

        result = await mock_store.get("session_summaries", "session-duration")
        assert result is not None
        assert result["duration_seconds"] == 3600.0  # 1 hour = 3600 seconds

    @pytest.mark.asyncio
    async def test_on_session_started_stores_phase_id(
        self, projection: SessionListProjection, mock_store: MockProjectionStore
    ) -> None:
        """Test that session started stores phase_id from event."""
        await projection.on_session_started(
            {
                "session_id": "session-phase",
                "workflow_id": "workflow-phase",
                "agent_provider": "claude",
                "started_at": "2025-12-04T01:00:00.000000Z",
                "phase_id": "phase-123",
            }
        )

        result = await mock_store.get("session_summaries", "session-phase")
        assert result is not None
        assert result["phase_id"] == "phase-123"

    @pytest.mark.asyncio
    async def test_on_operation_recorded_accumulates_tokens(
        self, projection: SessionListProjection, mock_store: MockProjectionStore
    ) -> None:
        """Test that operation events correctly accumulate token counts."""
        # Create session
        await projection.on_session_started(
            {
                "session_id": "session-ops",
                "workflow_id": "workflow-ops",
                "agent_provider": "claude",
                "started_at": "2025-12-04T01:00:00.000000Z",
            }
        )

        # Record operations
        await projection.on_operation_recorded(
            {
                "session_id": "session-ops",
                "tokens_used": 100,
                "cost_usd": "0.001",
            }
        )

        await projection.on_operation_recorded(
            {
                "session_id": "session-ops",
                "tokens_used": 200,
                "cost_usd": "0.002",
            }
        )

        result = await mock_store.get("session_summaries", "session-ops")
        assert result is not None
        assert result["total_tokens"] == 300
        assert float(result["total_cost_usd"]) == pytest.approx(0.003, rel=1e-6)

    @pytest.mark.asyncio
    async def test_query_sessions_by_workflow(
        self,
        projection: SessionListProjection,
        mock_store: MockProjectionStore,
    ) -> None:
        """Test querying sessions filtered by workflow."""
        # Create sessions for different workflows
        await projection.on_session_started(
            {
                "session_id": "session-1",
                "workflow_id": "workflow-a",
                "agent_provider": "claude",
                "started_at": "2025-12-04T01:00:00Z",
            }
        )
        await projection.on_session_started(
            {
                "session_id": "session-2",
                "workflow_id": "workflow-b",
                "agent_provider": "claude",
                "started_at": "2025-12-04T01:00:00Z",
            }
        )
        await projection.on_session_started(
            {
                "session_id": "session-3",
                "workflow_id": "workflow-a",
                "agent_provider": "openai",
                "started_at": "2025-12-04T01:00:00Z",
            }
        )

        # Query for workflow-a
        results = await projection.get_by_workflow("workflow-a")
        assert len(results) == 2
        assert all(s.workflow_id == "workflow-a" for s in results)


class TestSessionSummaryToDict:
    """Tests for SessionSummary.to_dict() datetime handling."""

    def test_to_dict_with_datetime_object(self) -> None:
        """Test to_dict with actual datetime objects."""
        from aef_domain.contexts.agent_sessions.domain.read_models.session_summary import (
            SessionSummary,
        )

        now = datetime.now(UTC)
        summary = SessionSummary(
            id="test-1",
            workflow_id="wf-1",
            agent_type="claude",
            status="running",
            total_tokens=100,
            total_cost_usd=Decimal("0.01"),
            started_at=now,
            completed_at=None,
        )

        result = summary.to_dict()
        assert result["started_at"] == now.isoformat()
        assert result["completed_at"] is None

    def test_to_dict_with_iso_string(self) -> None:
        """Test to_dict when datetime fields are already strings.

        This simulates the scenario where a SessionSummary is created
        from event store data where datetimes are ISO strings.
        """
        from aef_domain.contexts.agent_sessions.domain.read_models.session_summary import (
            SessionSummary,
        )

        iso_string = "2025-12-04T01:00:00.000000Z"
        summary = SessionSummary(
            id="test-2",
            workflow_id="wf-2",
            agent_type="openai",
            status="completed",
            total_tokens=500,
            total_cost_usd=Decimal("0.05"),
            started_at=iso_string,  # type: ignore[arg-type] - intentionally testing string
            completed_at=iso_string,  # type: ignore[arg-type]
        )

        # This should NOT raise "'str' object has no attribute 'isoformat'"
        result = summary.to_dict()
        assert result["started_at"] == iso_string
        assert result["completed_at"] == iso_string

    def test_to_dict_with_none_values(self) -> None:
        """Test to_dict with None datetime values."""
        from aef_domain.contexts.agent_sessions.domain.read_models.session_summary import (
            SessionSummary,
        )

        summary = SessionSummary(
            id="test-3",
            workflow_id="wf-3",
            agent_type="claude",
            status="pending",
            total_tokens=0,
            total_cost_usd=Decimal("0"),
            started_at=None,
            completed_at=None,
        )

        result = summary.to_dict()
        assert result["started_at"] is None
        assert result["completed_at"] is None
