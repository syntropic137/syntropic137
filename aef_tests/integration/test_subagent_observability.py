"""Integration tests for subagent observability.

Tests the subagent event flow through the observability pipeline:
1. EventParser detects Task tool usage as subagent events
2. Events flow through projections
3. SessionSummary includes subagent metrics

See: agentic_isolation v0.3.0 - Subagent Observability
"""

from __future__ import annotations

import pytest

from aef_domain.contexts.sessions.domain.read_models.session_summary import (
    SessionSummary,
    SubagentRecord,
)
from aef_shared.events import SUBAGENT_STARTED, SUBAGENT_STOPPED


class TestSubagentEventTypes:
    """Test subagent event type constants."""

    def test_subagent_started_constant(self) -> None:
        """SUBAGENT_STARTED constant is correctly defined."""
        assert SUBAGENT_STARTED == "subagent_started"

    def test_subagent_stopped_constant(self) -> None:
        """SUBAGENT_STOPPED constant is correctly defined."""
        assert SUBAGENT_STOPPED == "subagent_stopped"


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


class TestSessionSummarySubagentFields:
    """Test SessionSummary subagent-related fields."""

    def test_session_summary_with_subagents(self) -> None:
        """SessionSummary can include subagent metrics."""
        from decimal import Decimal

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

        summary = SessionSummary(
            id="session-123",
            workflow_id="workflow-456",
            agent_type="claude-3-5-sonnet",
            status="completed",
            total_tokens=10000,
            total_cost_usd=Decimal("0.05"),
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

        summary = SessionSummary.from_dict(data)

        assert summary.subagent_count == 1
        assert len(summary.subagents) == 1
        assert summary.subagents[0].agent_name == "helper"
        assert summary.subagents[0].duration_ms == 15000
        assert summary.tools_by_subagent["helper"]["Read"] == 3
        assert summary.num_turns == 3
        assert summary.duration_api_ms == 12500

    def test_session_summary_to_dict_with_subagents(self) -> None:
        """SessionSummary.to_dict correctly serializes subagent data."""
        from decimal import Decimal

        subagent = SubagentRecord(
            subagent_tool_use_id="toolu_ser",
            agent_name="serialization-test",
            duration_ms=1000,
            tools_used={"Test": 1},
            success=True,
        )

        summary = SessionSummary(
            id="session-ser",
            workflow_id="workflow-ser",
            agent_type="test",
            status="completed",
            total_tokens=100,
            total_cost_usd=Decimal("0.001"),
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


class TestEventModelMapping:
    """Test event type mapping includes subagent events."""

    def test_subagent_events_in_mapping(self) -> None:
        """AgentEvent.from_dict correctly maps subagent event types."""
        from aef_adapters.events.models import AgentEvent

        # Test subagent_started event
        started_event = AgentEvent.from_dict(
            {
                "type": "subagent_started",
                "session_id": "session-123",
                "agent_name": "test-subagent",
                "subagent_tool_use_id": "toolu_abc",
                "timestamp": "2025-01-08T10:00:00Z",
            }
        )

        assert started_event.event_type == "subagent_started"
        assert started_event.data.get("agent_name") == "test-subagent"

        # Test subagent_stopped event
        stopped_event = AgentEvent.from_dict(
            {
                "type": "subagent_stopped",
                "session_id": "session-123",
                "agent_name": "test-subagent",
                "subagent_tool_use_id": "toolu_abc",
                "duration_ms": 5000,
                "tools_used": {"Read": 2},
                "timestamp": "2025-01-08T10:00:05Z",
            }
        )

        assert stopped_event.event_type == "subagent_stopped"
        assert stopped_event.data.get("duration_ms") == 5000
        assert stopped_event.data.get("tools_used") == {"Read": 2}


class TestContainerRunnerSubagentEvents:
    """Test ContainerAgentRunner subagent event handling."""

    def test_subagent_event_dataclasses_exist(self) -> None:
        """ContainerSubagentStarted and ContainerSubagentStopped exist."""
        from aef_adapters.agents.container_runner import (
            ContainerSubagentStarted,
            ContainerSubagentStopped,
        )

        # Test ContainerSubagentStarted
        started = ContainerSubagentStarted(
            agent_name="test-agent",
            subagent_tool_use_id="toolu_123",
        )
        assert started.agent_name == "test-agent"
        assert started.subagent_tool_use_id == "toolu_123"

        # Test ContainerSubagentStopped
        stopped = ContainerSubagentStopped(
            agent_name="test-agent",
            subagent_tool_use_id="toolu_123",
            duration_ms=5000,
            tools_used={"Read": 3},
            success=True,
        )
        assert stopped.duration_ms == 5000
        assert stopped.tools_used["Read"] == 3
        assert stopped.success is True


@pytest.mark.integration
class TestProjectionSubagentHandlers:
    """Test projection handlers for subagent events."""

    @pytest.mark.asyncio
    async def test_session_list_projection_handles_subagent_started(self) -> None:
        """SessionListProjection.on_subagent_started creates subagent record."""
        from unittest.mock import AsyncMock

        from aef_domain.contexts.sessions.slices.list_sessions import (
            SessionListProjection,
        )

        # Create mock store
        mock_store = AsyncMock()
        mock_store.get.return_value = {
            "id": "session-123",
            "workflow_id": "workflow-456",
            "status": "running",
            "subagents": [],
            "subagent_count": 0,
        }

        projection = SessionListProjection(mock_store)

        # Handle subagent started event
        await projection.on_subagent_started(
            {
                "session_id": "session-123",
                "subagent_tool_use_id": "toolu_abc",
                "agent_name": "research-agent",
                "timestamp": "2025-01-08T10:00:00Z",
            }
        )

        # Verify store.save was called with updated data
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

        from aef_domain.contexts.sessions.slices.list_sessions import (
            SessionListProjection,
        )

        # Create mock store with existing subagent
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

        projection = SessionListProjection(mock_store)

        # Handle subagent stopped event
        await projection.on_subagent_stopped(
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

        # Verify store.save was called with updated data
        mock_store.save.assert_called_once()
        call_args = mock_store.save.call_args
        saved_data = call_args[0][2]

        # Check subagent was updated
        assert saved_data["subagents"][0]["duration_ms"] == 60000
        assert saved_data["subagents"][0]["tools_used"]["Read"] == 5

        # Check tools_by_subagent was aggregated
        assert "research-agent" in saved_data["tools_by_subagent"]
        assert saved_data["tools_by_subagent"]["research-agent"]["Read"] == 5
