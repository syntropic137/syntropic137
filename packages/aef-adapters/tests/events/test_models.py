"""Tests for AgentEvent model."""

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from aef_adapters.events.models import AgentEvent


class TestAgentEvent:
    """Tests for AgentEvent model validation."""

    def test_from_dict_minimal(self) -> None:
        """Should create event with just event_type."""
        event = AgentEvent.from_dict({"event_type": "test"})

        assert event.event_type == "test"
        assert isinstance(event.time, datetime)
        assert event.session_id is None
        assert event.data == {}

    def test_from_dict_with_session_id(self) -> None:
        """Should parse valid UUID session_id."""
        uid = uuid4()
        event = AgentEvent.from_dict({
            "event_type": "test",
            "session_id": str(uid),
        })

        assert event.session_id == uid

    def test_from_dict_with_invalid_session_id(self) -> None:
        """Should handle invalid UUID gracefully."""
        event = AgentEvent.from_dict({
            "event_type": "test",
            "session_id": "not-a-uuid",
        })

        # Invalid UUID becomes None (graceful handling)
        assert event.session_id is None

    def test_from_dict_with_timestamp_alias(self) -> None:
        """Should accept 'timestamp' as alias for 'time'."""
        ts = datetime(2025, 1, 1, 12, 0, 0)
        event = AgentEvent.from_dict({
            "event_type": "test",
            "timestamp": ts,
        })

        assert event.time == ts

    def test_from_dict_with_type_alias(self) -> None:
        """Should accept 'type' as alias for 'event_type'."""
        event = AgentEvent.from_dict({"type": "tool_started"})

        assert event.event_type == "tool_started"

    def test_from_dict_extra_fields_to_data(self) -> None:
        """Should put extra fields in data dict."""
        event = AgentEvent.from_dict({
            "event_type": "tool_started",
            "tool_name": "Write",
            "file_path": "/test.py",
        })

        assert event.data == {"tool_name": "Write", "file_path": "/test.py"}

    def test_to_insert_tuple(self) -> None:
        """Should return tuple for asyncpg insert."""
        session_id = uuid4()
        event = AgentEvent(
            time=datetime(2025, 1, 1),
            event_type="test",
            session_id=session_id,
            data={"key": "value"},
        )

        time, event_type, sid, eid, pid, data_json = event.to_insert_tuple()

        assert time == datetime(2025, 1, 1)
        assert event_type == "test"
        assert sid == session_id
        assert eid is None
        assert pid is None
        assert '"key": "value"' in data_json

    def test_data_validator_none_to_empty_dict(self) -> None:
        """Should convert None data to empty dict via validator."""
        # When data is passed directly to model
        event = AgentEvent(event_type="test", data=None)
        assert event.data == {}

    def test_data_field_from_dict_preserved(self) -> None:
        """Extra fields go to data, including 'data' field itself."""
        event = AgentEvent.from_dict({
            "event_type": "test",
            "data": {"nested": "value"},
        })
        # The 'data' key in input goes into the data dict as extra field
        assert event.data == {"data": {"nested": "value"}}

    def test_uuid_validator_accepts_uuid_object(self) -> None:
        """Should accept UUID objects directly."""
        uid = uuid4()
        event = AgentEvent.from_dict({
            "event_type": "test",
            "session_id": uid,
        })

        assert event.session_id == uid
