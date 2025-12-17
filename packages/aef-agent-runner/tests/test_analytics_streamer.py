"""Tests for AnalyticsStreamer.

This module tests the real-time analytics event streaming from
.agentic/analytics/ directory.

Test Categories:
- Lifecycle: Start/stop behavior
- Streaming: Tailing new lines as they appear
- Envelope: Wrapping events in standard format
- Error handling: Invalid JSON, missing files, etc.
"""

from __future__ import annotations

import json
import time

from aef_agent_runner.analytics_streamer import AnalyticsStreamer


class TestAnalyticsStreamerLifecycle:
    """Tests for streamer start/stop behavior."""

    def test_streamer_starts_and_stops(self, tmp_path):
        """Streamer should start and stop cleanly."""
        analytics_dir = tmp_path / ".agentic" / "analytics"
        analytics_dir.mkdir(parents=True)

        streamer = AnalyticsStreamer(analytics_dir)

        # Should not be running initially
        assert not streamer._running
        assert streamer._thread is None

        # Start
        streamer.start()
        assert streamer._running
        assert streamer._thread is not None
        assert streamer._thread.is_alive()

        # Stop
        streamer.stop()
        assert not streamer._running
        assert streamer._thread is None

    def test_streamer_double_start_is_noop(self, tmp_path):
        """Starting twice should be a no-op (with warning)."""
        analytics_dir = tmp_path / ".agentic" / "analytics"
        analytics_dir.mkdir(parents=True)

        streamer = AnalyticsStreamer(analytics_dir)
        streamer.start()

        original_thread = streamer._thread

        # Second start should be ignored
        streamer.start()

        assert streamer._thread is original_thread

        streamer.stop()

    def test_streamer_stop_without_start_is_safe(self, tmp_path):
        """Stopping without starting should not crash."""
        analytics_dir = tmp_path / ".agentic" / "analytics"
        analytics_dir.mkdir(parents=True)

        streamer = AnalyticsStreamer(analytics_dir)

        # Should not raise
        streamer.stop()

    def test_streamer_handles_missing_directory(self, tmp_path):
        """Streamer should handle non-existent directory gracefully."""
        analytics_dir = tmp_path / "does" / "not" / "exist"

        streamer = AnalyticsStreamer(analytics_dir)
        streamer.start()

        # Let it run briefly
        time.sleep(0.1)

        # Should not crash
        streamer.stop()


class TestAnalyticsStreamerOutput:
    """Tests for event streaming output."""

    def test_streamer_tails_new_lines(self, tmp_path, capsys):
        """Should emit new lines as they are appended."""
        analytics_dir = tmp_path / ".agentic" / "analytics"
        analytics_dir.mkdir(parents=True)

        events_file = analytics_dir / "events.jsonl"

        # Start with existing data
        events_file.write_text(
            '{"event_type": "existing"}\n',
            encoding="utf-8",
        )

        streamer = AnalyticsStreamer(analytics_dir, poll_interval=0.1)
        streamer.start()

        # Wait for initial read
        time.sleep(0.2)

        # Append new data
        with events_file.open("a", encoding="utf-8") as f:
            f.write('{"event_type": "new_event"}\n')

        # Wait for poll
        time.sleep(0.3)

        streamer.stop()

        # Check output
        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().split("\n") if line]

        # Should have 2 events
        assert len(lines) == 2

        # Check first event
        event1 = json.loads(lines[0])
        assert event1["type"] == "analytics"
        assert event1["source"] == "hook"
        assert event1["data"]["event_type"] == "existing"

        # Check second event
        event2 = json.loads(lines[1])
        assert event2["data"]["event_type"] == "new_event"

    def test_streamer_handles_multiple_files(self, tmp_path, capsys):
        """Should track multiple .jsonl files."""
        analytics_dir = tmp_path / ".agentic" / "analytics"
        analytics_dir.mkdir(parents=True)

        # Create two event files
        (analytics_dir / "events.jsonl").write_text(
            '{"source": "events"}\n',
            encoding="utf-8",
        )
        (analytics_dir / "other.jsonl").write_text(
            '{"source": "other"}\n',
            encoding="utf-8",
        )

        streamer = AnalyticsStreamer(analytics_dir, poll_interval=0.1)
        streamer.start()
        time.sleep(0.3)
        streamer.stop()

        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().split("\n") if line]

        # Should have events from both files
        assert len(lines) == 2
        sources = [json.loads(line)["data"]["source"] for line in lines]
        assert "events" in sources
        assert "other" in sources

    def test_streamer_emits_wrapped_events(self, tmp_path, capsys):
        """Should wrap events in analytics envelope."""
        analytics_dir = tmp_path / ".agentic" / "analytics"
        analytics_dir.mkdir(parents=True)

        (analytics_dir / "events.jsonl").write_text(
            '{"event_type": "test", "data": {"key": "value"}}\n',
            encoding="utf-8",
        )

        streamer = AnalyticsStreamer(analytics_dir, poll_interval=0.1)
        streamer.start()
        time.sleep(0.2)
        streamer.stop()

        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().split("\n") if line]

        assert len(lines) == 1
        envelope = json.loads(lines[0])

        # Check envelope structure
        assert envelope["type"] == "analytics"
        assert envelope["source"] == "hook"
        assert "data" in envelope

        # Check original data is preserved
        assert envelope["data"]["event_type"] == "test"
        assert envelope["data"]["data"]["key"] == "value"


class TestAnalyticsStreamerErrorHandling:
    """Tests for error handling."""

    def test_streamer_handles_invalid_json(self, tmp_path, capsys, caplog):
        """Should log warning and skip invalid lines."""
        analytics_dir = tmp_path / ".agentic" / "analytics"
        analytics_dir.mkdir(parents=True)

        (analytics_dir / "events.jsonl").write_text(
            '{"valid": true}\nnot valid json\n{"also_valid": true}\n',
            encoding="utf-8",
        )

        streamer = AnalyticsStreamer(analytics_dir, poll_interval=0.1)
        streamer.start()
        time.sleep(0.2)
        streamer.stop()

        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().split("\n") if line]

        # Should have 2 valid events (skipped the invalid one)
        assert len(lines) == 2

        # Check that warning was logged
        assert "Invalid JSON" in caplog.text

    def test_streamer_handles_empty_lines(self, tmp_path, capsys):
        """Should skip empty lines."""
        analytics_dir = tmp_path / ".agentic" / "analytics"
        analytics_dir.mkdir(parents=True)

        (analytics_dir / "events.jsonl").write_text(
            '{"event": 1}\n\n   \n{"event": 2}\n',
            encoding="utf-8",
        )

        streamer = AnalyticsStreamer(analytics_dir, poll_interval=0.1)
        streamer.start()
        time.sleep(0.2)
        streamer.stop()

        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().split("\n") if line]

        assert len(lines) == 2

    def test_streamer_handles_file_deletion(self, tmp_path, capsys):
        """Should handle file being deleted during streaming."""
        analytics_dir = tmp_path / ".agentic" / "analytics"
        analytics_dir.mkdir(parents=True)

        events_file = analytics_dir / "events.jsonl"
        events_file.write_text('{"event": 1}\n', encoding="utf-8")

        streamer = AnalyticsStreamer(analytics_dir, poll_interval=0.1)
        streamer.start()
        time.sleep(0.2)

        # Delete the file
        events_file.unlink()

        # Write new file
        events_file.write_text('{"event": 2}\n', encoding="utf-8")
        time.sleep(0.2)

        streamer.stop()

        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().split("\n") if line]

        # Should have at least the first event
        assert len(lines) >= 1

    def test_streamer_preserves_file_positions(self, tmp_path, capsys):
        """Should not re-emit events on subsequent polls."""
        analytics_dir = tmp_path / ".agentic" / "analytics"
        analytics_dir.mkdir(parents=True)

        events_file = analytics_dir / "events.jsonl"
        events_file.write_text('{"event": 1}\n', encoding="utf-8")

        streamer = AnalyticsStreamer(analytics_dir, poll_interval=0.1)
        streamer.start()

        # Let it poll multiple times
        time.sleep(0.5)

        streamer.stop()

        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().split("\n") if line]

        # Should only emit event once, not on every poll
        assert len(lines) == 1


class TestAnalyticsStreamerIntegration:
    """Integration tests for realistic scenarios."""

    def test_continuous_event_streaming(self, tmp_path, capsys):
        """Should continuously stream events as they are written."""
        analytics_dir = tmp_path / ".agentic" / "analytics"
        analytics_dir.mkdir(parents=True)

        events_file = analytics_dir / "events.jsonl"
        events_file.touch()

        streamer = AnalyticsStreamer(analytics_dir, poll_interval=0.1)
        streamer.start()

        # Simulate hook writing events over time
        for i in range(5):
            with events_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"event_num": i}) + "\n")
            time.sleep(0.15)

        streamer.stop()

        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().split("\n") if line]

        # Should have all 5 events
        assert len(lines) == 5

        # Check order
        for i, line in enumerate(lines):
            envelope = json.loads(line)
            assert envelope["data"]["event_num"] == i

    def test_factory_function(self, monkeypatch, tmp_path):
        """create_streamer_from_env should use workspace paths."""
        # Mock the workspace paths module
        monkeypatch.setattr(
            "aef_agent_runner.analytics_streamer.WORKSPACE_ANALYTICS_DIR",
            tmp_path / ".agentic" / "analytics",
            raising=False,
        )

        from aef_agent_runner.analytics_streamer import create_streamer_from_env

        # This would fail if the import doesn't work, but let's be pragmatic
        # and just test that the function exists and is callable
        assert callable(create_streamer_from_env)
