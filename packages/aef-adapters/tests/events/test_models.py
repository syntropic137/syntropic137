"""Tests for AgentEvent model."""

import pytest
from datetime import datetime
from uuid import uuid4

from aef_adapters.events.models import AgentEvent


@pytest.mark.unit
class TestAgentEventWithRealTypes:
    """Tests for AgentEvent with REAL Claude CLI event types.
    
    These tests validate that raw Claude CLI events can be
    processed through AgentEvent.from_dict() without errors.
    
    CRITICAL: This catches the bug where 'tool_started' wasn't
    being mapped to 'tool_execution_started'.
    """

    def test_tool_started_event_maps_correctly(self) -> None:
        """Claude CLI 'tool_started' should map to 'tool_execution_started'."""
        event = AgentEvent.from_dict({
            "type": "tool_started",
            "tool": "Bash",
            "timestamp": "2025-01-01T00:00:00Z",
        })
        assert event.event_type == "tool_execution_started"

    def test_tool_result_event_maps_correctly(self) -> None:
        """Claude CLI 'tool_result' should map to 'tool_execution_completed'."""
        event = AgentEvent.from_dict({
            "type": "tool_result",
            "tool": "Bash",
            "result": "success",
        })
        assert event.event_type == "tool_execution_completed"

    def test_system_init_event_maps_correctly(self) -> None:
        """Claude CLI 'system.init' should map to 'session_started'."""
        event = AgentEvent.from_dict({
            "type": "system.init",
            "model": "claude-3-5-sonnet",
        })
        assert event.event_type == "session_started"

    def test_result_event_maps_correctly(self) -> None:
        """Claude CLI 'result' should map to 'session_completed'."""
        event = AgentEvent.from_dict({
            "type": "result",
            "cost_usd": 0.01,
        })
        assert event.event_type == "session_completed"

    def test_assistant_event_maps_correctly(self) -> None:
        """Claude CLI 'assistant' should map to 'token_usage'."""
        event = AgentEvent.from_dict({
            "type": "assistant",
            "content": "Hello!",
        })
        assert event.event_type == "token_usage"

    def test_all_claude_cli_event_types_are_valid(self) -> None:
        """All common Claude CLI event types should produce valid AgentEvents."""
        claude_event_types = [
            "tool_started",
            "tool_result", 
            "tool_use",
            "system.init",
            "system",
            "result",
            "assistant",
            "user",
        ]
        
        for event_type in claude_event_types:
            # This should NOT raise ValidationError
            event = AgentEvent.from_dict({"type": event_type})
            assert event.event_type is not None, f"Event type {event_type} failed"


@pytest.mark.unit
class TestAgentEvent:
    """Tests for AgentEvent model validation."""

    def test_from_dict_minimal(self) -> None:
        """Should create event with just event_type (using valid type)."""
        event = AgentEvent.from_dict({"event_type": "session_started"})

        assert event.event_type == "session_started"
        assert isinstance(event.time, datetime)
        assert event.session_id is None
        assert event.data == {}

    def test_from_dict_with_session_id(self) -> None:
        """Should parse valid UUID session_id."""
        uid = uuid4()
        event = AgentEvent.from_dict(
            {
                "event_type": "session_started",
                "session_id": str(uid),
            }
        )

        assert event.session_id == uid

    def test_from_dict_with_invalid_session_id(self) -> None:
        """Should handle invalid UUID gracefully."""
        event = AgentEvent.from_dict(
            {
                "event_type": "session_started",
                "session_id": "not-a-uuid",
            }
        )

        # Invalid UUID becomes None (graceful handling)
        assert event.session_id is None

    def test_from_dict_with_timestamp_alias(self) -> None:
        """Should accept 'timestamp' as alias for 'time'."""
        ts = datetime(2025, 1, 1, 12, 0, 0)
        event = AgentEvent.from_dict(
            {
                "event_type": "session_started",
                "timestamp": ts,
            }
        )

        assert event.time == ts

    def test_from_dict_with_type_alias(self) -> None:
        """Should accept 'type' as alias for 'event_type' and map to normalized type."""
        event = AgentEvent.from_dict({"type": "tool_started"})

        # tool_started maps to tool_execution_started
        assert event.event_type == "tool_execution_started"

    def test_from_dict_extra_fields_to_data(self) -> None:
        """Should put extra fields in data dict."""
        event = AgentEvent.from_dict(
            {
                "event_type": "tool_execution_started",
                "tool_name": "Write",
                "file_path": "/test.py",
            }
        )

        assert event.data == {"tool_name": "Write", "file_path": "/test.py"}

    def test_to_insert_tuple(self) -> None:
        """Should return tuple for asyncpg insert."""
        session_id = uuid4()
        event = AgentEvent(
            time=datetime(2025, 1, 1),
            event_type="session_started",
            session_id=session_id,
            data={"key": "value"},
        )

        time, event_type, sid, eid, pid, data_json = event.to_insert_tuple()

        assert time == datetime(2025, 1, 1)
        assert event_type == "session_started"
        assert sid == session_id
        assert eid is None
        assert pid is None
        assert '"key": "value"' in data_json

    def test_data_validator_none_to_empty_dict(self) -> None:
        """Should convert None data to empty dict via validator."""
        # When data is passed directly to model
        event = AgentEvent(event_type="session_started", data=None)
        assert event.data == {}

    def test_data_field_from_dict_preserved(self) -> None:
        """Extra fields go to data, including 'data' field itself."""
        event = AgentEvent.from_dict(
            {
                "event_type": "session_started",
                "data": {"nested": "value"},
            }
        )
        # The 'data' key in input goes into the data dict as extra field
        assert event.data == {"data": {"nested": "value"}}

    def test_uuid_validator_accepts_uuid_object(self) -> None:
        """Should accept UUID objects directly."""
        uid = uuid4()
        event = AgentEvent.from_dict(
            {
                "event_type": "session_started",
                "session_id": uid,
            }
        )

        assert event.session_id == uid
