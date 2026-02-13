"""Trigger Fired domain event.

Emitted each time a trigger dispatches a workflow execution. Provides audit trail.
"""

from __future__ import annotations

from typing import Any

from event_sourcing import DomainEvent, event
from pydantic import Field, field_validator


@event("github.TriggerFired", "v1")
class TriggerFiredEvent(DomainEvent):
    """Event emitted when a trigger fires and dispatches a workflow.

    Attributes:
        trigger_id: Unique identifier for the trigger rule.
        execution_id: ID of the dispatched workflow execution.
        webhook_delivery_id: X-GitHub-Delivery header for idempotency.
        github_event_type: GitHub event type (e.g. "check_run.completed").
        repository: Repository that received the webhook.
        pr_number: PR number if applicable.
        payload_summary: Key fields from the webhook payload (not full payload).
    """

    trigger_id: str
    execution_id: str
    webhook_delivery_id: str = ""
    github_event_type: str = ""
    repository: str = ""
    pr_number: Any = None
    payload_summary: dict = Field(default_factory=dict)

    @field_validator("trigger_id")
    @classmethod
    def validate_trigger_id(cls, v: str) -> str:
        """Ensure trigger_id is provided."""
        if not v:
            raise ValueError("trigger_id is required")
        return v

    @field_validator("execution_id")
    @classmethod
    def validate_execution_id(cls, v: str) -> str:
        """Ensure execution_id is provided."""
        if not v:
            raise ValueError("execution_id is required")
        return v
