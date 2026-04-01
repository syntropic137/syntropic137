"""Tests for Events API → NormalizedEvent mapper."""

from __future__ import annotations

from syn_domain.contexts.github.slices.event_pipeline.event_type_mapper import (
    map_events_api_to_normalized,
)
from syn_domain.contexts.github.slices.event_pipeline.normalized_event import EventSource


class TestEventTypeMapper:
    def test_maps_push_event(self) -> None:
        raw = {
            "id": "12345",
            "type": "PushEvent",
            "repo": {"name": "owner/repo"},
            "payload": {"after": "abc123"},
            "created_at": "2026-01-01T00:00:00Z",
        }
        result = map_events_api_to_normalized(raw, "inst-1")
        assert result is not None
        assert result.event_type == "push"
        assert result.repository == "owner/repo"
        assert result.installation_id == "inst-1"
        assert result.source == EventSource.EVENTS_API
        assert result.events_api_id == "12345"

    def test_maps_pull_request_event(self) -> None:
        raw = {
            "id": "67890",
            "type": "PullRequestEvent",
            "repo": {"name": "owner/repo"},
            "payload": {
                "action": "opened",
                "number": 42,
                "pull_request": {"number": 42, "updated_at": "2026-01-01T00:00:00Z"},
            },
            "created_at": "2026-01-01T00:00:00Z",
        }
        result = map_events_api_to_normalized(raw, "inst-1")
        assert result is not None
        assert result.event_type == "pull_request"
        assert result.action == "opened"

    def test_check_run_event_not_in_events_api(self) -> None:
        """CheckRunEvent is webhook-only — the Events API never returns it (ISS-409)."""
        raw = {
            "id": "111",
            "type": "CheckRunEvent",
            "repo": {"name": "owner/repo"},
            "payload": {"action": "completed", "check_run": {"id": 99}},
            "created_at": "2026-01-01T00:00:00Z",
        }
        assert map_events_api_to_normalized(raw, "inst-1") is None

    def test_maps_issue_comment_event(self) -> None:
        raw = {
            "id": "222",
            "type": "IssueCommentEvent",
            "repo": {"name": "owner/repo"},
            "payload": {"action": "created", "comment": {"id": 555}},
            "created_at": "2026-01-01T00:00:00Z",
        }
        result = map_events_api_to_normalized(raw, "inst-1")
        assert result is not None
        assert result.event_type == "issue_comment"

    def test_unmapped_type_returns_none(self) -> None:
        raw = {
            "id": "333",
            "type": "SomeUnknownEvent",
            "repo": {"name": "owner/repo"},
            "payload": {},
            "created_at": "2026-01-01T00:00:00Z",
        }
        assert map_events_api_to_normalized(raw, "inst-1") is None

    def test_enriches_payload_with_repository(self) -> None:
        """The mapper injects ``repository.full_name`` so dedup keys work."""
        raw = {
            "id": "444",
            "type": "PushEvent",
            "repo": {"name": "owner/repo"},
            "payload": {"after": "abc123"},
            "created_at": "2026-01-01T00:00:00Z",
        }
        result = map_events_api_to_normalized(raw, "inst-1")
        assert result is not None
        assert result.payload["repository"]["full_name"] == "owner/repo"

    def test_dedup_key_matches_webhook_for_push(self) -> None:
        """Push events from both sources should produce the same dedup key."""
        from syn_domain.contexts.github.slices.event_pipeline.dedup_keys import compute_dedup_key

        # Events API payload (mapped)
        raw = {
            "id": "555",
            "type": "PushEvent",
            "repo": {"name": "owner/repo"},
            "payload": {"after": "abc123"},
            "created_at": "2026-01-01T00:00:00Z",
        }
        events_api_event = map_events_api_to_normalized(raw, "inst-1")
        assert events_api_event is not None

        # Webhook payload
        webhook_payload = {
            "after": "abc123",
            "repository": {"full_name": "owner/repo"},
        }
        webhook_key = compute_dedup_key("push", "", webhook_payload)

        assert events_api_event.dedup_key == webhook_key
