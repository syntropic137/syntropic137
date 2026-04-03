"""GitHub event availability by delivery mechanism.

GitHub delivers events through two mechanisms, each with different coverage:

1. **Webhooks** — Real-time HTTP POST to a configured URL. Covers all ~60+
   event types. Requires a publicly reachable endpoint (e.g., Cloudflare tunnel).
   https://docs.github.com/en/webhooks/webhook-events-and-payloads

2. **Events API** — ``GET /repos/{owner}/{repo}/events``. Polled by our
   background task. Only returns **17 event types** — notably missing the
   entire CI/CD surface (check runs, workflow runs, deployments).
   https://docs.github.com/en/rest/activity/events#list-repository-events

   The 17 supported types are enumerated here:
   https://docs.github.com/en/rest/using-the-rest-api/github-event-types

This module is the single source of truth for which events are available
via which mechanism. It is used by:

- **Trigger registration** — to warn when a trigger requires webhooks
- **Event type mapper** — to define the polling type map
- **Documentation** — this module IS the docs; see the EVENTS registry below

References:
    - Events API event types: https://docs.github.com/en/rest/using-the-rest-api/github-event-types
    - Webhook events & payloads: https://docs.github.com/en/webhooks/webhook-events-and-payloads
    - Events API endpoint: https://docs.github.com/en/rest/activity/events#list-repository-events
    - ISS-409: CI/CD events are webhook-only
"""

from __future__ import annotations

from enum import StrEnum
from typing import NamedTuple


class DeliveryChannel(StrEnum):
    """How a GitHub event can reach our system."""

    WEBHOOK = "webhook"
    """Real-time delivery via HTTP POST. Requires a public URL.

    See: https://docs.github.com/en/webhooks/about-webhooks
    """

    EVENTS_API = "events_api"
    """Polled via GET /repos/{owner}/{repo}/events. No public URL needed.

    See: https://docs.github.com/en/rest/activity/events#list-repository-events
    """

    BOTH = "both"
    """Available through both channels."""


class EventInfo(NamedTuple):
    """Metadata for a GitHub event type."""

    webhook_name: str
    """Webhook event name (e.g., ``"check_run"``, ``"push"``)."""

    events_api_name: str | None
    """Events API type name (e.g., ``"PushEvent"``), or None if webhook-only."""

    channel: DeliveryChannel
    """Which delivery channel(s) carry this event."""

    category: str
    """Grouping for documentation: ``"ci_cd"``, ``"code"``, ``"social"``, etc."""

    description: str
    """One-line description."""


# ---------------------------------------------------------------------------
# Event registry — the single source of truth
# ---------------------------------------------------------------------------

# fmt: off
EVENTS: tuple[EventInfo, ...] = (
    # -------------------------------------------------------------------------
    # Available via BOTH webhook and Events API polling.
    # These 17 types are the only ones the Events API returns.
    # https://docs.github.com/en/rest/using-the-rest-api/github-event-types
    # -------------------------------------------------------------------------
    EventInfo("push",                          "PushEvent",                          DeliveryChannel.BOTH, "code",    "Commits pushed to a branch"),                       # https://docs.github.com/en/webhooks/webhook-events-and-payloads#push
    EventInfo("pull_request",                  "PullRequestEvent",                   DeliveryChannel.BOTH, "code",    "PR opened, closed, merged, edited, etc."),           # https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request
    EventInfo("pull_request_review",           "PullRequestReviewEvent",             DeliveryChannel.BOTH, "code",    "PR review submitted"),                               # https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request_review
    EventInfo("pull_request_review_comment",   "PullRequestReviewCommentEvent",      DeliveryChannel.BOTH, "code",    "Comment on a PR diff"),                              # https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request_review_comment
    EventInfo("issue_comment",                 "IssueCommentEvent",                  DeliveryChannel.BOTH, "social",  "Comment on issue or PR"),                            # https://docs.github.com/en/webhooks/webhook-events-and-payloads#issue_comment
    EventInfo("issues",                        "IssuesEvent",                        DeliveryChannel.BOTH, "social",  "Issue opened, closed, labeled, etc."),               # https://docs.github.com/en/webhooks/webhook-events-and-payloads#issues
    EventInfo("create",                        "CreateEvent",                        DeliveryChannel.BOTH, "code",    "Branch or tag created"),                             # https://docs.github.com/en/webhooks/webhook-events-and-payloads#create
    EventInfo("delete",                        "DeleteEvent",                        DeliveryChannel.BOTH, "code",    "Branch or tag deleted"),                             # https://docs.github.com/en/webhooks/webhook-events-and-payloads#delete
    EventInfo("release",                       "ReleaseEvent",                       DeliveryChannel.BOTH, "code",    "Release published"),                                 # https://docs.github.com/en/webhooks/webhook-events-and-payloads#release
    EventInfo("fork",                          "ForkEvent",                          DeliveryChannel.BOTH, "social",  "Repository forked"),                                 # https://docs.github.com/en/webhooks/webhook-events-and-payloads#fork
    EventInfo("watch",                         "WatchEvent",                         DeliveryChannel.BOTH, "social",  "Repository starred"),                                # https://docs.github.com/en/webhooks/webhook-events-and-payloads#watch
    EventInfo("commit_comment",                "CommitCommentEvent",                 DeliveryChannel.BOTH, "code",    "Comment on a commit"),                               # https://docs.github.com/en/webhooks/webhook-events-and-payloads#commit_comment
    EventInfo("discussion",                    "DiscussionEvent",                    DeliveryChannel.BOTH, "social",  "Discussion created or answered"),                    # https://docs.github.com/en/webhooks/webhook-events-and-payloads#discussion
    EventInfo("gollum",                        "GollumEvent",                        DeliveryChannel.BOTH, "social",  "Wiki page created or updated"),                      # https://docs.github.com/en/webhooks/webhook-events-and-payloads#gollum
    EventInfo("member",                        "MemberEvent",                        DeliveryChannel.BOTH, "social",  "Collaborator added or removed"),                     # https://docs.github.com/en/webhooks/webhook-events-and-payloads#member
    EventInfo("public",                        "PublicEvent",                        DeliveryChannel.BOTH, "social",  "Repository made public"),                            # https://docs.github.com/en/webhooks/webhook-events-and-payloads#public
    EventInfo("sponsorship",                   "SponsorshipEvent",                   DeliveryChannel.BOTH, "social",  "Sponsorship activity"),                              # https://docs.github.com/en/webhooks/webhook-events-and-payloads#sponsorship

    # -------------------------------------------------------------------------
    # Webhook-only: CI/CD surface.
    # None of these are returned by the Events API — self-healing and CI
    # monitoring require a webhook URL (e.g., Cloudflare tunnel). (ISS-409)
    # https://docs.github.com/en/webhooks/webhook-events-and-payloads#check_run
    # -------------------------------------------------------------------------
    EventInfo("check_run",                     None,                                 DeliveryChannel.WEBHOOK, "ci_cd", "CI check result (e.g., each Actions job)"),          # https://docs.github.com/en/webhooks/webhook-events-and-payloads#check_run
    EventInfo("check_suite",                   None,                                 DeliveryChannel.WEBHOOK, "ci_cd", "CI check suite lifecycle"),                          # https://docs.github.com/en/webhooks/webhook-events-and-payloads#check_suite
    EventInfo("workflow_run",                  None,                                 DeliveryChannel.WEBHOOK, "ci_cd", "GitHub Actions workflow run lifecycle"),              # https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_run
    EventInfo("workflow_job",                  None,                                 DeliveryChannel.WEBHOOK, "ci_cd", "GitHub Actions individual job lifecycle"),            # https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_job
    EventInfo("deployment",                    None,                                 DeliveryChannel.WEBHOOK, "ci_cd", "Deployment created"),                                # https://docs.github.com/en/webhooks/webhook-events-and-payloads#deployment
    EventInfo("deployment_status",             None,                                 DeliveryChannel.WEBHOOK, "ci_cd", "Deployment status changed"),                         # https://docs.github.com/en/webhooks/webhook-events-and-payloads#deployment_status
    EventInfo("deployment_protection_rule",    None,                                 DeliveryChannel.WEBHOOK, "ci_cd", "Deployment protection rule activity"),               # https://docs.github.com/en/webhooks/webhook-events-and-payloads#deployment_protection_rule
    EventInfo("status",                        None,                                 DeliveryChannel.WEBHOOK, "ci_cd", "Commit status (legacy, pre-Checks API)"),            # https://docs.github.com/en/webhooks/webhook-events-and-payloads#status

    # -------------------------------------------------------------------------
    # Webhook-only: Security alerts.
    # https://docs.github.com/en/webhooks/webhook-events-and-payloads#code_scanning_alert
    # -------------------------------------------------------------------------
    EventInfo("code_scanning_alert",           None,                                 DeliveryChannel.WEBHOOK, "security", "Code scanning alert"),                            # https://docs.github.com/en/webhooks/webhook-events-and-payloads#code_scanning_alert
    EventInfo("dependabot_alert",              None,                                 DeliveryChannel.WEBHOOK, "security", "Dependabot alert"),                                # https://docs.github.com/en/webhooks/webhook-events-and-payloads#dependabot_alert
    EventInfo("secret_scanning_alert",         None,                                 DeliveryChannel.WEBHOOK, "security", "Secret scanning alert"),                           # https://docs.github.com/en/webhooks/webhook-events-and-payloads#secret_scanning_alert

    # -------------------------------------------------------------------------
    # Webhook-only: Admin & repository management.
    # https://docs.github.com/en/webhooks/webhook-events-and-payloads#branch_protection_rule
    # -------------------------------------------------------------------------
    EventInfo("branch_protection_rule",        None,                                 DeliveryChannel.WEBHOOK, "admin",   "Branch protection changed"),                       # https://docs.github.com/en/webhooks/webhook-events-and-payloads#branch_protection_rule
    EventInfo("repository_dispatch",           None,                                 DeliveryChannel.WEBHOOK, "admin",   "Custom repository_dispatch event"),                 # https://docs.github.com/en/webhooks/webhook-events-and-payloads#repository_dispatch
    EventInfo("workflow_dispatch",             None,                                 DeliveryChannel.WEBHOOK, "admin",   "Manual workflow trigger"),                          # https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_dispatch
    EventInfo("merge_group",                   None,                                 DeliveryChannel.WEBHOOK, "code",    "Merge queue activity"),                             # https://docs.github.com/en/webhooks/webhook-events-and-payloads#merge_group
)
# fmt: on

# ---------------------------------------------------------------------------
# Derived lookups (computed once at import time)
# ---------------------------------------------------------------------------

_BY_WEBHOOK_NAME: dict[str, EventInfo] = {e.webhook_name: e for e in EVENTS}


def get_event_info(webhook_event_name: str) -> EventInfo | None:
    """Look up event info by webhook name (e.g., ``"check_run"``)."""
    base = webhook_event_name.split(".")[0]
    return _BY_WEBHOOK_NAME.get(base)


def requires_webhook(webhook_event_name: str) -> bool:
    """Return True if this event type is only available via webhooks.

    Use this at trigger registration time to warn users who don't have
    a webhook URL configured.
    """
    info = get_event_info(webhook_event_name)
    if info is None:
        return False
    return info.channel == DeliveryChannel.WEBHOOK


def available_via_polling(webhook_event_name: str) -> bool:
    """Return True if this event type can be received via Events API polling."""
    info = get_event_info(webhook_event_name)
    if info is None:
        return False
    return info.channel in (DeliveryChannel.EVENTS_API, DeliveryChannel.BOTH)


def build_events_api_type_map() -> dict[str, str]:
    """Build the Events API type name → webhook name mapping.

    Only includes events that are actually available via the Events API.
    This replaces the manually maintained map in ``event_type_mapper.py``.
    """
    return {e.events_api_name: e.webhook_name for e in EVENTS if e.events_api_name is not None}


# ---------------------------------------------------------------------------
# Summary helpers (useful for CLI/API introspection)
# ---------------------------------------------------------------------------


def polling_supported_events() -> list[EventInfo]:
    """All events available via Events API polling."""
    return [e for e in EVENTS if e.channel in (DeliveryChannel.EVENTS_API, DeliveryChannel.BOTH)]


def webhook_only_events() -> list[EventInfo]:
    """All events that require webhook delivery."""
    return [e for e in EVENTS if e.channel == DeliveryChannel.WEBHOOK]


def webhook_only_by_category() -> dict[str, list[EventInfo]]:
    """Webhook-only events grouped by category."""
    result: dict[str, list[EventInfo]] = {}
    for e in webhook_only_events():
        result.setdefault(e.category, []).append(e)
    return result
