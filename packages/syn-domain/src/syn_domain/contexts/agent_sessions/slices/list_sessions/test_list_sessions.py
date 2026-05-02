"""Tests for SessionListProjection.

These tests verify that the projection correctly handles events from the event store,
where datetime fields are serialized as ISO strings (not datetime objects).

This is critical because:
1. Events are serialized to JSON when saved to the event store
2. When read back, datetime fields come as strings, not datetime objects
3. Projections must handle both formats gracefully
"""

from datetime import UTC, datetime

import pytest

from syn_domain.contexts.agent_sessions.slices.list_sessions.projection import (
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
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[dict]:
        items = list(self._data.get(projection_name, {}).values())
        if filters:
            items = [item for item in items if all(item.get(k) == v for k, v in filters.items())]
        if limit is None:
            return items[offset:]
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

        # Record operations (cost is Lane 2 — not accumulated here, see #695)
        await projection.on_operation_recorded(
            {
                "session_id": "session-ops",
                "tokens_used": 100,
            }
        )

        await projection.on_operation_recorded(
            {
                "session_id": "session-ops",
                "tokens_used": 200,
            }
        )

        result = await mock_store.get("session_summaries", "session-ops")
        assert result is not None
        assert result["total_tokens"] == 300
        assert "total_cost_usd" not in result

    @pytest.mark.asyncio
    async def test_query_filters_by_started_after(
        self,
        projection: SessionListProjection,
        mock_store: MockProjectionStore,
    ) -> None:
        """started_after returns only sessions whose started_at >= bound."""
        await projection.on_session_started(
            {
                "session_id": "old",
                "workflow_id": "wf",
                "agent_provider": "claude",
                "started_at": "2026-04-18T08:00:00+00:00",
            }
        )
        await projection.on_session_started(
            {
                "session_id": "new",
                "workflow_id": "wf",
                "agent_provider": "claude",
                "started_at": "2026-04-18T12:00:00+00:00",
            }
        )

        bound = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
        results = await projection.query(started_after=bound)
        assert {s.id for s in results} == {"new"}

    @pytest.mark.asyncio
    async def test_query_filters_by_started_before(
        self,
        projection: SessionListProjection,
        mock_store: MockProjectionStore,
    ) -> None:
        """started_before returns only sessions whose started_at <= bound."""
        await projection.on_session_started(
            {
                "session_id": "old",
                "workflow_id": "wf",
                "agent_provider": "claude",
                "started_at": "2026-04-18T08:00:00+00:00",
            }
        )
        await projection.on_session_started(
            {
                "session_id": "new",
                "workflow_id": "wf",
                "agent_provider": "claude",
                "started_at": "2026-04-18T12:00:00+00:00",
            }
        )

        bound = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
        results = await projection.query(started_before=bound)
        assert {s.id for s in results} == {"old"}

    @pytest.mark.asyncio
    async def test_query_filters_by_time_window_intersection(
        self,
        projection: SessionListProjection,
        mock_store: MockProjectionStore,
    ) -> None:
        """started_after + started_before together yield the intersection."""
        for sid, started in [
            ("a", "2026-04-18T08:00:00+00:00"),
            ("b", "2026-04-18T11:00:00+00:00"),
            ("c", "2026-04-18T13:00:00+00:00"),
        ]:
            await projection.on_session_started(
                {
                    "session_id": sid,
                    "workflow_id": "wf",
                    "agent_provider": "claude",
                    "started_at": started,
                }
            )

        results = await projection.query(
            started_after=datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC),
            started_before=datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC),
        )
        assert {s.id for s in results} == {"b"}

    @pytest.mark.asyncio
    async def test_query_multi_status_or(
        self,
        projection: SessionListProjection,
        mock_store: MockProjectionStore,
    ) -> None:
        """statuses=[a,b] returns sessions in either state (OR'd)."""
        for sid, status in [("a", "running"), ("b", "completed"), ("c", "failed")]:
            await projection.on_session_started(
                {
                    "session_id": sid,
                    "workflow_id": "wf",
                    "agent_provider": "claude",
                    "started_at": "2026-04-18T08:00:00+00:00",
                }
            )
            data = await mock_store.get("session_summaries", sid)
            assert data is not None
            data["status"] = status
            await mock_store.save("session_summaries", sid, data)

        results = await projection.query(statuses=["running", "failed"])
        assert {s.id for s in results} == {"a", "c"}

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
        from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
            SessionSummary,
        )

        now = datetime.now(UTC)
        summary = SessionSummary(
            id="test-1",
            workflow_id="wf-1",
            agent_type="claude",
            status="running",
            total_tokens=100,
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
        from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
            SessionSummary,
        )

        iso_string = "2025-12-04T01:00:00.000000Z"
        summary = SessionSummary(
            id="test-2",
            workflow_id="wf-2",
            agent_type="openai",
            status="completed",
            total_tokens=500,
            started_at=iso_string,  # type: ignore[arg-type] - intentionally testing string
            completed_at=iso_string,  # type: ignore[arg-type]
        )

        # This should NOT raise "'str' object has no attribute 'isoformat'"
        result = summary.to_dict()
        assert result["started_at"] == iso_string
        assert result["completed_at"] == iso_string

    def test_to_dict_with_none_values(self) -> None:
        """Test to_dict with None datetime values."""
        from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
            SessionSummary,
        )

        summary = SessionSummary(
            id="test-3",
            workflow_id="wf-3",
            agent_type="claude",
            status="pending",
            total_tokens=0,
            started_at=None,
            completed_at=None,
        )

        result = summary.to_dict()
        assert result["started_at"] is None
        assert result["completed_at"] is None


# ---------------------------------------------------------------------------
# Subagent tests — moved from syn_tests/integration/test_subagent_observability.py (#115)
# ---------------------------------------------------------------------------

from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (  # noqa: E402
    SubagentRecord,
)


@pytest.mark.unit
class TestSubagentRecord:
    """Test SubagentRecord dataclass."""

    def test_create_subagent_record(self) -> None:
        """Can create a SubagentRecord with all fields."""
        record = SubagentRecord(
            subagent_tool_use_id="toolu_123",
            agent_name="research-agent",
            started_at="2025-01-08T10:00:00Z",
            stopped_at="2025-01-08T10:01:00Z",
            duration_ms=60000,
            tools_used={"Read": 5, "Write": 2},
            success=True,
        )

        assert record.subagent_tool_use_id == "toolu_123"
        assert record.agent_name == "research-agent"
        assert record.duration_ms == 60000
        assert record.tools_used["Read"] == 5
        assert record.success is True

    def test_subagent_record_from_dict(self) -> None:
        """Can create SubagentRecord from dictionary."""
        data = {
            "subagent_tool_use_id": "toolu_456",
            "agent_name": "coding-agent",
            "started_at": "2025-01-08T10:00:00Z",
            "stopped_at": "2025-01-08T10:02:00Z",
            "duration_ms": 120000,
            "tools_used": {"Bash": 10, "Edit": 3},
            "success": True,
        }

        record = SubagentRecord.from_dict(data)

        assert record.subagent_tool_use_id == "toolu_456"
        assert record.agent_name == "coding-agent"
        assert record.duration_ms == 120000
        assert record.tools_used["Bash"] == 10

    def test_subagent_record_to_dict(self) -> None:
        """SubagentRecord can be serialized to dict."""
        record = SubagentRecord(
            subagent_tool_use_id="toolu_789",
            agent_name="test-agent",
            duration_ms=5000,
            tools_used={"Read": 1},
            success=True,
        )

        data = record.to_dict()

        assert data["subagent_tool_use_id"] == "toolu_789"
        assert data["agent_name"] == "test-agent"
        assert data["duration_ms"] == 5000
        assert data["tools_used"] == {"Read": 1}


@pytest.mark.unit
class TestSessionSummarySubagentFields:
    """Test SessionSummary subagent-related fields."""

    def test_session_summary_with_subagents(self) -> None:
        """SessionSummary can include subagent metrics."""
        from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
            SessionSummary as DomainSessionSummary,
        )

        subagent1 = SubagentRecord(
            subagent_tool_use_id="toolu_1",
            agent_name="research",
            duration_ms=30000,
            tools_used={"Read": 5},
            success=True,
        )
        subagent2 = SubagentRecord(
            subagent_tool_use_id="toolu_2",
            agent_name="coding",
            duration_ms=60000,
            tools_used={"Bash": 10, "Edit": 3},
            success=True,
        )

        summary = DomainSessionSummary(
            id="session-123",
            workflow_id="workflow-456",
            agent_type="claude-3-5-sonnet",
            status="completed",
            total_tokens=10000,
            started_at=None,
            completed_at=None,
            subagent_count=2,
            subagents=(subagent1, subagent2),
            tools_by_subagent={
                "research": {"Read": 5},
                "coding": {"Bash": 10, "Edit": 3},
            },
            num_turns=5,
        )

        assert summary.subagent_count == 2
        assert len(summary.subagents) == 2
        assert summary.subagents[0].agent_name == "research"
        assert summary.subagents[1].agent_name == "coding"
        assert summary.tools_by_subagent["coding"]["Bash"] == 10
        assert summary.num_turns == 5

    def test_session_summary_from_dict_with_subagents(self) -> None:
        """SessionSummary.from_dict correctly parses subagent data."""
        from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
            SessionSummary as DomainSessionSummary,
        )

        data = {
            "id": "session-abc",
            "workflow_id": "workflow-xyz",
            "agent_type": "claude-3-5-sonnet",
            "status": "completed",
            "total_tokens": 5000,
            "total_cost_usd": "0.025",
            "subagent_count": 1,
            "subagents": [
                {
                    "subagent_tool_use_id": "toolu_test",
                    "agent_name": "helper",
                    "duration_ms": 15000,
                    "tools_used": {"Read": 3},
                    "success": True,
                }
            ],
            "tools_by_subagent": {"helper": {"Read": 3}},
            "num_turns": 3,
            "duration_api_ms": 12500,
        }

        summary = DomainSessionSummary.from_dict(data)

        assert summary.subagent_count == 1
        assert len(summary.subagents) == 1
        assert summary.subagents[0].agent_name == "helper"
        assert summary.subagents[0].duration_ms == 15000
        assert summary.tools_by_subagent["helper"]["Read"] == 3
        assert summary.num_turns == 3
        assert summary.duration_api_ms == 12500

    def test_session_summary_to_dict_with_subagents(self) -> None:
        """SessionSummary.to_dict correctly serializes subagent data."""
        from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
            SessionSummary as DomainSessionSummary,
        )

        subagent = SubagentRecord(
            subagent_tool_use_id="toolu_ser",
            agent_name="serialization-test",
            duration_ms=1000,
            tools_used={"Test": 1},
            success=True,
        )

        summary = DomainSessionSummary(
            id="session-ser",
            workflow_id="workflow-ser",
            agent_type="test",
            status="completed",
            total_tokens=100,
            started_at=None,
            completed_at=None,
            subagent_count=1,
            subagents=(subagent,),
            tools_by_subagent={"serialization-test": {"Test": 1}},
            num_turns=1,
            duration_api_ms=500,
        )

        data = summary.to_dict()

        assert data["subagent_count"] == 1
        assert len(data["subagents"]) == 1
        assert data["subagents"][0]["agent_name"] == "serialization-test"
        assert data["tools_by_subagent"]["serialization-test"]["Test"] == 1
        assert data["num_turns"] == 1
        assert data["duration_api_ms"] == 500


@pytest.mark.unit
class TestProjectionSubagentHandlers:
    """Test projection handlers for subagent events."""

    @pytest.mark.asyncio
    async def test_session_list_projection_handles_subagent_started(self) -> None:
        """SessionListProjection.on_subagent_started creates subagent record."""
        from unittest.mock import AsyncMock

        mock_store = AsyncMock()
        mock_store.get.return_value = {
            "id": "session-123",
            "workflow_id": "workflow-456",
            "status": "running",
            "subagents": [],
            "subagent_count": 0,
        }

        proj = SessionListProjection(mock_store)

        await proj.on_subagent_started(
            {
                "session_id": "session-123",
                "subagent_tool_use_id": "toolu_abc",
                "agent_name": "research-agent",
                "timestamp": "2025-01-08T10:00:00Z",
            }
        )

        mock_store.save.assert_called_once()
        call_args = mock_store.save.call_args
        saved_data = call_args[0][2]

        assert saved_data["subagent_count"] == 1
        assert len(saved_data["subagents"]) == 1
        assert saved_data["subagents"][0]["agent_name"] == "research-agent"

    @pytest.mark.asyncio
    async def test_session_list_projection_handles_subagent_stopped(self) -> None:
        """SessionListProjection.on_subagent_stopped updates subagent record."""
        from unittest.mock import AsyncMock

        mock_store = AsyncMock()
        mock_store.get.return_value = {
            "id": "session-123",
            "workflow_id": "workflow-456",
            "status": "running",
            "subagents": [
                {
                    "subagent_tool_use_id": "toolu_abc",
                    "agent_name": "research-agent",
                    "started_at": "2025-01-08T10:00:00Z",
                    "stopped_at": None,
                    "duration_ms": None,
                    "tools_used": {},
                    "success": True,
                }
            ],
            "subagent_count": 1,
            "tools_by_subagent": {},
        }

        proj = SessionListProjection(mock_store)

        await proj.on_subagent_stopped(
            {
                "session_id": "session-123",
                "subagent_tool_use_id": "toolu_abc",
                "agent_name": "research-agent",
                "timestamp": "2025-01-08T10:01:00Z",
                "duration_ms": 60000,
                "tools_used": {"Read": 5, "Write": 2},
                "success": True,
            }
        )

        mock_store.save.assert_called_once()
        call_args = mock_store.save.call_args
        saved_data = call_args[0][2]

        assert saved_data["subagents"][0]["duration_ms"] == 60000
        assert saved_data["subagents"][0]["tools_used"]["Read"] == 5
        assert "research-agent" in saved_data["tools_by_subagent"]
        assert saved_data["tools_by_subagent"]["research-agent"]["Read"] == 5
