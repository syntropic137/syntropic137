"""Integration tests for RecordingEventStreamAdapter with WorkspaceService.

These tests demonstrate the full pattern of using recordings
for integration testing without API calls.
"""

from __future__ import annotations

import json

import pytest

from aef_adapters.workspace_backends.recording import RecordingEventStreamAdapter

pytestmark = [pytest.mark.unit, pytest.mark.integration]  # Runs in CI - no external services


class TestRecordingIntegration:
    """Integration tests using recorded sessions."""

    @pytest.fixture
    def simple_bash_adapter(self) -> RecordingEventStreamAdapter:
        """Adapter loaded with simple-bash recording."""
        try:
            return RecordingEventStreamAdapter("simple-bash")
        except FileNotFoundError:
            pytest.skip("simple-bash recording not available")

    def test_adapter_has_expected_events(
        self, simple_bash_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Recording has expected event structure."""
        events = simple_bash_adapter.get_events()

        # Should have multiple events
        assert len(events) >= 3

        # Should have system init
        init_events = [
            e for e in events if e.get("type") == "system" and e.get("subtype") == "init"
        ]
        assert len(init_events) == 1

        # Init should have session info
        init = init_events[0]
        assert "session_id" in init
        assert "tools" in init
        assert "model" in init

    def test_adapter_has_tool_usage(
        self, simple_bash_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Recording captures tool usage."""
        events = simple_bash_adapter.get_events()

        # Should have assistant messages (which contain tool use)
        assistant_events = [e for e in events if e.get("type") == "assistant"]
        assert len(assistant_events) > 0

    def test_adapter_has_result(
        self, simple_bash_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Recording has final result event."""
        events = simple_bash_adapter.get_events()

        # Should have result event
        result_events = [e for e in events if e.get("type") == "result"]
        assert len(result_events) == 1

        result = result_events[0]
        assert "duration_ms" in result
        assert "total_cost_usd" in result

    @pytest.mark.asyncio
    async def test_stream_produces_valid_jsonl(
        self, simple_bash_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Stream produces valid JSONL that can be parsed."""
        from unittest.mock import MagicMock

        mock_handle = MagicMock()
        lines = []

        async for line in simple_bash_adapter.stream(mock_handle, ["test"]):
            lines.append(line)
            # Verify each line parses as JSON
            parsed = json.loads(line)
            assert isinstance(parsed, dict)

        assert len(lines) == simple_bash_adapter.event_count


class TestMultipleRecordings:
    """Tests demonstrating multiple recording scenarios."""

    @pytest.mark.parametrize(
        "recording_name",
        [
            "simple-bash",
            "file-create",
            "file-read",
            "git-status",
            "multi-tool",
        ],
    )
    def test_recording_loads_successfully(self, recording_name: str) -> None:
        """Each recording loads and has valid structure."""
        try:
            adapter = RecordingEventStreamAdapter(recording_name)
        except FileNotFoundError:
            pytest.skip(f"{recording_name} recording not available")

        # Basic validation
        assert adapter.event_count > 0
        assert adapter.metadata is not None
        assert adapter.session_id is not None

        # Has required event types
        events = adapter.get_events()
        event_types = {e.get("type") for e in events}

        assert "system" in event_types, f"{recording_name} missing system event"
        assert "result" in event_types, f"{recording_name} missing result event"

    @pytest.mark.parametrize(
        "recording_name",
        [
            "simple-bash",
            "file-create",
            "multi-tool",
        ],
    )
    def test_recording_has_tool_use(self, recording_name: str) -> None:
        """Recordings with tool use have assistant events."""
        try:
            adapter = RecordingEventStreamAdapter(recording_name)
        except FileNotFoundError:
            pytest.skip(f"{recording_name} recording not available")

        events = adapter.get_events()
        assistant_events = [e for e in events if e.get("type") == "assistant"]

        assert len(assistant_events) > 0, f"{recording_name} has no tool use"


class TestEventPipelineSimulation:
    """Tests simulating the full event pipeline flow."""

    @pytest.mark.asyncio
    async def test_collect_events_from_stream(self) -> None:
        """Simulate collecting events like the real pipeline would."""
        from unittest.mock import MagicMock

        try:
            adapter = RecordingEventStreamAdapter("simple-bash")
        except FileNotFoundError:
            pytest.skip("simple-bash recording not available")

        mock_handle = MagicMock()

        # Simulate event collection (like EventCollector would do)
        collected_events = []

        async for line in adapter.stream(mock_handle, ["claude", "-p", "test"]):
            event = json.loads(line)
            # Add collection metadata (like real collector)
            event["_collected_at"] = "2025-12-20T00:00:00Z"
            collected_events.append(event)

        # Verify collection
        assert len(collected_events) == adapter.event_count

        # All events have collection timestamp
        assert all("_collected_at" in e for e in collected_events)

        # Session ID is consistent
        session_ids = {e.get("session_id") for e in collected_events}
        assert len(session_ids) == 1

    @pytest.mark.asyncio
    async def test_extract_metrics_from_events(self) -> None:
        """Extract metrics from recorded events (like projections would)."""
        from unittest.mock import MagicMock

        try:
            adapter = RecordingEventStreamAdapter("simple-bash")
        except FileNotFoundError:
            pytest.skip("simple-bash recording not available")

        mock_handle = MagicMock()

        # Collect events
        events = []
        async for line in adapter.stream(mock_handle, ["test"]):
            events.append(json.loads(line))

        # Extract metrics (like SessionProjection would)
        result_event = next((e for e in events if e.get("type") == "result"), None)
        assert result_event is not None

        metrics = {
            "session_id": adapter.session_id,
            "duration_ms": result_event.get("duration_ms"),
            "total_cost_usd": result_event.get("total_cost_usd"),
            "num_turns": result_event.get("num_turns"),
            "is_error": result_event.get("is_error", False),
        }

        # Verify extracted metrics
        assert metrics["session_id"] is not None
        assert metrics["duration_ms"] is not None
        assert metrics["total_cost_usd"] is not None
        assert metrics["is_error"] is False
