"""Trigger Blocked domain event.

Emitted when a trigger evaluation is blocked by a safety guard,
condition mismatch, or concurrency constraint. Provides audit trail
for trigger observability — answers "why didn't this trigger fire?"
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field, field_validator


@event("github.TriggerBlocked", "v1")
class TriggerBlockedEvent(DomainEvent):
    """Event emitted when a trigger is blocked from firing.

    Attributes:
        trigger_id: Trigger rule that was blocked.
        guard_name: Which guard blocked the trigger (e.g. "max_attempts",
            "cooldown", "concurrency", "conditions_not_met").
        reason: Human-readable explanation of why the trigger was blocked.
        webhook_delivery_id: X-GitHub-Delivery header for traceability.
        github_event_type: GitHub event type (e.g. "check_run.completed").
        repository: Repository that received the webhook.
        pr_number: PR number if applicable.
        payload_summary: Key fields from the webhook payload (not full payload).
    """

    trigger_id: str
    guard_name: str
    reason: str = ""
    webhook_delivery_id: str = ""
    github_event_type: str = ""
    repository: str = ""
    pr_number: int | None = None
    payload_summary: dict = Field(default_factory=dict)

    @field_validator("trigger_id")
    @classmethod
    def validate_trigger_id(cls, v: str) -> str:
        """Ensure trigger_id is provided."""
        if not v:
            raise ValueError("trigger_id is required")
        return v

    @field_validator("guard_name")
    @classmethod
    def validate_guard_name(cls, v: str) -> str:
        """Ensure guard_name is provided."""
        if not v:
            raise ValueError("guard_name is required")
        return v
