"""Tests for event types and ID generation."""

from datetime import UTC, datetime

import pytest

from syn_collector.events.ids import (
    generate_event_id,
    generate_session_event_id,
    generate_token_event_id,
    generate_tool_event_id,
)
from syn_collector.events.types import (
    BatchResponse,
    CollectedEvent,
    EventBatch,
    EventType,
)


@pytest.mark.unit
class TestEventTypes:
    """Tests for event type definitions."""

    def test_event_type_values(self) -> None:
        """Verify event type enum values."""
        assert EventType.SESSION_STARTED.value == "session_started"
        assert EventType.TOOL_EXECUTION_STARTED.value == "tool_execution_started"
        assert EventType.TOKEN_USAGE.value == "token_usage"

    def test_collected_event_creation(self) -> None:
        """Test creating a CollectedEvent."""
        event = CollectedEvent(
            event_id="abc123def456789012345678901234",
            event_type=EventType.TOOL_EXECUTION_STARTED,
            session_id="session-123",
            timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            data={"tool_name": "Read", "tool_use_id": "toolu_01ABC"},
        )

        assert event.event_id == "abc123def456789012345678901234"
        assert event.event_type == EventType.TOOL_EXECUTION_STARTED
        assert event.session_id == "session-123"
        assert event.data["tool_name"] == "Read"

    def test_collected_event_is_frozen(self) -> None:
        """Verify CollectedEvent is immutable."""
        event = CollectedEvent(
            event_id="abc123def456789012345678901234",
            event_type=EventType.SESSION_STARTED,
            session_id="session-123",
            timestamp=datetime.now(UTC),
            data={},
        )

        from pydantic import ValidationError

        with pytest.raises(ValidationError):  # ValidationError for frozen model
            event.session_id = "new-session"  # type: ignore

    def test_event_batch_creation(self) -> None:
        """Test creating an EventBatch."""
        event = CollectedEvent(
            event_id="abc123def456789012345678901234",
            event_type=EventType.SESSION_STARTED,
            session_id="session-123",
            timestamp=datetime.now(UTC),
            data={},
        )

        batch = EventBatch(
            agent_id="agent-001",
            batch_id="batch-20250101",
            events=[event],
        )

        assert batch.agent_id == "agent-001"
        assert len(batch.events) == 1

    def test_batch_response_creation(self) -> None:
        """Test creating a BatchResponse."""
        response = BatchResponse(
            accepted=5,
            duplicates=2,
            batch_id="batch-001",
        )

        assert response.accepted == 5
        assert response.duplicates == 2


class TestEventIdGeneration:
    """Tests for deterministic event ID generation."""

    def test_generate_event_id_is_deterministic(self) -> None:
        """Same inputs should produce same ID."""
        timestamp = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        id1 = generate_event_id("session-123", "test_event", timestamp, "content")
        id2 = generate_event_id("session-123", "test_event", timestamp, "content")

        assert id1 == id2

    def test_generate_event_id_differs_with_content(self) -> None:
        """Different content should produce different ID."""
        timestamp = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        id1 = generate_event_id("session-123", "test_event", timestamp, "content1")
        id2 = generate_event_id("session-123", "test_event", timestamp, "content2")

        assert id1 != id2

    def test_generate_event_id_length(self) -> None:
        """Event ID should be 32 characters."""
        timestamp = datetime.now(UTC)
        event_id = generate_event_id("session", "type", timestamp)

        assert len(event_id) == 32

    def test_generate_tool_event_id(self) -> None:
        """Test tool event ID generation."""
        timestamp = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        id1 = generate_tool_event_id(
            "session-123",
            "tool_execution_started",
            timestamp,
            "Read",
            "toolu_01ABC",
        )
        id2 = generate_tool_event_id(
            "session-123",
            "tool_execution_started",
            timestamp,
            "Read",
            "toolu_01ABC",
        )

        assert id1 == id2
        assert len(id1) == 32

    def test_generate_tool_event_id_differs_by_tool(self) -> None:
        """Different tools should produce different IDs."""
        timestamp = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        id_read = generate_tool_event_id(
            "session-123", "tool_execution_started", timestamp, "Read", "toolu_01ABC"
        )
        id_write = generate_tool_event_id(
            "session-123", "tool_execution_started", timestamp, "Write", "toolu_01ABC"
        )

        assert id_read != id_write

    def test_generate_token_event_id(self) -> None:
        """Test token event ID generation."""
        timestamp = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        id1 = generate_token_event_id("session-123", timestamp, "msg-uuid-12345678")
        id2 = generate_token_event_id("session-123", timestamp, "msg-uuid-12345678")

        assert id1 == id2
        assert len(id1) == 32

    def test_generate_session_event_id(self) -> None:
        """Test session event ID generation."""
        timestamp = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        id1 = generate_session_event_id("session-123", "session_started", timestamp)
        id2 = generate_session_event_id("session-123", "session_started", timestamp)

        assert id1 == id2
        assert len(id1) == 32
