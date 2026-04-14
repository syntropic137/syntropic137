"""Trigger Dispatch Completed domain event.

Emitted when a trigger's workflow dispatch completes successfully.
Provides audit trail for trigger lifecycle observability.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("github.TriggerDispatchCompleted", "v1")
class TriggerDispatchCompletedEvent(DomainEvent):
    """Event emitted when a trigger's workflow dispatch succeeds.

    Attributes:
        trigger_id: Unique identifier for the trigger rule.
        execution_id: ID of the dispatched workflow execution.
        workflow_id: Workflow that was dispatched.
    """

    trigger_id: str
    execution_id: str
    workflow_id: str = ""

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
