"""Tests for content-based dedup key computation."""

from __future__ import annotations

from syn_domain.contexts.github.slices.event_pipeline.dedup_keys import compute_dedup_key

# ---------------------------------------------------------------------------
# Push events
# ---------------------------------------------------------------------------


class TestPushDedupKey:
    def test_push_uses_after_sha(self) -> None:
        payload = {
            "after": "abc123",
            "repository": {"full_name": "owner/repo"},
        }
        key = compute_dedup_key("push", "", payload)
        assert key == "push:owner/repo:abc123"

    def test_push_falls_back_to_head_commit_id(self) -> None:
        payload = {
            "head_commit": {"id": "def456"},
            "repository": {"full_name": "owner/repo"},
        }
        key = compute_dedup_key("push", "", payload)
        assert key == "push:owner/repo:def456"

    def test_push_identical_across_sources(self) -> None:
        """Webhook and Events API payloads produce the same key."""
        webhook_payload = {
            "after": "abc123",
            "repository": {"full_name": "owner/repo"},
        }
        # Events API payload has the same structure for push
        events_api_payload = {
            "after": "abc123",
            "repository": {"full_name": "owner/repo"},
        }
        assert compute_dedup_key("push", "", webhook_payload) == compute_dedup_key(
            "push", "", events_api_payload
        )


# ---------------------------------------------------------------------------
# Pull request events
# ---------------------------------------------------------------------------


class TestPullRequestDedupKey:
    def test_pr_opened(self) -> None:
        payload = {
            "number": 42,
            "pull_request": {"number": 42, "head": {"sha": "abc123"}},
            "repository": {"full_name": "owner/repo"},
        }
        key = compute_dedup_key("pull_request", "opened", payload)
        assert key == "pr:owner/repo:42:opened:abc123"

    def test_pr_different_actions_produce_different_keys(self) -> None:
        base = {
            "number": 42,
            "pull_request": {"number": 42, "head": {"sha": "abc123"}},
            "repository": {"full_name": "owner/repo"},
        }
        key_opened = compute_dedup_key("pull_request", "opened", base)
        key_closed = compute_dedup_key("pull_request", "closed", base)
        assert key_opened != key_closed


# ---------------------------------------------------------------------------
# Check run events
# ---------------------------------------------------------------------------


class TestCheckRunDedupKey:
    def test_check_run_completed(self) -> None:
        payload = {
            "check_run": {"id": 99},
            "repository": {"full_name": "owner/repo"},
        }
        key = compute_dedup_key("check_run", "completed", payload)
        assert key == "check_run:owner/repo:99:completed"


# ---------------------------------------------------------------------------
# Issue comment events
# ---------------------------------------------------------------------------


class TestIssueCommentDedupKey:
    def test_issue_comment_created(self) -> None:
        payload = {
            "comment": {"id": 555},
            "repository": {"full_name": "owner/repo"},
        }
        key = compute_dedup_key("issue_comment", "created", payload)
        assert key == "comment:owner/repo:555:created"


# ---------------------------------------------------------------------------
# Create / delete events
# ---------------------------------------------------------------------------


class TestCreateDeleteDedupKey:
    def test_create_branch(self) -> None:
        payload = {
            "ref_type": "branch",
            "ref": "feat/new",
            "repository": {"full_name": "owner/repo"},
        }
        key = compute_dedup_key("create", "", payload)
        assert key == "create:owner/repo:branch:feat/new"

    def test_delete_tag(self) -> None:
        payload = {
            "ref_type": "tag",
            "ref": "v1.0",
            "repository": {"full_name": "owner/repo"},
        }
        key = compute_dedup_key("delete", "", payload)
        assert key == "delete:owner/repo:tag:v1.0"


# ---------------------------------------------------------------------------
# Unknown event type fallback
# ---------------------------------------------------------------------------


class TestFallbackDedupKey:
    def test_unknown_type_uses_hash(self) -> None:
        payload = {"some": "data", "repository": {"full_name": "owner/repo"}}
        key = compute_dedup_key("unknown_event", "action", payload)
        assert key.startswith("unknown:")
        assert len(key) == len("unknown:") + 16

    def test_unknown_type_is_deterministic(self) -> None:
        payload = {"some": "data"}
        key1 = compute_dedup_key("unknown_event", "action", payload)
        key2 = compute_dedup_key("unknown_event", "action", payload)
        assert key1 == key2
