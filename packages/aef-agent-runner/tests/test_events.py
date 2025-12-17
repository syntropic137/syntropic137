"""Tests for events module."""

from __future__ import annotations

import json
from unittest import mock

from aef_agent_runner.events import (
    AgentEvent,
    EventType,
    emit_artifact,
    emit_cancelled,
    emit_completed,
    emit_error,
    emit_event,
    emit_progress,
    emit_started,
    emit_token_usage,
    emit_tool_result,
    emit_tool_use,
)


class TestAgentEvent:
    """Tests for AgentEvent class."""

    def test_to_dict(self) -> None:
        """Should convert event to dictionary."""
        event = AgentEvent(
            type=EventType.STARTED,
            timestamp="2025-12-14T10:00:00Z",
        )

        result = event.to_dict()

        assert result["type"] == "started"
        assert result["timestamp"] == "2025-12-14T10:00:00Z"

    def test_to_dict_with_data(self) -> None:
        """Should include additional data in dict."""
        event = AgentEvent(
            type=EventType.PROGRESS,
            data={"turn": 5, "tokens": 1000},
        )

        result = event.to_dict()

        assert result["type"] == "progress"
        assert result["turn"] == 5
        assert result["tokens"] == 1000

    def test_to_json(self) -> None:
        """Should serialize to JSON string."""
        event = AgentEvent(
            type=EventType.COMPLETED,
            timestamp="2025-12-14T10:00:00Z",
            data={"success": True},
        )

        result = event.to_json()
        parsed = json.loads(result)

        assert parsed["type"] == "completed"
        assert parsed["success"] is True

    def test_timestamp_auto_generated(self) -> None:
        """Should auto-generate timestamp if not provided."""
        event = AgentEvent(type=EventType.STARTED)

        assert event.timestamp is not None
        assert "T" in event.timestamp  # ISO format


class TestEmitEvent:
    """Tests for emit_event function."""

    def test_emit_agent_event(self) -> None:
        """Should emit AgentEvent as JSONL."""
        event = AgentEvent(
            type=EventType.STARTED,
            timestamp="2025-12-14T10:00:00Z",
        )

        with mock.patch("builtins.print") as mock_print:
            emit_event(event)

            mock_print.assert_called_once()
            args = mock_print.call_args
            line = args[0][0]
            parsed = json.loads(line)
            assert parsed["type"] == "started"

    def test_emit_dict(self) -> None:
        """Should emit dict as JSONL."""
        event = {"type": "custom", "data": 123}

        with mock.patch("builtins.print") as mock_print:
            emit_event(event)

            args = mock_print.call_args
            line = args[0][0]
            parsed = json.loads(line)
            assert parsed["type"] == "custom"
            assert parsed["data"] == 123
            assert "timestamp" in parsed  # Auto-added


class TestEmitConvenienceFunctions:
    """Tests for convenience emit functions."""

    def test_emit_started(self) -> None:
        """Should emit started event."""
        with mock.patch("builtins.print") as mock_print:
            emit_started()

            line = mock_print.call_args[0][0]
            parsed = json.loads(line)
            assert parsed["type"] == "started"

    def test_emit_completed(self) -> None:
        """Should emit completed event."""
        with mock.patch("builtins.print") as mock_print:
            emit_completed(success=True, duration_ms=5000)

            line = mock_print.call_args[0][0]
            parsed = json.loads(line)
            assert parsed["type"] == "completed"
            assert parsed["success"] is True
            assert parsed["duration_ms"] == 5000

    def test_emit_error(self) -> None:
        """Should emit error event."""
        with mock.patch("builtins.print") as mock_print:
            emit_error(message="Something failed", error_type="ValueError")

            line = mock_print.call_args[0][0]
            parsed = json.loads(line)
            assert parsed["type"] == "error"
            assert parsed["message"] == "Something failed"
            assert parsed["error_type"] == "ValueError"

    def test_emit_cancelled(self) -> None:
        """Should emit cancelled event."""
        with mock.patch("builtins.print") as mock_print:
            emit_cancelled()

            line = mock_print.call_args[0][0]
            parsed = json.loads(line)
            assert parsed["type"] == "cancelled"

    def test_emit_progress(self) -> None:
        """Should emit progress event."""
        with mock.patch("builtins.print") as mock_print:
            emit_progress(turn=3, input_tokens=1500, output_tokens=200)

            line = mock_print.call_args[0][0]
            parsed = json.loads(line)
            assert parsed["type"] == "progress"
            assert parsed["turn"] == 3
            assert parsed["input_tokens"] == 1500
            assert parsed["output_tokens"] == 200

    def test_emit_tool_use(self) -> None:
        """Should emit tool_use event."""
        with mock.patch("builtins.print") as mock_print:
            emit_tool_use(
                tool_name="Read",
                tool_input={"path": "/test.txt"},
                tool_use_id="tool-123",
            )

            line = mock_print.call_args[0][0]
            parsed = json.loads(line)
            assert parsed["type"] == "tool_use"
            assert parsed["tool"] == "Read"
            assert parsed["input"] == {"path": "/test.txt"}
            assert parsed["tool_use_id"] == "tool-123"

    def test_emit_tool_result(self) -> None:
        """Should emit tool_result event."""
        with mock.patch("builtins.print") as mock_print:
            emit_tool_result(
                tool_name="Write",
                success=True,
                tool_use_id="tool-456",
                duration_ms=50,
            )

            line = mock_print.call_args[0][0]
            parsed = json.loads(line)
            assert parsed["type"] == "tool_result"
            assert parsed["tool"] == "Write"
            assert parsed["success"] is True
            assert parsed["duration_ms"] == 50

    def test_emit_artifact(self) -> None:
        """Should emit artifact event."""
        with mock.patch("builtins.print") as mock_print:
            emit_artifact(
                name="output.md",
                path="/workspace/artifacts/output.md",
                size_bytes=1024,
            )

            line = mock_print.call_args[0][0]
            parsed = json.loads(line)
            assert parsed["type"] == "artifact"
            assert parsed["name"] == "output.md"
            assert parsed["path"] == "/workspace/artifacts/output.md"
            assert parsed["size_bytes"] == 1024

    def test_emit_token_usage(self) -> None:
        """Should emit token_usage event."""
        with mock.patch("builtins.print") as mock_print:
            emit_token_usage(
                input_tokens=1000,
                output_tokens=500,
                cache_creation_tokens=200,
                cache_read_tokens=100,
            )

            line = mock_print.call_args[0][0]
            parsed = json.loads(line)
            assert parsed["type"] == "token_usage"
            assert parsed["input_tokens"] == 1000
            assert parsed["output_tokens"] == 500
            assert parsed["cache_creation_tokens"] == 200
            assert parsed["cache_read_tokens"] == 100
