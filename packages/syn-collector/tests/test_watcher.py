"""Tests for file watchers."""

import json
from pathlib import Path

import pytest

from syn_collector.events.types import EventType
from syn_collector.watcher.hooks import HookWatcher
from syn_collector.watcher.transcript import TranscriptWatcher


@pytest.mark.unit
class TestHookWatcher:
    """Tests for the hook event watcher."""

    @pytest.fixture
    def temp_hook_file(self, tmp_path: Path) -> Path:
        """Create a temporary hook events file."""
        hook_file = tmp_path / "events.jsonl"
        return hook_file

    @pytest.mark.asyncio
    async def test_read_empty_file(self, temp_hook_file: Path) -> None:
        """Reading non-existent file returns empty list."""
        watcher = HookWatcher(temp_hook_file)

        events = await watcher.read_existing()

        assert events == []

    @pytest.mark.asyncio
    async def test_read_existing_events(self, temp_hook_file: Path) -> None:
        """Read existing events from file."""
        # Write test events
        events_data = [
            {
                "event_type": "tool_execution_started",
                "session_id": "session-123",
                "tool_name": "Read",
                "tool_use_id": "toolu_01ABC",
                "timestamp": "2025-01-01T12:00:00Z",
            },
            {
                "event_type": "tool_execution_completed",
                "session_id": "session-123",
                "tool_name": "Read",
                "tool_use_id": "toolu_01ABC",
                "timestamp": "2025-01-01T12:00:01Z",
            },
        ]

        with temp_hook_file.open("w") as f:
            for event in events_data:
                f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hook_file)
        events = await watcher.read_existing()

        assert len(events) == 2
        assert events[0].event_type == EventType.TOOL_EXECUTION_STARTED
        assert events[1].event_type == EventType.TOOL_EXECUTION_COMPLETED
        assert events[0].data["tool_name"] == "Read"

    @pytest.mark.asyncio
    async def test_parse_session_events(self, temp_hook_file: Path) -> None:
        """Parse session start/end events."""
        events_data = [
            {
                "event_type": "session_started",
                "session_id": "session-123",
                "timestamp": "2025-01-01T12:00:00Z",
            },
            {
                "event_type": "session_ended",
                "session_id": "session-123",
                "timestamp": "2025-01-01T13:00:00Z",
            },
        ]

        with temp_hook_file.open("w") as f:
            for event in events_data:
                f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hook_file)
        events = await watcher.read_existing()

        assert len(events) == 2
        assert events[0].event_type == EventType.SESSION_STARTED
        assert events[1].event_type == EventType.SESSION_ENDED

    @pytest.mark.asyncio
    async def test_skip_invalid_json(self, temp_hook_file: Path) -> None:
        """Invalid JSON lines should be skipped."""
        with temp_hook_file.open("w") as f:
            f.write(
                '{"event_type": "session_started", "session_id": "s1", "timestamp": "2025-01-01T12:00:00Z"}\n'
            )
            f.write("not valid json\n")
            f.write(
                '{"event_type": "session_ended", "session_id": "s1", "timestamp": "2025-01-01T13:00:00Z"}\n'
            )

        watcher = HookWatcher(temp_hook_file)
        events = await watcher.read_existing()

        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_position_tracking(self, temp_hook_file: Path) -> None:
        """Position should be tracked after reading."""
        events_data = [
            {
                "event_type": "session_started",
                "session_id": "session-123",
                "timestamp": "2025-01-01T12:00:00Z",
            },
        ]

        with temp_hook_file.open("w") as f:
            for event in events_data:
                f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hook_file)
        await watcher.read_existing()

        assert watcher.get_position() > 0

    @pytest.mark.asyncio
    async def test_parse_git_commit_event(self, temp_hook_file: Path) -> None:
        """Parse git commit events."""
        events_data = [
            {
                "event_type": "git_commit",
                "session_id": "session-123",
                "timestamp": "2025-01-01T12:00:00Z",
                "commit_hash": "abc123def456",
                "commit_message": "feat: add feature",
                "author": "Developer",
                "branch": "main",
                "files_changed": 5,
                "insertions": 120,
                "deletions": 30,
                "estimated_tokens_added": 450,
                "estimated_tokens_removed": 112,
            },
        ]

        with temp_hook_file.open("w") as f:
            for event in events_data:
                f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hook_file)
        events = await watcher.read_existing()

        assert len(events) == 1
        assert events[0].event_type == EventType.GIT_COMMIT
        assert events[0].data["commit_hash"] == "abc123def456"
        assert events[0].data["branch"] == "main"
        assert events[0].data["insertions"] == 120

    @pytest.mark.asyncio
    async def test_parse_git_branch_events(self, temp_hook_file: Path) -> None:
        """Parse git branch created and switched events."""
        events_data = [
            {
                "event_type": "git_branch_created",
                "session_id": "session-123",
                "timestamp": "2025-01-01T12:00:00Z",
                "branch": "feat/new-feature",
                "from_ref": "main",
            },
            {
                "event_type": "git_branch_switched",
                "session_id": "session-123",
                "timestamp": "2025-01-01T12:00:01Z",
                "branch": "main",
                "previous_branch": "feat/new-feature",
            },
        ]

        with temp_hook_file.open("w") as f:
            for event in events_data:
                f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hook_file)
        events = await watcher.read_existing()

        assert len(events) == 2
        assert events[0].event_type == EventType.GIT_BRANCH_CREATED
        assert events[0].data["branch"] == "feat/new-feature"
        assert events[1].event_type == EventType.GIT_BRANCH_SWITCHED
        assert events[1].data["previous_branch"] == "feat/new-feature"

    @pytest.mark.asyncio
    async def test_parse_git_merge_event(self, temp_hook_file: Path) -> None:
        """Parse git merge completed event."""
        events_data = [
            {
                "event_type": "git_merge_completed",
                "session_id": "session-123",
                "timestamp": "2025-01-01T12:00:00Z",
                "branch": "main",
                "merge_head": "feat/feature",
                "merge_mode": "normal",
            },
        ]

        with temp_hook_file.open("w") as f:
            for event in events_data:
                f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hook_file)
        events = await watcher.read_existing()

        assert len(events) == 1
        assert events[0].event_type == EventType.GIT_MERGE_COMPLETED
        assert events[0].data["merge_head"] == "feat/feature"

    @pytest.mark.asyncio
    async def test_parse_git_push_events(self, temp_hook_file: Path) -> None:
        """Parse git push started event."""
        events_data = [
            {
                "event_type": "git_push_started",
                "session_id": "session-123",
                "timestamp": "2025-01-01T12:00:00Z",
                "remote": "origin",
                "branch": "main",
                "commit_count": 3,
            },
        ]

        with temp_hook_file.open("w") as f:
            for event in events_data:
                f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hook_file)
        events = await watcher.read_existing()

        assert len(events) == 1
        assert events[0].event_type == EventType.GIT_PUSH_STARTED
        assert events[0].data["commit_count"] == 3

    @pytest.mark.asyncio
    async def test_parse_git_rewrite_event(self, temp_hook_file: Path) -> None:
        """Parse git commits rewritten event (rebase/amend)."""
        events_data = [
            {
                "event_type": "git_commits_rewritten",
                "session_id": "session-123",
                "timestamp": "2025-01-01T12:00:00Z",
                "branch": "feat/feature",
                "command": "rebase",
                "rewritten_count": 5,
            },
        ]

        with temp_hook_file.open("w") as f:
            for event in events_data:
                f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hook_file)
        events = await watcher.read_existing()

        assert len(events) == 1
        assert events[0].event_type == EventType.GIT_COMMITS_REWRITTEN
        assert events[0].data["command"] == "rebase"
        assert events[0].data["rewritten_count"] == 5

    @pytest.mark.asyncio
    async def test_parse_stop_events(self, temp_hook_file: Path) -> None:
        """Parse agent stopped and subagent stopped events."""
        events_data = [
            {
                "event_type": "agent_stopped",
                "session_id": "session-123",
                "timestamp": "2025-01-01T12:00:00Z",
                "reason": "normal_completion",
            },
            {
                "event_type": "subagent_stopped",
                "session_id": "session-456",
                "timestamp": "2025-01-01T12:00:01Z",
                "reason": "task_complete",
                "parent_session_id": "session-123",
            },
        ]

        with temp_hook_file.open("w") as f:
            for event in events_data:
                f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hook_file)
        events = await watcher.read_existing()

        assert len(events) == 2
        assert events[0].event_type == EventType.AGENT_STOPPED
        assert events[0].data["reason"] == "normal_completion"
        assert events[1].event_type == EventType.SUBAGENT_STOPPED
        assert events[1].data["parent_session_id"] == "session-123"

    @pytest.mark.asyncio
    async def test_parse_notification_event(self, temp_hook_file: Path) -> None:
        """Parse notification sent event."""
        events_data = [
            {
                "event_type": "notification_sent",
                "session_id": "session-123",
                "timestamp": "2025-01-01T12:00:00Z",
                "notification_type": "completion",
                "content_preview": "Task completed successfully...",
            },
        ]

        with temp_hook_file.open("w") as f:
            for event in events_data:
                f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hook_file)
        events = await watcher.read_existing()

        assert len(events) == 1
        assert events[0].event_type == EventType.NOTIFICATION_SENT
        assert events[0].data["notification_type"] == "completion"

    @pytest.mark.asyncio
    async def test_handler_name_mapping(self, temp_hook_file: Path) -> None:
        """Handler names should map to correct event types."""
        events_data = [
            {
                "handler": "stop",
                "session_id": "session-123",
                "timestamp": "2025-01-01T12:00:00Z",
            },
            {
                "handler": "notification",
                "session_id": "session-123",
                "timestamp": "2025-01-01T12:00:01Z",
            },
        ]

        with temp_hook_file.open("w") as f:
            for event in events_data:
                f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hook_file)
        events = await watcher.read_existing()

        assert len(events) == 2
        assert events[0].event_type == EventType.AGENT_STOPPED
        assert events[1].event_type == EventType.NOTIFICATION_SENT


class TestTranscriptWatcher:
    """Tests for the transcript watcher."""

    @pytest.fixture
    def temp_transcript_file(self, tmp_path: Path) -> Path:
        """Create a temporary transcript file."""
        transcript_file = tmp_path / "session.jsonl"
        return transcript_file

    @pytest.mark.asyncio
    async def test_read_empty_file(self, temp_transcript_file: Path) -> None:
        """Reading non-existent file returns empty list."""
        watcher = TranscriptWatcher(temp_transcript_file)

        events = await watcher.read_existing()

        assert events == []

    @pytest.mark.asyncio
    async def test_read_token_usage(self, temp_transcript_file: Path) -> None:
        """Read token usage from assistant messages."""
        messages = [
            {
                "uuid": "user-msg-001",
                "type": "user",
                "message": {"role": "user", "content": "Hello"},
                "timestamp": "2025-01-01T12:00:00Z",
                "sessionId": "session-123",
            },
            {
                "uuid": "asst-msg-001",
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": "Hi there!",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
                "timestamp": "2025-01-01T12:00:01Z",
                "sessionId": "session-123",
            },
        ]

        with temp_transcript_file.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        watcher = TranscriptWatcher(temp_transcript_file)
        events = await watcher.read_existing()

        # Only assistant message with usage should produce event
        assert len(events) == 1
        assert events[0].event_type == EventType.TOKEN_USAGE
        assert events[0].data["input_tokens"] == 100
        assert events[0].data["output_tokens"] == 50

    @pytest.mark.asyncio
    async def test_skip_messages_without_usage(self, temp_transcript_file: Path) -> None:
        """Messages without usage data should be skipped."""
        messages = [
            {
                "uuid": "asst-msg-001",
                "type": "assistant",
                "message": {"role": "assistant", "content": "Hi!"},  # No usage
                "timestamp": "2025-01-01T12:00:01Z",
                "sessionId": "session-123",
            },
        ]

        with temp_transcript_file.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        watcher = TranscriptWatcher(temp_transcript_file)
        events = await watcher.read_existing()

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_session_id_from_file_path(self, tmp_path: Path) -> None:
        """Session ID can be extracted from file name."""
        transcript_file = tmp_path / "my-session-id.jsonl"

        messages = [
            {
                "uuid": "asst-msg-001",
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
                "timestamp": "2025-01-01T12:00:01Z",
                # No sessionId field
            },
        ]

        with transcript_file.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        watcher = TranscriptWatcher(transcript_file)
        events = await watcher.read_existing()

        assert len(events) == 1
        assert events[0].session_id == "my-session-id"

    @pytest.mark.asyncio
    async def test_watch_directory(self, tmp_path: Path) -> None:
        """Watch all JSONL files in a directory."""
        # Create multiple transcript files
        for i in range(2):
            file = tmp_path / f"session-{i}.jsonl"
            msg = {
                "uuid": f"msg-{i}",
                "type": "assistant",
                "message": {"usage": {"input_tokens": 100 * (i + 1), "output_tokens": 50}},
                "timestamp": "2025-01-01T12:00:00Z",
                "sessionId": f"session-{i}",
            }
            with file.open("w") as f:
                f.write(json.dumps(msg) + "\n")

        watcher = TranscriptWatcher(tmp_path)
        events = await watcher.read_existing()

        assert len(events) == 2
