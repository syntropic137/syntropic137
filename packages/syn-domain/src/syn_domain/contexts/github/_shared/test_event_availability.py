"""Tests for GitHub event availability registry."""

from __future__ import annotations

from syn_domain.contexts.github._shared.event_availability import (
    EVENTS,
    DeliveryChannel,
    available_via_polling,
    build_events_api_type_map,
    get_event_info,
    polling_supported_events,
    requires_webhook,
    webhook_only_by_category,
    webhook_only_events,
)


class TestEventRegistry:
    def test_all_events_have_required_fields(self) -> None:
        for e in EVENTS:
            assert e.webhook_name, f"Missing webhook_name: {e}"
            assert e.channel in DeliveryChannel, f"Invalid channel: {e}"
            assert e.category, f"Missing category: {e}"
            assert e.description, f"Missing description: {e}"

    def test_webhook_only_events_have_no_api_name(self) -> None:
        for e in EVENTS:
            if e.channel == DeliveryChannel.WEBHOOK:
                assert e.events_api_name is None, f"Webhook-only {e.webhook_name} has api name"

    def test_pollable_events_have_api_name(self) -> None:
        for e in EVENTS:
            if e.channel in (DeliveryChannel.EVENTS_API, DeliveryChannel.BOTH):
                assert e.events_api_name is not None, f"Pollable {e.webhook_name} missing api name"

    def test_no_duplicate_webhook_names(self) -> None:
        names = [e.webhook_name for e in EVENTS]
        assert len(names) == len(set(names))

    def test_no_duplicate_api_names(self) -> None:
        api_names = [e.events_api_name for e in EVENTS if e.events_api_name]
        assert len(api_names) == len(set(api_names))


class TestGetEventInfo:
    def test_known_event(self) -> None:
        info = get_event_info("push")
        assert info is not None
        assert info.webhook_name == "push"
        assert info.events_api_name == "PushEvent"

    def test_compound_event_strips_action(self) -> None:
        info = get_event_info("check_run.completed")
        assert info is not None
        assert info.webhook_name == "check_run"

    def test_unknown_event(self) -> None:
        assert get_event_info("nonexistent_event") is None


class TestRequiresWebhook:
    def test_ci_cd_events_require_webhook(self) -> None:
        assert requires_webhook("check_run") is True
        assert requires_webhook("check_suite") is True
        assert requires_webhook("workflow_run") is True
        assert requires_webhook("deployment") is True

    def test_compound_ci_cd_event(self) -> None:
        assert requires_webhook("check_run.completed") is True

    def test_pollable_events_do_not_require_webhook(self) -> None:
        assert requires_webhook("push") is False
        assert requires_webhook("pull_request") is False
        assert requires_webhook("issues") is False

    def test_unknown_event_returns_false(self) -> None:
        assert requires_webhook("nonexistent") is False


class TestAvailableViaPolling:
    def test_both_channel_events(self) -> None:
        assert available_via_polling("push") is True
        assert available_via_polling("pull_request") is True
        assert available_via_polling("issue_comment") is True

    def test_webhook_only_events(self) -> None:
        assert available_via_polling("check_run") is False
        assert available_via_polling("workflow_run") is False

    def test_unknown_event(self) -> None:
        assert available_via_polling("nonexistent") is False


class TestBuildEventsApiTypeMap:
    def test_returns_correct_mappings(self) -> None:
        type_map = build_events_api_type_map()
        assert type_map["PushEvent"] == "push"
        assert type_map["PullRequestEvent"] == "pull_request"
        assert type_map["IssueCommentEvent"] == "issue_comment"

    def test_excludes_webhook_only_events(self) -> None:
        type_map = build_events_api_type_map()
        # These are webhook-only — must NOT appear in the polling map
        assert "CheckRunEvent" not in type_map
        assert "CheckSuiteEvent" not in type_map
        assert "StatusEvent" not in type_map
        assert "WorkflowRunEvent" not in type_map

    def test_includes_all_pollable_events(self) -> None:
        type_map = build_events_api_type_map()
        pollable = polling_supported_events()
        assert len(type_map) == len(pollable)
        for e in pollable:
            assert e.events_api_name in type_map


class TestSummaryHelpers:
    def test_polling_supported_events_count(self) -> None:
        # GitHub Events API returns 17 event types
        events = polling_supported_events()
        assert len(events) == 17

    def test_webhook_only_events_not_empty(self) -> None:
        assert len(webhook_only_events()) > 0

    def test_webhook_only_by_category_includes_ci_cd(self) -> None:
        by_cat = webhook_only_by_category()
        assert "ci_cd" in by_cat
        ci_cd_names = [e.webhook_name for e in by_cat["ci_cd"]]
        assert "check_run" in ci_cd_names
        assert "workflow_run" in ci_cd_names
