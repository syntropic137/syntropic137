"""Trigger history entry read model.

Represents a single trigger firing in the audit log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003 - needed for runtime type annotations


@dataclass
class TriggerHistoryEntry:
    """Read model for a trigger firing history entry.

    Attributes:
        trigger_id: Trigger rule that fired.
        execution_id: Dispatched workflow execution ID.
        webhook_delivery_id: X-GitHub-Delivery header for idempotency.
        github_event_type: GitHub event type (e.g. "check_run.completed").
        repository: Repository that received the webhook.
        pr_number: PR number if applicable.
        payload_summary: Key fields from the webhook payload.
        fired_at: When the trigger fired.
        status: Execution status (dispatched, completed, failed).
        cost_usd: Cost of the triggered execution, if known.
    """

    trigger_id: str
    execution_id: str
    webhook_delivery_id: str = ""
    github_event_type: str = ""
    repository: str = ""
    pr_number: int | None = None
    payload_summary: dict = field(default_factory=dict)
    fired_at: datetime | None = None
    status: str = "dispatched"
    cost_usd: float | None = None
