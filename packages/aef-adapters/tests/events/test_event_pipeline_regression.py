"""Comprehensive regression tests for the event processing pipeline.

These tests use REAL Claude CLI recordings to ensure the full event pipeline
works correctly. They catch regressions like:
- Event type mapping failures
- Tool name extraction failures
- Missing fields in events
- Validation errors

IMPORTANT: These tests should be run before any release to ensure
the observability layer is bulletproof.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aef_adapters.events.models import AgentEvent

# Path to recordings - relative to workspace root
# __file__ is packages/aef-adapters/tests/events/test_event_pipeline_regression.py
# We need to go up to workspace root then down to lib/agentic-primitives
_AEF_ROOT = Path(__file__).parent.parent.parent.parent.parent
RECORDINGS_DIR = (
    _AEF_ROOT
    / "lib"
    / "agentic-primitives"
    / "providers"
    / "workspaces"
    / "claude-cli"
    / "fixtures"
    / "recordings"
)


def load_recording(name: str) -> list[dict[str, Any]]:
    """Load a JSONL recording file."""
    recording_path = RECORDINGS_DIR / name
    if not recording_path.exists():
        pytest.skip(f"Recording {name} not found at {recording_path}")

    events = []
    with open(recording_path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def get_all_recordings() -> list[str]:
    """Get all available recording files."""
    if not RECORDINGS_DIR.exists():
        return []
    return [f.name for f in RECORDINGS_DIR.glob("*.jsonl")]


# =============================================================================
# RECORDING PARSING TESTS
# =============================================================================


@pytest.mark.unit
class TestRecordingsParse:
    """Test that all recordings parse correctly through AgentEvent.from_dict()."""

    @pytest.fixture
    def recordings(self) -> list[str]:
        """Get all available recordings."""
        recordings = get_all_recordings()
        if not recordings:
            pytest.skip("No recordings available")
        return recordings

    def test_all_recordings_exist(self, recordings: list[str]) -> None:
        """Verify recordings directory exists and has files."""
        assert len(recordings) > 0, "Should have at least one recording"

    @pytest.mark.parametrize(
        "recording_name",
        get_all_recordings() or ["skip"],
    )
    def test_recording_parses_without_error(self, recording_name: str) -> None:
        """REGRESSION: Every recording should parse without raising exceptions."""
        if recording_name == "skip":
            pytest.skip("No recordings available")

        events = load_recording(recording_name)
        parse_errors = []

        for i, raw_event in enumerate(events):
            try:
                AgentEvent.from_dict(raw_event)
            except Exception as e:
                parse_errors.append(f"Event {i}: {e}")

        assert not parse_errors, (
            f"Recording {recording_name} had parse errors:\n"
            + "\n".join(parse_errors)
        )


# =============================================================================
# TOOL NAME EXTRACTION TESTS
# =============================================================================


@pytest.mark.unit
class TestToolNameExtraction:
    """Test tool name extraction from Claude CLI events."""

    @pytest.mark.parametrize(
        "recording_name",
        get_all_recordings() or ["skip"],
    )
    def test_tool_use_events_have_tool_name(self, recording_name: str) -> None:
        """REGRESSION: All tool_use events should extract tool_name."""
        if recording_name == "skip":
            pytest.skip("No recordings available")

        events = load_recording(recording_name)
        tool_use_events = []

        for raw_event in events:
            event_type = raw_event.get("type")
            if event_type == "assistant":
                message = raw_event.get("message", {})
                content = message.get("content", [])
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        parsed = AgentEvent.from_dict(raw_event)
                        tool_use_events.append(
                            {
                                "raw_name": item.get("name"),
                                "parsed_name": parsed.data.get("tool_name"),
                                "raw_id": item.get("id"),
                                "parsed_id": parsed.data.get("tool_use_id"),
                            }
                        )

        for tool_event in tool_use_events:
            assert tool_event["parsed_name"] is not None, (
                f"Recording {recording_name}: tool_use should extract tool_name. "
                f"Raw name was: {tool_event['raw_name']}"
            )
            assert tool_event["parsed_id"] is not None, (
                f"Recording {recording_name}: tool_use should extract tool_use_id. "
                f"Raw id was: {tool_event['raw_id']}"
            )

    @pytest.mark.parametrize(
        "recording_name",
        get_all_recordings() or ["skip"],
    )
    def test_tool_result_events_have_tool_use_id(self, recording_name: str) -> None:
        """REGRESSION: All tool_result events should extract tool_use_id."""
        if recording_name == "skip":
            pytest.skip("No recordings available")

        events = load_recording(recording_name)
        tool_result_events = []

        for raw_event in events:
            event_type = raw_event.get("type")
            if event_type == "user":
                message = raw_event.get("message", {})
                content = message.get("content", [])
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        parsed = AgentEvent.from_dict(raw_event)
                        tool_result_events.append(
                            {
                                "raw_id": item.get("tool_use_id"),
                                "parsed_id": parsed.data.get("tool_use_id"),
                                "raw_is_error": item.get("is_error"),
                                "parsed_success": parsed.data.get("success"),
                            }
                        )

        for tool_event in tool_result_events:
            assert tool_event["parsed_id"] is not None, (
                f"Recording {recording_name}: tool_result should extract tool_use_id"
            )
            # success should be inverse of is_error
            if tool_event["raw_is_error"] is not None:
                expected_success = not tool_event["raw_is_error"]
                assert tool_event["parsed_success"] == expected_success, (
                    f"Recording {recording_name}: success should be inverse of is_error"
                )


# =============================================================================
# EVENT TYPE MAPPING TESTS
# =============================================================================


@pytest.mark.unit
class TestEventTypeMapping:
    """Test that Claude CLI event types map correctly to AEF types."""

    @pytest.mark.parametrize(
        "recording_name",
        get_all_recordings() or ["skip"],
    )
    def test_all_events_have_valid_type(self, recording_name: str) -> None:
        """REGRESSION: All events should map to valid AEF event types."""
        if recording_name == "skip":
            pytest.skip("No recordings available")

        # Valid AEF event types
        valid_types = {
            "tool_execution_started",
            "tool_execution_completed",
            "session_started",
            "session_completed",
            "token_usage",
            "cost_recorded",
            "phase_started",
            "phase_completed",
            "error",
        }

        events = load_recording(recording_name)
        invalid_types = []

        for i, raw_event in enumerate(events):
            try:
                parsed = AgentEvent.from_dict(raw_event)
                if parsed.event_type not in valid_types:
                    invalid_types.append(
                        f"Event {i}: '{parsed.event_type}' not in valid types"
                    )
            except Exception as e:
                invalid_types.append(f"Event {i}: Parse failed - {e}")

        assert not invalid_types, (
            f"Recording {recording_name} had invalid event types:\n"
            + "\n".join(invalid_types)
        )


# =============================================================================
# SESSION LIFECYCLE TESTS
# =============================================================================


@pytest.mark.unit
class TestSessionLifecycle:
    """Test session lifecycle events are properly handled."""

    @pytest.mark.parametrize(
        "recording_name",
        get_all_recordings() or ["skip"],
    )
    def test_recording_has_result_event(self, recording_name: str) -> None:
        """REGRESSION: Every recording should end with a result event."""
        if recording_name == "skip":
            pytest.skip("No recordings available")

        events = load_recording(recording_name)
        result_events = [e for e in events if e.get("type") == "result"]

        assert len(result_events) >= 1, (
            f"Recording {recording_name} should have at least one result event"
        )

    @pytest.mark.parametrize(
        "recording_name",
        get_all_recordings() or ["skip"],
    )
    def test_result_event_has_cost_info(self, recording_name: str) -> None:
        """REGRESSION: Result events should have cost information."""
        if recording_name == "skip":
            pytest.skip("No recordings available")

        events = load_recording(recording_name)
        result_events = [e for e in events if e.get("type") == "result"]

        for result in result_events:
            # Result events should have cost_usd or total_cost_usd
            has_cost = "cost_usd" in result or "total_cost_usd" in result
            assert has_cost, (
                f"Recording {recording_name}: result event should have cost info"
            )


# =============================================================================
# TOKEN USAGE TESTS
# =============================================================================


@pytest.mark.unit
class TestTokenUsage:
    """Test token usage extraction from events."""

    @pytest.mark.parametrize(
        "recording_name",
        get_all_recordings() or ["skip"],
    )
    def test_assistant_events_map_correctly(self, recording_name: str) -> None:
        """REGRESSION: Assistant events map based on content type.

        - assistant + tool_use → tool_execution_started
        - assistant + text only → token_usage
        """
        if recording_name == "skip":
            pytest.skip("No recordings available")

        events = load_recording(recording_name)
        assistant_events = [e for e in events if e.get("type") == "assistant"]

        for raw_event in assistant_events:
            parsed = AgentEvent.from_dict(raw_event)

            # Check if assistant message contains tool_use
            content = raw_event.get("message", {}).get("content", [])
            has_tool_use = any(
                isinstance(item, dict) and item.get("type") == "tool_use"
                for item in content
            )

            if has_tool_use:
                assert parsed.event_type == "tool_execution_started", (
                    f"Recording {recording_name}: assistant+tool_use should map to tool_execution_started"
                )
            else:
                assert parsed.event_type == "token_usage", (
                    f"Recording {recording_name}: assistant+text should map to token_usage"
                )


# =============================================================================
# DATA INTEGRITY TESTS
# =============================================================================


@pytest.mark.unit
class TestDataIntegrity:
    """Test that event data is preserved correctly."""

    @pytest.mark.parametrize(
        "recording_name",
        get_all_recordings() or ["skip"],
    )
    def test_session_id_preserved(self, recording_name: str) -> None:
        """REGRESSION: Session ID should be preserved through parsing."""
        if recording_name == "skip":
            pytest.skip("No recordings available")

        events = load_recording(recording_name)
        session_ids = set()

        for raw_event in events:
            session_id = raw_event.get("session_id")
            if session_id:
                # Add to raw event for parsing
                event_with_session = {**raw_event, "session_id": session_id}
                parsed = AgentEvent.from_dict(event_with_session)
                if parsed.session_id:
                    session_ids.add(str(parsed.session_id))

        # All events in a recording should have the same session_id
        assert len(session_ids) <= 1, (
            f"Recording {recording_name} has multiple session IDs: {session_ids}"
        )

    def test_no_data_loss_for_tool_input(self) -> None:
        """REGRESSION: Tool input should be preserved as input_preview."""
        raw_event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_test",
                        "name": "Bash",
                        "input": {"command": "ls -la", "timeout": 30},
                    }
                ]
            },
        }

        parsed = AgentEvent.from_dict(raw_event)

        assert "input_preview" in parsed.data
        # Input should be JSON stringified
        assert "command" in parsed.data["input_preview"]
        assert "ls -la" in parsed.data["input_preview"]


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_content_array(self) -> None:
        """Should handle empty content array gracefully."""
        raw_event = {
            "type": "assistant",
            "message": {"content": []},
        }

        # Should not raise
        parsed = AgentEvent.from_dict(raw_event)
        assert parsed.event_type == "token_usage"

    def test_missing_message_field(self) -> None:
        """Should handle missing message field gracefully."""
        raw_event = {"type": "assistant"}

        # Should not raise
        parsed = AgentEvent.from_dict(raw_event)
        assert parsed.event_type == "token_usage"

    def test_non_dict_content_items(self) -> None:
        """Should handle non-dict content items gracefully."""
        raw_event = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Hello"},
                    "just a string",  # Non-dict item
                ]
            },
        }

        # Should not raise
        parsed = AgentEvent.from_dict(raw_event)
        assert parsed.event_type == "token_usage"

    def test_unknown_event_type_raises_validation_error(self) -> None:
        """Unknown event types should raise validation error.

        This is intentional - we want to catch any unknown event types
        so they can be properly mapped in the event_type_mapping.
        """
        import pytest
        from pydantic import ValidationError

        raw_event = {
            "type": "custom_event",
            "custom_field": "value",
        }

        with pytest.raises(ValidationError):
            AgentEvent.from_dict(raw_event)
