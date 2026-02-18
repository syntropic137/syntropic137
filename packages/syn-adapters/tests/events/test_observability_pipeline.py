"""Integration tests for the observability pipeline.

Tests that verify events flow from recordings through:
- Recording → Event parsing
- Events → Projection updates
- Projections → Queryable data

These tests use RecordingEventStreamAdapter to replay pre-recorded
agent sessions without API calls.

See ADR-033: Recording-Based Integration Testing
"""

from __future__ import annotations

import contextlib
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from syn_adapters.workspace_backends.recording import RecordingEventStreamAdapter

pytestmark = [pytest.mark.unit, pytest.mark.integration]  # Runs in CI - no external services


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def simple_bash_events() -> list[dict[str, Any]]:
    """Get events from simple-bash recording."""
    try:
        adapter = RecordingEventStreamAdapter("simple-bash")
        return adapter.get_events()
    except FileNotFoundError:
        pytest.skip("simple-bash recording not available")


@pytest.fixture
def multi_tool_events() -> list[dict[str, Any]]:
    """Get events from multi-tool recording."""
    try:
        adapter = RecordingEventStreamAdapter("multi-tool")
        return adapter.get_events()
    except FileNotFoundError:
        pytest.skip("multi-tool recording not available")


@pytest.fixture
def all_recording_adapters() -> list[RecordingEventStreamAdapter]:
    """Get adapters for all available recordings."""
    recording_names = [
        "simple-bash",
        "file-create",
        "file-read",
        "git-status",
        "multi-tool",
        "simple-question",
        "list-files",
    ]
    adapters = []
    for name in recording_names:
        with contextlib.suppress(FileNotFoundError):
            adapters.append(RecordingEventStreamAdapter(name))
    if not adapters:
        pytest.skip("No recordings available")
    return adapters


# =============================================================================
# EVENT STRUCTURE TESTS
# =============================================================================


class TestEventStructure:
    """Verify recorded events have the structure required by observability pipeline."""

    def test_events_have_session_id(self, simple_bash_events: list[dict[str, Any]]) -> None:
        """All events have session_id for correlation."""
        session_ids = {e.get("session_id") for e in simple_bash_events}
        # Remove None if present
        session_ids.discard(None)

        assert len(session_ids) >= 1, "Events should have session_id"
        # All events from same session should have same session_id
        assert len(session_ids) == 1, "All events should have same session_id"

    def test_events_have_type(self, simple_bash_events: list[dict[str, Any]]) -> None:
        """All events have type for routing."""
        for event in simple_bash_events:
            assert "type" in event, f"Event missing type: {event.keys()}"

    def test_has_system_init_event(self, simple_bash_events: list[dict[str, Any]]) -> None:
        """Recording has system init event with session metadata."""
        init_events = [
            e
            for e in simple_bash_events
            if e.get("type") == "system" and e.get("subtype") == "init"
        ]
        assert len(init_events) == 1, "Should have exactly one system.init event"

        init = init_events[0]
        assert "session_id" in init
        assert "model" in init
        assert "tools" in init

    def test_has_result_event(self, simple_bash_events: list[dict[str, Any]]) -> None:
        """Recording has result event with metrics."""
        result_events = [e for e in simple_bash_events if e.get("type") == "result"]
        assert len(result_events) == 1, "Should have exactly one result event"

        result = result_events[0]
        # These are the key metrics for observability
        assert "duration_ms" in result, "Result should have duration"
        assert "total_cost_usd" in result, "Result should have cost"

    def test_has_assistant_events(self, simple_bash_events: list[dict[str, Any]]) -> None:
        """Recording has assistant events (tool use)."""
        assistant_events = [e for e in simple_bash_events if e.get("type") == "assistant"]
        assert len(assistant_events) > 0, "Should have assistant events (tool use)"


class TestEventMetrics:
    """Verify metrics can be extracted from events."""

    def test_extract_token_counts(self, simple_bash_events: list[dict[str, Any]]) -> None:
        """Can extract token usage from result event."""
        result = next((e for e in simple_bash_events if e.get("type") == "result"), None)
        assert result is not None

        # Find usage data
        usage = result.get("usage", {})
        assert "input_tokens" in usage or "output_tokens" in usage, (
            f"Result should have usage data: {result.keys()}"
        )

    def test_extract_cost(self, simple_bash_events: list[dict[str, Any]]) -> None:
        """Can extract cost from result event."""
        result = next((e for e in simple_bash_events if e.get("type") == "result"), None)
        assert result is not None

        cost = result.get("total_cost_usd")
        assert cost is not None, "Result should have cost"
        assert isinstance(cost, (int, float)), f"Cost should be numeric: {cost}"
        assert cost >= 0, f"Cost should be non-negative: {cost}"

    def test_extract_duration(self, simple_bash_events: list[dict[str, Any]]) -> None:
        """Can extract duration from result event."""
        result = next((e for e in simple_bash_events if e.get("type") == "result"), None)
        assert result is not None

        duration = result.get("duration_ms")
        assert duration is not None, "Result should have duration"
        assert isinstance(duration, (int, float)), f"Duration should be numeric: {duration}"


class TestToolTracking:
    """Verify tool usage can be tracked from events."""

    def test_tool_use_in_assistant_events(self, multi_tool_events: list[dict[str, Any]]) -> None:
        """Tool use is captured in assistant events."""
        assistant_events = [e for e in multi_tool_events if e.get("type") == "assistant"]
        assert len(assistant_events) > 0

        # Check for tool use content
        tool_uses = []
        for event in assistant_events:
            message = event.get("message", {})
            content = message.get("content", [])
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    tool_uses.append(item)

        assert len(tool_uses) > 0, "multi-tool should have tool_use in assistant events"

    def test_tool_results_in_user_events(self, multi_tool_events: list[dict[str, Any]]) -> None:
        """Tool results are captured in user events."""
        user_events = [e for e in multi_tool_events if e.get("type") == "user"]
        assert len(user_events) > 0

        # Check for tool_result content
        tool_results = []
        for event in user_events:
            message = event.get("message", {})
            content = message.get("content", [])
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    tool_results.append(item)

        assert len(tool_results) > 0, "multi-tool should have tool_result in user events"


# =============================================================================
# STREAMING TESTS
# =============================================================================


class TestEventStreaming:
    """Test event streaming from recordings."""

    @pytest.mark.asyncio
    async def test_stream_produces_jsonl(self) -> None:
        """Stream produces valid JSONL lines."""
        try:
            adapter = RecordingEventStreamAdapter("simple-bash")
        except FileNotFoundError:
            pytest.skip("simple-bash recording not available")

        mock_handle = MagicMock()
        lines = []

        async for line in adapter.stream(mock_handle, ["test"]):
            lines.append(line)
            # Each line should be valid JSON
            parsed = json.loads(line)
            assert isinstance(parsed, dict)

        assert len(lines) == adapter.event_count

    @pytest.mark.asyncio
    async def test_stream_maintains_order(self) -> None:
        """Events stream in original order."""
        try:
            adapter = RecordingEventStreamAdapter("simple-bash")
        except FileNotFoundError:
            pytest.skip("simple-bash recording not available")

        mock_handle = MagicMock()
        streamed_events = []

        async for line in adapter.stream(mock_handle, ["test"]):
            streamed_events.append(json.loads(line))

        original_events = adapter.get_events()

        # Compare types in order
        streamed_types = [e.get("type") for e in streamed_events]
        original_types = [e.get("type") for e in original_events]
        assert streamed_types == original_types


# =============================================================================
# CROSS-RECORDING TESTS
# =============================================================================


class TestAllRecordings:
    """Tests that run against all available recordings."""

    def test_all_recordings_have_session_id(
        self, all_recording_adapters: list[RecordingEventStreamAdapter]
    ) -> None:
        """Every recording has a session_id."""
        for adapter in all_recording_adapters:
            assert adapter.session_id is not None, (
                f"Recording {adapter.metadata.task if adapter.metadata else 'unknown'} "
                "missing session_id"
            )

    def test_all_recordings_have_result(
        self, all_recording_adapters: list[RecordingEventStreamAdapter]
    ) -> None:
        """Every recording has a result event."""
        for adapter in all_recording_adapters:
            events = adapter.get_events()
            result_events = [e for e in events if e.get("type") == "result"]
            assert len(result_events) >= 1, (
                f"Recording {adapter.metadata.task if adapter.metadata else 'unknown'} "
                "missing result event"
            )

    def test_all_recordings_have_metadata(
        self, all_recording_adapters: list[RecordingEventStreamAdapter]
    ) -> None:
        """Every recording has metadata."""
        for adapter in all_recording_adapters:
            assert adapter.metadata is not None
            assert adapter.metadata.cli_version is not None
            assert adapter.metadata.model is not None


# =============================================================================
# OBSERVABILITY METRIC EXTRACTION
# =============================================================================


class TestMetricExtraction:
    """Test extracting observability metrics from recordings."""

    def test_extract_session_summary(
        self, all_recording_adapters: list[RecordingEventStreamAdapter]
    ) -> None:
        """Can extract session summary from any recording."""
        for adapter in all_recording_adapters:
            events = adapter.get_events()

            # Extract session summary
            summary = self._extract_session_summary(events)

            assert summary["session_id"] is not None
            assert summary["event_count"] > 0
            assert summary["has_result"] is True

    def test_extract_cost_summary(
        self, all_recording_adapters: list[RecordingEventStreamAdapter]
    ) -> None:
        """Can extract cost from any recording."""
        for adapter in all_recording_adapters:
            events = adapter.get_events()
            result = next((e for e in events if e.get("type") == "result"), None)

            if result:
                cost = result.get("total_cost_usd")
                assert cost is not None, (
                    f"Recording {adapter.metadata.task if adapter.metadata else 'unknown'} "
                    "missing cost"
                )

    def _extract_session_summary(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Extract a session summary from events."""
        session_id = None
        for e in events:
            if e.get("session_id"):
                session_id = e.get("session_id")
                break

        result = next((e for e in events if e.get("type") == "result"), None)

        return {
            "session_id": session_id,
            "event_count": len(events),
            "has_result": result is not None,
            "total_cost_usd": result.get("total_cost_usd") if result else None,
            "duration_ms": result.get("duration_ms") if result else None,
        }
