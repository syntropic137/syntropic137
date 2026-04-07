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

    def test_checks_api_events_have_no_events_api_name(self) -> None:
        """CHECKS_API events use a different endpoint, not the Events API."""
        for e in EVENTS:
            if e.channel == DeliveryChannel.CHECKS_API:
                assert e.events_api_name is None, f"Checks API {e.webhook_name} has events api name"

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
    def test_webhook_only_ci_cd_events(self) -> None:
        assert requires_webhook("check_suite") is True
        assert requires_webhook("workflow_run") is True
        assert requires_webhook("deployment") is True

    def test_check_run_does_not_require_webhook(self) -> None:
        """check_run is available via Checks API polling (#602)."""
        assert requires_webhook("check_run") is False
        assert requires_webhook("check_run.completed") is False

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

    def test_checks_api_events(self) -> None:
        """check_run available via Checks API polling (#602)."""
        assert available_via_polling("check_run") is True
        assert available_via_polling("check_run.completed") is True

    def test_webhook_only_events(self) -> None:
        assert available_via_polling("workflow_run") is False
        assert available_via_polling("check_suite") is False

    def test_unknown_event(self) -> None:
        assert available_via_polling("nonexistent") is False


class TestBuildEventsApiTypeMap:
    def test_returns_correct_mappings(self) -> None:
        type_map = build_events_api_type_map()
        assert type_map["PushEvent"] == "push"
        assert type_map["PullRequestEvent"] == "pull_request"
        assert type_map["IssueCommentEvent"] == "issue_comment"

    def test_excludes_non_events_api_types(self) -> None:
        type_map = build_events_api_type_map()
        # These have no events_api_name — must NOT appear in the Events API map
        # (check_run uses Checks API, not Events API; others are webhook-only)
        assert "CheckRunEvent" not in type_map
        assert "CheckSuiteEvent" not in type_map
        assert "StatusEvent" not in type_map
        assert "WorkflowRunEvent" not in type_map

    def test_includes_all_events_api_pollable_events(self) -> None:
        type_map = build_events_api_type_map()
        # Only Events API + BOTH events have events_api_name entries.
        # CHECKS_API events (check_run) use a different endpoint.
        events_api_pollable = [
            e for e in polling_supported_events() if e.events_api_name is not None
        ]
        assert len(type_map) == len(events_api_pollable)
        for e in events_api_pollable:
            assert e.events_api_name in type_map


class TestSummaryHelpers:
    def test_polling_supported_events_count(self) -> None:
        # 17 Events API types + 1 Checks API type (check_run, #602)
        events = polling_supported_events()
        assert len(events) == 18

    def test_webhook_only_events_not_empty(self) -> None:
        assert len(webhook_only_events()) > 0

    def test_check_run_not_in_webhook_only(self) -> None:
        """check_run moved to CHECKS_API channel (#602)."""
        wo_names = [e.webhook_name for e in webhook_only_events()]
        assert "check_run" not in wo_names

    def test_check_run_in_polling_supported(self) -> None:
        """check_run available via Checks API polling (#602)."""
        poll_names = [e.webhook_name for e in polling_supported_events()]
        assert "check_run" in poll_names

    def test_webhook_only_by_category_includes_ci_cd(self) -> None:
        by_cat = webhook_only_by_category()
        assert "ci_cd" in by_cat
        ci_cd_names = [e.webhook_name for e in by_cat["ci_cd"]]
        assert "check_run" not in ci_cd_names  # Moved to CHECKS_API (#602)
        assert "workflow_run" in ci_cd_names
