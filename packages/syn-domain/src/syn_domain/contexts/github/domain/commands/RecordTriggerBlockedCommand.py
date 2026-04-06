"""Record Trigger Blocked command.

Command to record that a trigger rule was blocked from firing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class RecordTriggerBlockedCommand:
    """Command to record a trigger block.

    Attributes:
        trigger_id: ID of the trigger rule that was blocked.
        guard_name: Which guard blocked the trigger.
        reason: Human-readable explanation.
        webhook_delivery_id: X-GitHub-Delivery header for traceability.
        event_type: GitHub event type (e.g. "check_run.completed").
        repository: Repository that received the webhook.
        pr_number: PR number if applicable.
        payload_summary: Key fields from the webhook payload.
        command_id: Unique identifier for this command.
    """

    trigger_id: str
    guard_name: str
    reason: str = ""
    webhook_delivery_id: str = ""
    event_type: str = ""
    repository: str = ""
    pr_number: int | None = None
    payload_summary: dict[str, Any] | None = None
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        return self.trigger_id
