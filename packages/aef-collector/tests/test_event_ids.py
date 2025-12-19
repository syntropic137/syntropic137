"""Tests for event ID generation functions."""

from datetime import UTC, datetime

import pytest

from aef_collector.events.ids import (
    generate_event_id,
    generate_git_event_id,
    generate_notification_event_id,
    generate_session_event_id,
    generate_stop_event_id,
    generate_token_event_id,
    generate_tool_event_id,
    generate_user_prompt_event_id,
)


@pytest.mark.unit
class TestGenerateEventId:
    """Tests for the base generate_event_id function."""

    def test_returns_32_char_hex(self) -> None:
        """Event ID should be 32 character hex string."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result = generate_event_id("session-123", "test_event", ts)

        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self) -> None:
        """Same inputs should produce same output."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_event_id("session-123", "test_event", ts)
        result2 = generate_event_id("session-123", "test_event", ts)

        assert result1 == result2

    def test_different_session_different_id(self) -> None:
        """Different session should produce different ID."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_event_id("session-123", "test_event", ts)
        result2 = generate_event_id("session-456", "test_event", ts)

        assert result1 != result2

    def test_different_event_type_different_id(self) -> None:
        """Different event type should produce different ID."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_event_id("session-123", "type_a", ts)
        result2 = generate_event_id("session-123", "type_b", ts)

        assert result1 != result2

    def test_different_timestamp_different_id(self) -> None:
        """Different timestamp should produce different ID."""
        ts1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        ts2 = datetime(2025, 1, 1, 12, 0, 1, tzinfo=UTC)

        result1 = generate_event_id("session-123", "test_event", ts1)
        result2 = generate_event_id("session-123", "test_event", ts2)

        assert result1 != result2

    def test_with_content_hash(self) -> None:
        """Content hash should affect the ID."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_event_id("session-123", "test_event", ts, "hash1")
        result2 = generate_event_id("session-123", "test_event", ts, "hash2")
        result3 = generate_event_id("session-123", "test_event", ts, None)

        assert result1 != result2
        assert result1 != result3


class TestGenerateToolEventId:
    """Tests for tool event ID generation."""

    def test_includes_tool_info(self) -> None:
        """Tool name and ID should affect the event ID."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_tool_event_id("s1", "tool_started", ts, "Read", "toolu_01")
        result2 = generate_tool_event_id("s1", "tool_started", ts, "Write", "toolu_01")
        result3 = generate_tool_event_id("s1", "tool_started", ts, "Read", "toolu_02")

        assert result1 != result2  # Different tool
        assert result1 != result3  # Different tool_use_id


class TestGenerateTokenEventId:
    """Tests for token usage event ID generation."""

    def test_includes_message_uuid(self) -> None:
        """Message UUID should affect the event ID."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_token_event_id("s1", ts, "msg-001")
        result2 = generate_token_event_id("s1", ts, "msg-002")

        assert result1 != result2


class TestGenerateSessionEventId:
    """Tests for session event ID generation."""

    def test_session_started_ended_different(self) -> None:
        """Started and ended should produce different IDs."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_session_event_id("s1", "session_started", ts)
        result2 = generate_session_event_id("s1", "session_ended", ts)

        assert result1 != result2


class TestGenerateUserPromptEventId:
    """Tests for user prompt event ID generation."""

    def test_includes_prompt_hash(self) -> None:
        """Prompt hash should affect the event ID."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_user_prompt_event_id("s1", ts, "hash_of_prompt_1")
        result2 = generate_user_prompt_event_id("s1", ts, "hash_of_prompt_2")

        assert result1 != result2


class TestGenerateStopEventId:
    """Tests for stop event ID generation."""

    def test_returns_valid_id(self) -> None:
        """Stop event ID should be valid 32 char hex."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result = generate_stop_event_id("session-123", ts)

        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self) -> None:
        """Same inputs should produce same output."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_stop_event_id("session-123", ts)
        result2 = generate_stop_event_id("session-123", ts)

        assert result1 == result2

    def test_agent_vs_subagent_different(self) -> None:
        """Agent stopped vs subagent stopped should produce different IDs."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_stop_event_id("s1", ts, "agent_stopped")
        result2 = generate_stop_event_id("s1", ts, "subagent_stopped")

        assert result1 != result2

    def test_default_event_type(self) -> None:
        """Default event type should be agent_stopped."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_stop_event_id("s1", ts)
        result2 = generate_stop_event_id("s1", ts, "agent_stopped")

        assert result1 == result2


class TestGenerateNotificationEventId:
    """Tests for notification event ID generation."""

    def test_returns_valid_id(self) -> None:
        """Notification event ID should be valid 32 char hex."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result = generate_notification_event_id("session-123", ts, "content_hash_abc")

        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self) -> None:
        """Same inputs should produce same output."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_notification_event_id("s1", ts, "hash123")
        result2 = generate_notification_event_id("s1", ts, "hash123")

        assert result1 == result2

    def test_different_content_different_id(self) -> None:
        """Different content should produce different IDs."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_notification_event_id("s1", ts, "hash_content_1")
        result2 = generate_notification_event_id("s1", ts, "hash_content_2")

        assert result1 != result2


class TestGenerateGitEventId:
    """Tests for git event ID generation."""

    def test_returns_valid_id(self) -> None:
        """Git event ID should be valid 32 char hex."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result = generate_git_event_id(
            "session-123",
            "git_commit",
            ts,
            commit_hash="abc123def456",
        )

        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self) -> None:
        """Same inputs should produce same output."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_git_event_id("s1", "git_commit", ts, commit_hash="abc123")
        result2 = generate_git_event_id("s1", "git_commit", ts, commit_hash="abc123")

        assert result1 == result2

    def test_different_commit_hash_different_id(self) -> None:
        """Different commit hash should produce different IDs."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_git_event_id("s1", "git_commit", ts, commit_hash="abc123")
        result2 = generate_git_event_id("s1", "git_commit", ts, commit_hash="def456")

        assert result1 != result2

    def test_different_branch_different_id(self) -> None:
        """Different branch should produce different IDs."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_git_event_id("s1", "git_branch_created", ts, branch="main")
        result2 = generate_git_event_id("s1", "git_branch_created", ts, branch="dev")

        assert result1 != result2

    def test_different_event_types(self) -> None:
        """Different git event types should produce different IDs."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_git_event_id("s1", "git_commit", ts, commit_hash="abc")
        result2 = generate_git_event_id("s1", "git_push_started", ts, commit_hash="abc")

        assert result1 != result2

    def test_commit_with_branch(self) -> None:
        """Commit hash and branch together should work."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result1 = generate_git_event_id("s1", "git_commit", ts, commit_hash="abc", branch="main")
        result2 = generate_git_event_id("s1", "git_commit", ts, commit_hash="abc", branch="dev")

        assert result1 != result2

    def test_no_commit_or_branch(self) -> None:
        """Git event without commit or branch should still work."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result = generate_git_event_id("s1", "git_push_started", ts)

        assert len(result) == 32

    @pytest.mark.parametrize(
        "event_type",
        [
            "git_commit",
            "git_branch_created",
            "git_branch_switched",
            "git_merge_completed",
            "git_commits_rewritten",
            "git_push_started",
            "git_push_completed",
        ],
    )
    def test_all_git_event_types(self, event_type: str) -> None:
        """All git event types should produce valid IDs."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result = generate_git_event_id(
            "session-123",
            event_type,
            ts,
            commit_hash="abc123",
            branch="main",
        )

        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)
