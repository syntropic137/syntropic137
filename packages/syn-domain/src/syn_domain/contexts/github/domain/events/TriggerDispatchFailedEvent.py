"""Trigger Dispatch Failed domain event.

Emitted when a trigger's workflow dispatch fails.
Provides audit trail for trigger lifecycle observability.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("github.TriggerDispatchFailed", "v1")
class TriggerDispatchFailedEvent(DomainEvent):
    """Event emitted when a trigger's workflow dispatch fails.

    Attributes:
        trigger_id: Unique identifier for the trigger rule.
        execution_id: ID of the attempted workflow execution.
        workflow_id: Workflow that failed to dispatch.
        failure_reason: Reason the dispatch failed.
    """

    trigger_id: str
    execution_id: str
    workflow_id: str = ""
    failure_reason: str = ""

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

    @field_validator("failure_reason")
    @classmethod
    def validate_failure_reason(cls, v: str) -> str:
        """Default empty failure_reason to 'unknown'."""
        return v if v else "unknown"
