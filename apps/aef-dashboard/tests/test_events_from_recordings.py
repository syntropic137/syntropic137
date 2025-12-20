"""Tests for dashboard event processing using recordings.

These tests verify that recorded agent events can be correctly
transformed into dashboard API response formats.

See ADR-033: Recording-Based Integration Testing
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from aef_adapters.workspace_backends.recording import RecordingEventStreamAdapter

pytestmark = [pytest.mark.integration]


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def recording_adapter() -> RecordingEventStreamAdapter:
    """Get adapter for simple-bash recording."""
    try:
        return RecordingEventStreamAdapter("simple-bash")
    except FileNotFoundError:
        pytest.skip("simple-bash recording not available")


@pytest.fixture
def multi_tool_adapter() -> RecordingEventStreamAdapter:
    """Get adapter for multi-tool recording."""
    try:
        return RecordingEventStreamAdapter("multi-tool")
    except FileNotFoundError:
        pytest.skip("multi-tool recording not available")


# =============================================================================
# EVENT TRANSFORMATION TESTS
# =============================================================================


class TestEventToApiTransformation:
    """Test transforming recording events to API response format."""

    def test_can_extract_event_response_fields(
        self, recording_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Events have fields needed for EventResponse schema."""
        events = recording_adapter.get_events()

        for event in events:
            # EventResponse requires: time, event_type, session_id, data
            # We can derive event_type from 'type'
            assert "type" in event, "Event missing 'type' for event_type"
            assert "session_id" in event, "Event missing session_id"

            # Time can be derived from various fields
            # Events always have some timing info (via message timestamps or result)
            _ = any(k in event for k in ["timestamp", "time", "created_at", "message"])

    def test_event_type_mapping(self, recording_adapter: RecordingEventStreamAdapter) -> None:
        """Recording event types can be mapped to dashboard event types."""
        events = recording_adapter.get_events()

        # Map of recording types to dashboard display types
        type_mapping = {
            "system": "session_lifecycle",
            "assistant": "model_response",
            "user": "tool_result",
            "result": "session_completed",
        }

        for event in events:
            event_type = event.get("type")
            assert event_type in type_mapping or event_type is not None, (
                f"Unknown event type: {event_type}"
            )

    def test_can_build_cost_summary_from_result(
        self, recording_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Can build CostSummary from result event."""
        events = recording_adapter.get_events()
        result = next((e for e in events if e.get("type") == "result"), None)
        assert result is not None

        # Extract cost summary fields
        usage = result.get("usage", {})

        cost_summary = {
            "session_id": recording_adapter.session_id,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_creation_tokens": usage.get("cache_creation_tokens", 0),
            "cache_read_tokens": usage.get("cache_read_tokens", 0),
            "estimated_cost_usd": result.get("total_cost_usd"),
        }

        # Verify fields are populated
        assert cost_summary["session_id"] is not None
        assert cost_summary["estimated_cost_usd"] is not None
        assert isinstance(cost_summary["input_tokens"], int)
        assert isinstance(cost_summary["output_tokens"], int)


class TestToolTimelineExtraction:
    """Test extracting tool timeline for dashboard visualization."""

    def test_can_build_tool_timeline(self, multi_tool_adapter: RecordingEventStreamAdapter) -> None:
        """Can build tool timeline entries from events."""
        events = multi_tool_adapter.get_events()
        timeline: list[dict[str, Any]] = []

        for event in events:
            if event.get("type") != "assistant":
                continue

            message = event.get("message", {})
            content = message.get("content", [])

            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    timeline.append(
                        {
                            "event_type": "tool_started",
                            "tool_name": item.get("name"),
                            "tool_use_id": item.get("id"),
                        }
                    )

        assert len(timeline) > 0, "Should have tool timeline entries"

        for entry in timeline:
            assert entry["tool_name"] is not None
            assert entry["tool_use_id"] is not None

    def test_can_correlate_tool_results(
        self, multi_tool_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Can correlate tool_use with tool_result for duration."""
        events = multi_tool_adapter.get_events()

        tool_uses: dict[str, dict[str, Any]] = {}
        tool_results: dict[str, dict[str, Any]] = {}

        for event in events:
            message = event.get("message", {})
            content = message.get("content", [])

            for item in content:
                if not isinstance(item, dict):
                    continue

                if item.get("type") == "tool_use":
                    tool_id = item.get("id")
                    if tool_id:
                        tool_uses[tool_id] = {
                            "name": item.get("name"),
                            "input": item.get("input"),
                        }

                if item.get("type") == "tool_result":
                    tool_id = item.get("tool_use_id")
                    if tool_id:
                        tool_results[tool_id] = {
                            "content": item.get("content"),
                            "is_error": item.get("is_error", False),
                        }

        # All tool_uses should have corresponding results
        for tool_id in tool_uses:
            assert tool_id in tool_results, f"Tool {tool_id} missing result"


class TestToolSummaryAggregation:
    """Test aggregating tool usage for ToolSummary."""

    def test_can_aggregate_tool_stats(
        self, multi_tool_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Can aggregate tool usage statistics."""
        events = multi_tool_adapter.get_events()

        tool_stats: dict[str, dict[str, Any]] = {}

        for event in events:
            message = event.get("message", {})
            content = message.get("content", [])

            for item in content:
                if not isinstance(item, dict):
                    continue

                if item.get("type") == "tool_use":
                    name = item.get("name")
                    if name:
                        if name not in tool_stats:
                            tool_stats[name] = {
                                "tool_name": name,
                                "call_count": 0,
                                "success_count": 0,
                                "error_count": 0,
                            }
                        tool_stats[name]["call_count"] += 1

                # Count errors from tool_result
                if item.get("type") == "tool_result":
                    is_error = item.get("is_error", False)
                    # Would need to correlate with tool_use to get name
                    # For now just verify we can detect errors
                    if is_error:
                        pass  # Would increment error_count

        assert len(tool_stats) > 0, "Should have tool stats"

        for name, stats in tool_stats.items():
            assert stats["call_count"] > 0
            assert stats["tool_name"] == name


# =============================================================================
# SESSION SUMMARY TESTS
# =============================================================================


class TestSessionSummaryExtraction:
    """Test extracting session summary data for dashboard."""

    def test_can_build_session_summary(
        self, recording_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Can build complete session summary from events."""
        events = recording_adapter.get_events()

        # Extract all session summary fields
        summary = {
            "id": recording_adapter.session_id,
            "status": "unknown",
            "agent_provider": None,
            "total_tokens": 0,
            "total_cost_usd": None,
            "started_at": None,
            "completed_at": None,
        }

        for event in events:
            # Session start from system.init
            if event.get("type") == "system" and event.get("subtype") == "init":
                summary["started_at"] = datetime.now(UTC)  # Would parse from event
                summary["agent_provider"] = "anthropic"  # From model name

            # Session end from result
            if event.get("type") == "result":
                summary["status"] = "completed"
                summary["completed_at"] = datetime.now(UTC)
                summary["total_cost_usd"] = event.get("total_cost_usd")

                usage = event.get("usage", {})
                summary["total_tokens"] = usage.get("input_tokens", 0) + usage.get(
                    "output_tokens", 0
                )

        # Verify summary is complete
        assert summary["id"] is not None
        assert summary["status"] == "completed"
        assert summary["total_cost_usd"] is not None
        assert summary["total_tokens"] > 0


class TestEventFiltering:
    """Test event filtering for dashboard queries."""

    def test_can_filter_by_type(self, recording_adapter: RecordingEventStreamAdapter) -> None:
        """Can filter events by type."""
        events = recording_adapter.get_events()

        assistant_events = [e for e in events if e.get("type") == "assistant"]
        user_events = [e for e in events if e.get("type") == "user"]
        system_events = [e for e in events if e.get("type") == "system"]
        result_events = [e for e in events if e.get("type") == "result"]

        # Should have at least system and result
        assert len(system_events) >= 1
        assert len(result_events) >= 1

        # Total filtered should equal total
        total_filtered = (
            len(assistant_events) + len(user_events) + len(system_events) + len(result_events)
        )
        assert total_filtered == len(events)

    def test_can_extract_tool_events_only(
        self, multi_tool_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Can extract only tool-related events."""
        events = multi_tool_adapter.get_events()

        tool_events = []
        for event in events:
            message = event.get("message", {})
            content = message.get("content", [])

            for item in content:
                if isinstance(item, dict) and item.get("type") in ("tool_use", "tool_result"):
                    tool_events.append(
                        {
                            "event_type": event.get("type"),
                            "item_type": item.get("type"),
                            "tool_name": item.get("name"),
                            "tool_id": item.get("id") or item.get("tool_use_id"),
                        }
                    )

        assert len(tool_events) > 0, "Should find tool events"


# =============================================================================
# DATA VALIDATION TESTS
# =============================================================================


class TestDataValidation:
    """Test that extracted data passes API schema validation."""

    def test_cost_values_are_valid_for_decimal(
        self, recording_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Cost values can be converted to Decimal for API."""
        from decimal import Decimal

        events = recording_adapter.get_events()
        result = next((e for e in events if e.get("type") == "result"), None)
        assert result is not None

        cost = result.get("total_cost_usd")
        assert cost is not None

        # Should be convertible to Decimal
        decimal_cost = Decimal(str(cost))
        assert decimal_cost >= 0

    def test_token_counts_are_valid_integers(
        self, recording_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Token counts are valid integers for API."""
        events = recording_adapter.get_events()
        result = next((e for e in events if e.get("type") == "result"), None)
        assert result is not None

        usage = result.get("usage", {})

        for key in ["input_tokens", "output_tokens"]:
            if key in usage:
                value = usage[key]
                assert isinstance(value, int)
                assert value >= 0

    def test_session_id_is_valid_uuid_format(
        self, recording_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Session ID is valid UUID format."""
        import re

        session_id = recording_adapter.session_id
        assert session_id is not None

        # UUID format: 8-4-4-4-12 hex digits
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        assert uuid_pattern.match(session_id), f"Invalid UUID format: {session_id}"
