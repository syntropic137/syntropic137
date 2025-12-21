"""Tests for AgentEvent model."""

from datetime import datetime
from uuid import uuid4

import pytest

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
        event = AgentEvent.from_dict(
            {
                "type": "tool_started",
                "tool": "Bash",
                "timestamp": "2025-01-01T00:00:00Z",
            }
        )
        assert event.event_type == "tool_execution_started"

    def test_tool_result_event_maps_correctly(self) -> None:
        """Claude CLI 'tool_result' should map to 'tool_execution_completed'."""
        event = AgentEvent.from_dict(
            {
                "type": "tool_result",
                "tool": "Bash",
                "result": "success",
            }
        )
        assert event.event_type == "tool_execution_completed"

    def test_system_init_event_maps_correctly(self) -> None:
        """Claude CLI 'system.init' should map to 'session_started'."""
        event = AgentEvent.from_dict(
            {
                "type": "system.init",
                "model": "claude-3-5-sonnet",
            }
        )
        assert event.event_type == "session_started"

    def test_result_event_maps_correctly(self) -> None:
        """Claude CLI 'result' should map to 'session_completed'."""
        event = AgentEvent.from_dict(
            {
                "type": "result",
                "cost_usd": 0.01,
            }
        )
        assert event.event_type == "session_completed"

    def test_assistant_event_maps_correctly(self) -> None:
        """Claude CLI 'assistant' should map to 'token_usage'."""
        event = AgentEvent.from_dict(
            {
                "type": "assistant",
                "content": "Hello!",
            }
        )
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

        # Now returns string (not UUID) per simplified schema
        assert event.session_id == str(uid)

    def test_from_dict_with_invalid_session_id(self) -> None:
        """Should accept any string as session_id (simplified schema)."""
        event = AgentEvent.from_dict(
            {
                "event_type": "session_started",
                "session_id": "not-a-uuid",
            }
        )

        # Simplified schema accepts any string
        assert event.session_id == "not-a-uuid"

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
        session_id = str(uuid4())  # Now string, not UUID
        event = AgentEvent(
            time=datetime(2025, 1, 1),
            event_type="session_started",
            session_id=session_id,
            data={"key": "value"},
        )

        time, event_type, sid, eid, pid, data_json = event.to_insert_tuple()

        assert time == datetime(2025, 1, 1)
        assert event_type == "session_started"
        assert sid == session_id  # String equality
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
        """Should accept UUID objects and convert to string."""
        uid = uuid4()
        event = AgentEvent.from_dict(
            {
                "event_type": "session_started",
                "session_id": uid,
            }
        )

        # UUID objects are converted to strings
        assert event.session_id == str(uid)


@pytest.mark.unit
class TestToolNameExtraction:
    """Regression tests for extracting tool_name from Claude CLI events.

    CRITICAL: These tests verify the fix for "Tool Calls: unknown" bug.
    Claude CLI's tool_result events don't include tool_name, only tool_use_id.
    We must extract tool_name from message.content.
    """

    def test_tool_use_extracts_name_and_id(self) -> None:
        """REGRESSION: tool_use in assistant message should extract tool_name and id."""
        # Raw Claude CLI assistant message with tool_use
        raw_event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_abc123",
                        "name": "Bash",
                        "input": {"command": "ls -la"},
                    }
                ]
            },
        }

        event = AgentEvent.from_dict(raw_event)

        # assistant + tool_use maps to tool_execution_started (not token_usage)
        assert event.event_type == "tool_execution_started"
        assert event.data.get("tool_name") == "Bash"
        assert event.data.get("tool_use_id") == "toolu_abc123"
        assert "input_preview" in event.data

    def test_tool_result_extracts_enriched_tool_name(self) -> None:
        """REGRESSION: tool_result with enriched tool_name should be extracted."""
        # Enriched Claude CLI user message with tool_result
        # (tool_name added by container_runner enrichment)
        raw_event = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_abc123",
                        "tool_name": "Bash",  # Added by enrichment
                        "content": "file.txt",
                        "is_error": False,
                    }
                ]
            },
        }

        event = AgentEvent.from_dict(raw_event)

        # user + tool_result maps to tool_execution_completed (not token_usage)
        assert event.event_type == "tool_execution_completed"
        assert event.data.get("tool_name") == "Bash"
        assert event.data.get("tool_use_id") == "toolu_abc123"
        assert event.data.get("success") is True

    def test_tool_result_without_enrichment_has_no_name(self) -> None:
        """REGRESSION: unenriched tool_result should not have tool_name."""
        # Raw Claude CLI user message without enrichment
        raw_event = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_abc123",
                        "content": "error output",
                        "is_error": True,
                    }
                ]
            },
        }

        event = AgentEvent.from_dict(raw_event)

        assert event.data.get("tool_use_id") == "toolu_abc123"
        assert event.data.get("tool_name") is None  # Not enriched
        assert event.data.get("success") is False  # is_error=True

    def test_tool_result_error_sets_success_false(self) -> None:
        """REGRESSION: tool_result with is_error=True should set success=False."""
        raw_event = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_xyz",
                        "is_error": True,
                    }
                ]
            },
        }

        event = AgentEvent.from_dict(raw_event)

        assert event.data.get("success") is False
