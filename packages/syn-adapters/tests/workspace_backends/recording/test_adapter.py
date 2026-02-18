"""Unit tests for RecordingEventStreamAdapter."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 - used at runtime in fixture
from unittest.mock import MagicMock

import pytest

from syn_adapters.workspace_backends.recording import RecordingEventStreamAdapter
from syn_adapters.workspace_backends.recording.adapter import (
    RecordingAdapterTestOnlyError,
    _assert_test_environment,
)

pytestmark = pytest.mark.unit


class TestAssertTestEnvironment:
    """Tests for _assert_test_environment guard."""

    def test_allows_pytest_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Allows when PYTEST_CURRENT_TEST is set."""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_something")
        # Should not raise
        _assert_test_environment()

    def test_allows_app_environment_test(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Allows when APP_ENVIRONMENT=test."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        _assert_test_environment()

    def test_allows_app_environment_testing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Allows when APP_ENVIRONMENT=testing."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("APP_ENVIRONMENT", "testing")
        _assert_test_environment()

    def test_rejects_production_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rejects when not in test environment."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("APP_ENVIRONMENT", "production")

        with pytest.raises(RecordingAdapterTestOnlyError):
            _assert_test_environment()


class TestRecordingEventStreamAdapter:
    """Tests for RecordingEventStreamAdapter."""

    @pytest.fixture
    def sample_recording(self, tmp_path: Path) -> Path:
        """Create a sample recording file."""
        recording_path = tmp_path / "test-recording.jsonl"

        # Create minimal valid recording
        metadata = {
            "_recording": {
                "version": 1,
                "event_schema_version": 1,
                "cli_version": "2.0.74",
                "model": "claude-sonnet-4-5",
                "provider": "claude",
                "task": "test-task",
                "recorded_at": "2025-12-20T00:00:00Z",
                "duration_ms": 1000,
                "event_count": 2,
                "session_id": "test-session-123",
            }
        }

        events = [
            {"type": "system", "subtype": "init", "session_id": "test-session-123"},
            {"type": "result", "subtype": "success", "session_id": "test-session-123"},
        ]

        with recording_path.open("w") as f:
            f.write(json.dumps(metadata) + "\n")
            for event in events:
                event["_offset_ms"] = 0
                f.write(json.dumps(event) + "\n")

        return recording_path

    def test_init_with_path(self, sample_recording: Path) -> None:
        """Can initialize with Path to recording file."""
        adapter = RecordingEventStreamAdapter(sample_recording)

        assert adapter.event_count == 2
        assert adapter.session_id == "test-session-123"

    def test_init_with_session_player(self, sample_recording: Path) -> None:
        """Can initialize with SessionPlayer instance."""
        from agentic_events import SessionPlayer

        player = SessionPlayer(sample_recording)
        adapter = RecordingEventStreamAdapter(player)

        assert adapter.event_count == 2

    def test_metadata_accessible(self, sample_recording: Path) -> None:
        """Metadata is accessible via property."""
        adapter = RecordingEventStreamAdapter(sample_recording)

        assert adapter.metadata is not None
        assert adapter.metadata.cli_version == "2.0.74"
        assert adapter.metadata.model == "claude-sonnet-4-5"
        assert adapter.metadata.duration_ms == 1000

    def test_get_events(self, sample_recording: Path) -> None:
        """Can get all events from recording."""
        adapter = RecordingEventStreamAdapter(sample_recording)

        events = adapter.get_events()

        assert len(events) == 2
        assert events[0]["type"] == "system"
        assert events[1]["type"] == "result"

    @pytest.mark.asyncio
    async def test_stream_yields_jsonl(self, sample_recording: Path) -> None:
        """Stream yields JSONL strings."""
        adapter = RecordingEventStreamAdapter(sample_recording)

        # Create mock handle
        mock_handle = MagicMock()
        mock_handle.isolation_id = "test-123"

        lines = []
        async for line in adapter.stream(mock_handle, ["claude", "-p", "test"]):
            lines.append(line)

        assert len(lines) == 2

        # Verify each line is valid JSON
        for line in lines:
            parsed = json.loads(line)
            assert "type" in parsed
            assert "session_id" in parsed

    @pytest.mark.asyncio
    async def test_stream_instant_mode(self, sample_recording: Path) -> None:
        """Stream yields events instantly by default (no delays)."""
        import time

        adapter = RecordingEventStreamAdapter(sample_recording, realtime=False)
        mock_handle = MagicMock()

        start = time.monotonic()
        lines = []
        async for line in adapter.stream(mock_handle, ["test"]):
            lines.append(line)
        duration = time.monotonic() - start

        # Should be nearly instant (< 0.1s)
        assert duration < 0.1
        assert len(lines) == 2


class TestRecordingEventStreamAdapterWithFixtures:
    """Tests using real fixture recordings."""

    def test_load_by_task_name(self) -> None:
        """Can load recording by task name from fixtures."""
        # This will use load_recording() to find in fixtures
        try:
            adapter = RecordingEventStreamAdapter("simple-bash")
            assert adapter.event_count > 0
            assert adapter.metadata is not None
        except FileNotFoundError:
            pytest.skip("simple-bash recording not available")

    @pytest.mark.asyncio
    async def test_stream_real_recording(self) -> None:
        """Can stream events from real recording."""
        try:
            adapter = RecordingEventStreamAdapter("simple-bash")
        except FileNotFoundError:
            pytest.skip("simple-bash recording not available")

        mock_handle = MagicMock()
        events = []

        async for line in adapter.stream(mock_handle, ["test"]):
            events.append(json.loads(line))

        assert len(events) > 0
        # Should have system init event
        system_events = [e for e in events if e.get("type") == "system"]
        assert len(system_events) > 0


class TestRecordingAdapterWithWorkspace:
    """Tests for recordings with workspace files."""

    def test_load_with_recording_enum(self) -> None:
        """Can load recording using Recording enum."""
        from agentic_events import Recording

        try:
            adapter = RecordingEventStreamAdapter(Recording.ARTIFACT_WRITE)
            assert adapter.event_count > 0
        except FileNotFoundError:
            pytest.skip("artifact-write recording not available")

    def test_has_workspace(self) -> None:
        """Adapter reports has_workspace correctly."""
        from agentic_events import Recording

        try:
            adapter = RecordingEventStreamAdapter(Recording.ARTIFACT_WRITE)
            assert adapter.has_workspace is True
        except FileNotFoundError:
            pytest.skip("artifact-write recording not available")

    def test_get_workspace_files(self) -> None:
        """Can get workspace files from recording."""
        from agentic_events import Recording

        try:
            adapter = RecordingEventStreamAdapter(Recording.ARTIFACT_WRITE)
        except FileNotFoundError:
            pytest.skip("artifact-write recording not available")

        files = adapter.get_workspace_files()
        assert "artifacts/output/summary.md" in files

    def test_collect_files_with_pattern(self) -> None:
        """Can collect files matching a pattern."""
        from agentic_events import Recording

        try:
            adapter = RecordingEventStreamAdapter(Recording.ARTIFACT_WRITE)
        except FileNotFoundError:
            pytest.skip("artifact-write recording not available")

        files = adapter.collect_files(patterns=["artifacts/**/*"])
        assert len(files) > 0
        paths = [f[0] for f in files]
        assert "artifacts/output/summary.md" in paths

    def test_legacy_recording_has_no_workspace(self) -> None:
        """Legacy .jsonl recordings have no workspace."""
        try:
            adapter = RecordingEventStreamAdapter("simple-bash")
            assert adapter.has_workspace is False
            assert adapter.get_workspace_files() == {}
            assert adapter.collect_files() == []
        except FileNotFoundError:
            pytest.skip("simple-bash recording not available")
