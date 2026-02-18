"""Record Trigger Fired command.

Command to record that a trigger rule has fired and dispatched a workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class RecordTriggerFiredCommand:
    """Command to record a trigger firing.

    Attributes:
        trigger_id: ID of the trigger rule that fired.
        execution_id: ID of the dispatched workflow execution.
        webhook_delivery_id: X-GitHub-Delivery header for idempotency.
        event_type: GitHub event type (e.g. "check_run.completed").
        repository: Repository that received the webhook.
        workflow_id: Workflow being dispatched.
        workflow_inputs: Extracted inputs for the workflow.
        pr_number: PR number if applicable.
        payload_summary: Key fields from the webhook payload.
        command_id: Unique identifier for this command.
    """

    trigger_id: str
    execution_id: str
    webhook_delivery_id: str = ""
    event_type: str = ""
    repository: str = ""
    workflow_id: str = ""
    workflow_inputs: dict[str, Any] | None = None
    pr_number: int | None = None
    payload_summary: dict[str, Any] | None = None
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        return self.trigger_id
